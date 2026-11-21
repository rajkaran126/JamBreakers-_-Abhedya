"""The simulated world: radio slots every 10 ms, broadcast every 50 ms.

SimWorld is one world (one network, one set of jammers, one defender). SimArena implements the
server's World interface and holds one world ('main') or two twins ('ai_off' and 'ai_on') that
share a seed and an attack timeline, so the side-by-side view shows the same attack twice.

Determinism: every source of randomness has its own stream from one SeedSequence (fading,
packets, jammers, control frames, spectrum, defender). The same seed and the same commands at the
same slots give the same run, and the twins see identical fading and jammer randomness.
"""
from __future__ import annotations

import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from backend import commands as C
from backend.protocol import ARENA_BOUNDS, CHANNELS_MHZ, CNN_CLASSES, FFT_BINS, F_START_MHZ, F_STOP_MHZ, JAMMER_TYPES, envelope

from .defenders import Action, Decision, Defender, SlotObs, make_defender
from .hopping import fixed_channel, keyed_channel, rendezvous_channel
from .jammers import Jammer, SlotCtx, make_jammer
from .network import ARENA_OBSTACLES, Network, Node, arena_nodes
from .phy import EmitterSpec, Phy, get_phy
from .radio import (
    N_CH, NOISE_INBAND_DBM, POWER_CAP_DB, RICIAN_K_DB_AIR, SLOT_S, TX_POWER_DBM, WINDOW_S, channel_offset_hz,
    dbm_to_mw, mw_to_dbm,
)

log = logging.getLogger("aegis.sim")
SRC = "sim"
SLOTS_PER_TICK = 5
KEY_EPOCH_S = 60.0
MAX_BLACKLIST = 4
CONTROL_MARGIN_DB = 12.0         # control frames: max power, BPSK, 4x repetition
STREAMS = ["fade", "pkt", "jam", "ctrl", "phy", "def"]
AI_ON_DEFENDER = "aegis"         # falls back to 'energy' until ai/defender.py exists
AI_OFF_DEFENDER = "fixed_hopping"


def mission_key_for(seed: int) -> bytes:
    """Phase 1 stand-in: a deterministic 32-byte key per seed. Phase 3 replaces this with the
    pre-loaded mission key and HKDF epochs."""
    return hashlib.sha256(b"AEGIS-LINK mission " + str(seed).encode()).digest()


def fingerprint(key: bytes) -> str:
    h = hashlib.sha256(b"fp" + key).hexdigest()[:16].upper()
    return ":".join(h[i:i + 4] for i in range(0, 16, 4))


@dataclass
class Pending:
    decision: Decision
    created_slot: int
    next_try: int
    attempts: int = 0


class SimWorld:
    def __init__(self, world_id: str, seed: int, defender: str, phy: Phy, spectrum_every: int = 1):
        self.world_id = world_id
        self.seed = seed
        self.phy = phy
        self.spectrum_every = spectrum_every
        ss = np.random.SeedSequence(seed)
        self.rng = {name: np.random.default_rng(s) for name, s in zip(STREAMS, ss.spawn(len(STREAMS)))}
        self.key = mission_key_for(seed)
        self.net = Network(arena_nodes(), [dict(o) for o in ARENA_OBSTACLES])
        self.jammers: list[Jammer] = []
        self._started: set[str] = set()
        self._launch_queue: list[Jammer] = []
        self._clear_pending = False
        self.slot = 0
        self.tick = 0
        self.outbox: list[dict] = []
        self.last_window: Optional[np.ndarray] = None
        self.last_bins: Optional[list[float]] = None
        self.set_defender(defender)
        self.channel = self.channel_for_slot(0)
        self._reset_metrics()
        self.net.update_geometry(0.0, self.jammers)
        self.net.route()

    # ---------- setup ----------
    def set_defender(self, name: str) -> None:
        self.defender: Defender = make_defender(name, self.rng["def"])
        self.defender_name = self.defender.name
        self.hop_mode = self.defender.initial_mode
        self.dwell_channel = 0
        self.blacklist: dict[int, float] = {}         # channel -> expiry time
        self.recent_channels: deque[int] = deque(maxlen=3)
        self.anti_follow = False
        self.pending: Optional[Pending] = None
        self.net.tx_boost_db = 0.0
        self.net.modulation = "QPSK"
        had_relay = any(n.kind == "relay" for n in self.net.nodes)
        self.net.remove_relays()
        if had_relay and hasattr(self.net, "positions"):
            self.net.update_geometry(self.t, self.jammers)
            self.net.route()
        self.ai_enabled = name not in ("fixed_hopping", "none")

    def _reset_metrics(self) -> None:
        self.recent: deque[tuple[int, int]] = deque(maxlen=100)     # (sent, delivered) per slot, last 1 s
        self.loss5: deque[tuple[int, int]] = deque(maxlen=5)
        self.total_sent = self.total_delivered = 0
        self.outage_ms = 0.0
        self.latencies: list[float] = []
        self.hops = 0
        self.frames_forged = 0
        self.frames_rejected = 0
        self.decision_time_ms: Optional[float] = None
        self.jam_start: Optional[int] = None
        self.node_ema = {n.id: 1.0 for n in self.net.nodes}

    @property
    def t(self) -> float:
        return self.slot * SLOT_S

    def launch(self, jammer: Jammer) -> None:
        self._launch_queue.append(jammer)

    def clear_jammers(self) -> None:
        self._clear_pending = True

    # ---------- channel plan ----------
    def active_blacklist(self) -> frozenset:
        return frozenset(c for c, exp in self.blacklist.items() if exp > self.t)

    def channel_for_slot(self, slot: int) -> int:
        if self.hop_mode == "fixed":
            return fixed_channel(slot)
        if self.hop_mode == "keyed":
            # never the last 3 channels (a follower re-tunes ~25 ms late) nor right next to the last one
            if not self.anti_follow:
                return keyed_channel(self.key, slot, self.active_blacklist())
            soft = {(self.recent_channels[-1] + d) % N_CH for d in (-1, 1)} if self.recent_channels else set()
            return keyed_channel(self.key, slot, self.active_blacklist(), set(self.recent_channels), soft)
        return self.dwell_channel

    def rendezvous(self, attempt: int = 0) -> int:
        """Key-derived control channel. Each retry moves to the next channel of a key-derived
        sequence, so a jammer parked on one channel cannot block the control link."""
        ch = rendezvous_channel(self.key, int(self.t // KEY_EPOCH_S) * 64 + attempt)
        bl = self.active_blacklist()
        while ch in bl and len(bl) < N_CH:
            ch = (ch + 1) % N_CH
        return ch

    # ---------- sensing ----------
    def sense(self, node_id: str = "CP") -> np.ndarray:
        """Spectrogram window (12 x 128 dBm) as the receiver at node_id would capture it right now."""
        net = self.net
        ni = net.index[node_id]
        ch = self.channel
        emitters: list[EmitterSpec] = []
        # our own traffic: the neighbour transmitting to this node in this TDMA slot
        clean_snr = TX_POWER_DBM - net.link_loss_db - NOISE_INBAND_DBM
        neighbours = [k for k, (i, j) in enumerate(net.pairs) if ni in (i, j) and clean_snr[k] > 10]
        if neighbours:
            k = neighbours[self.slot % len(neighbours)]
            rx = TX_POWER_DBM + net.tx_boost_db - net.link_loss_db[k]
            emitters.append(EmitterSpec("qpsk", float(rx), channel_offset_hz(ch), k_db=float(net.link_k_db[k]), label="own"))
        for a, jm in enumerate(self.jammers):
            if a < net.jam_gain_db.shape[0]:
                emitters.extend(jm.emitters(float(jm.power_dbm + net.jam_gain_db[a, ni]), self.t, self.rng["phy"]))
        return self.phy.synthesize(emitters, self.rng["phy"], t0=self.t)

    def rssi_reports(self, channel: Optional[int] = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """What each node's wideband receiver measures from hostile emitters: total received power over
        the 80 MHz band, averaged over 8 readings (fading), with 1 dB meter noise. Returns node
        positions, readings (dBm) and each node's path-loss exponent (the system knows which of its own
        nodes are airborne). Readings near the noise floor carry no information and are dropped."""
        from .network import AIRBORNE
        from .radio import NOISE_BAND_DBM, PL_EXPONENT_AIR, PL_EXPONENT_GROUND, RICIAN_K_DB_GROUND, rician_gain_db
        net, rng = self.net, self.rng["def"]
        n = len(net.nodes)
        total = np.zeros(n)
        for a, jm in enumerate(self.jammers):
            if jm.friendly:
                continue
            fades = rician_gain_db(rng, RICIAN_K_DB_GROUND, (8, n))
            total += dbm_to_mw(jm.power_dbm + net.jam_gain_db[a][None, :] + fades).mean(axis=0)
        meas = mw_to_dbm(total + dbm_to_mw(NOISE_BAND_DBM)) + rng.normal(0, 1.0, n)
        exps = np.array([PL_EXPONENT_AIR if nd.kind in AIRBORNE else PL_EXPONENT_GROUND for nd in net.nodes])
        keep = meas > NOISE_BAND_DBM + 10
        return net.positions[keep], meas[keep], exps[keep]

    def nearest_jammer_id(self, x: float, y: float) -> Optional[str]:
        """Ground truth, used only to tag an estimate for scoring and display."""
        if not self.jammers:
            return None
        return min(self.jammers, key=lambda j: (j.pos[0] - x) ** 2 + (j.pos[1] - y) ** 2).id

    # ---------- one radio slot ----------
    def step_slot(self) -> None:
        net = self.net
        if self.slot % SLOTS_PER_TICK == 0:
            self._apply_jammer_changes()
            net.update_geometry(self.t, self.jammers)
            net.route()
        ch = self.channel_for_slot(self.slot)
        self.channel = ch
        ctx = SlotCtx(self.slot, self.t, ch, self.rng["jam"])
        for jm in self.jammers:
            if jm.id not in self._started:
                jm.start(ctx)
                self._started.add(jm.id)
            jm.update(ctx)

        sinr, ok, i_mw = net.slot(self.jammers, ch, self.rng["fade"], self.rng["pkt"])
        sent = delivered = 0
        for nd in net.nodes:
            if nd.id == "CP" or nd.kind == "relay":
                continue
            path = net.path_links(nd.id)
            success = bool(path) and bool(np.all(ok[path]))
            sent += 1
            delivered += success
            self.node_ema[nd.id] = 0.85 * self.node_ema.get(nd.id, 1.0) + 0.15 * success
        self.recent.append((sent, delivered))
        self.loss5.append((sent, delivered))
        self.total_sent += sent
        self.total_delivered += delivered
        if sent and delivered / sent < 0.5:
            self.outage_ms += SLOT_S * 1000

        # forged look-alike frames reaching the command post are counted (and, from Phase 3, rejected)
        for a, jm in enumerate(self.jammers):
            if jm.forging and ch in jm.channels and jm.power_dbm + net.jam_gain_db[a, net.cp] > NOISE_INBAND_DBM + 6:
                self.frames_forged += 1
                self.frames_rejected += 1

        # jamming episode: hostile energy on our channel at a node on a route, and packets lost
        noise_mw = dbm_to_mw(NOISE_INBAND_DBM)
        hostile = any(not jm.friendly and jm.frac[ch] > 0 for jm in self.jammers)
        jammed = hostile and delivered < sent and float(np.max(i_mw)) > 2 * noise_mw
        if jammed:
            self._clear_slots = 0
            if self.jam_start is None:
                self.jam_start = self.slot
        elif self.jam_start is not None and self.pending is None:
            # 3 clean slots in a row without a hop of ours: the episode ended on its own
            self._clear_slots = getattr(self, "_clear_slots", 0) + 1
            if self._clear_slots >= 3:
                self.jam_start = None

        applied = self._control_plane()
        if self.pending is None and not applied:
            obs = self._observe(sent, delivered)
            t0 = time.perf_counter()
            decision = self.defender.on_slot(obs)
            if decision is not None:
                decision.decision_time_ms = decision.decision_time_ms or round((time.perf_counter() - t0) * 1000, 2)
                self.decision_time_ms = decision.decision_time_ms
                if decision.actions:
                    self.pending = Pending(decision, self.slot, self.slot + 1)
                else:
                    self._emit_decision(decision, latency=None)
            for level, text in getattr(self.defender, "events", []):
                self.outbox.append(envelope("event", SRC, world=self.world_id, level=level, text=text))
            if getattr(self.defender, "events", None):
                self.defender.events.clear()
        self.recent_channels.append(ch)
        self.slot += 1

    def _observe(self, sent: int, delivered: int) -> SlotObs:
        s = sum(x for x, _ in self.loss5)
        d = sum(y for _, y in self.loss5)
        energy = self.net.channel_energy_dbm(self.jammers, self.net.cp) + self.rng["def"].normal(0, 1.0, N_CH)
        return SlotObs(self.slot, self.t, self.channel, self.hop_mode, sent, delivered, 1 - d / s if s else 0.0,
                       energy, self.net.tx_boost_db, self.net.modulation, self.pending is not None,
                       self.active_blacklist(), self.sense, self)

    # ---------- control plane: decisions take effect only when their frame arrives ----------
    def _control_plane(self) -> None:
        p = self.pending
        if p is None or self.slot < p.next_try:
            return False
        rdv = self.rendezvous(p.attempts)
        ok = self.net.probe(self.jammers, rdv, self.rng["ctrl"], extra_db=CONTROL_MARGIN_DB)
        reached = []
        for nd in self.net.nodes:
            if nd.id == "CP":
                continue
            path = self.net.path_links(nd.id)
            reached.append(bool(path) and bool(np.all(ok[path])))
        if reached and np.mean(reached) >= 0.8:
            self._apply(p.decision)
            latency = None
            if p.decision.action in ("hop", "fast_hop") and self.jam_start is not None:
                latency = round((self.slot + 1 - self.jam_start) * SLOT_S * 1000, 1)
                self.latencies.append(latency)
                self.jam_start = None
            self._emit_decision(p.decision, latency)
            self.pending = None
            self.loss5.clear()          # judge the new channel on its own packets, not the old ones
            return True
        else:
            p.attempts += 1
            p.next_try = self.slot + min(2 ** (p.attempts - 1), 4)     # retry with back-off
            if p.attempts == 6:
                self.outbox.append(envelope("event", SRC, world=self.world_id, level="warn",
                                            text="Control frame not getting through yet; retrying across rendezvous channels."))
        return False

    def _apply(self, d: Decision) -> None:
        for a in d.actions:
            if a.kind == "hop" and a.channel is not None:
                self.hop_mode = "dwell"
                self.dwell_channel = a.channel
                self.hops += 1
            elif a.kind == "mode" and a.mode:
                if a.mode == "dwell" and self.hop_mode != "dwell":
                    self.dwell_channel = a.channel if a.channel is not None else self.channel
                if a.mode == "keyed":
                    self.anti_follow = self.anti_follow or a.anti_follow
                else:
                    self.anti_follow = False
                self.hop_mode = a.mode
                self.hops += 1
            elif a.kind == "power":
                self.net.tx_boost_db = float(np.clip(self.net.tx_boost_db + a.delta_db, 0.0, POWER_CAP_DB))
            elif a.kind == "rate" and a.modulation:
                self.net.modulation = a.modulation
            elif a.kind == "blacklist":
                for c in a.channels:
                    self.blacklist[c] = self.t + a.ttl_s
                # keep at least half the band usable: only the 4 most recent entries stay active
                active = sorted(self.active_blacklist(), key=lambda c: self.blacklist[c], reverse=True)
                for c in active[MAX_BLACKLIST:]:
                    self.blacklist.pop(c, None)
            elif a.kind == "relay":
                self._dispatch_relay(*a.between)

    def _dispatch_relay(self, a_id: str, b_id: str) -> None:
        if any(n.kind == "relay" for n in self.net.nodes):
            return
        pa, pb = self.net.nodes[self.net.index[a_id]].pos, self.net.nodes[self.net.index[b_id]].pos
        tallest = max([o["size"][2] for o in self.net.obstacles] + [0.0])
        mid = (pa + pb) / 2
        mid[2] = tallest + 30.0
        relay = Node("R1", "relay", pos=mid)
        self.net.add_node(relay)
        self.node_ema["R1"] = 1.0
        self.net.update_geometry(self.t, self.jammers)     # link arrays must include the new node now
        self.net.route()
        self.outbox.append(envelope("event", SRC, world=self.world_id, level="good",
                                    text=f"Relay drone R1 on station at {mid[2]:.0f} m between {a_id} and {b_id}."))

    def _emit_decision(self, d: Decision, latency: Optional[float]) -> None:
        msg = envelope("decision", SRC, world=self.world_id, sim_time_s=round(self.t, 3), confidence=round(d.confidence, 3),
                       action=d.action, latency_ms=latency, reason=d.reason, defender=self.defender_name,
                       node_ids=[n.id for n in self.net.nodes])
        msg["class"] = d.cls
        if d.from_channel is not None:
            msg["from_channel"] = d.from_channel
        if d.to_channel is not None:
            msg["to_channel"] = d.to_channel
        self.outbox.append(msg)
        text = d.reason if latency is None else f"{d.reason} Done in {latency:.0f} ms."
        level = "info" if d.action == "ignore" or d.cls in ("accidental", "clean") else "good"
        self.outbox.append(envelope("event", SRC, world=self.world_id, level=level, text=text))

    def _apply_jammer_changes(self) -> None:
        if self._clear_pending:
            self.jammers.clear()
            self._started.clear()
            self._clear_pending = False
            self.net.tx_boost_db = 0.0
            self.net.modulation = "QPSK"
            self.blacklist.clear()
            self.jam_start = None
            if self.hop_mode == "keyed" and self.defender_name != "fixed_hopping":
                self.anti_follow = False
                self.hop_mode = "dwell"
                self.dwell_channel = self.channel_for_slot(self.slot)
        if self._launch_queue:
            self.jammers.extend(self._launch_queue)
            self._launch_queue.clear()

    # ---------- per broadcast tick ----------
    def run_slots(self, n: int) -> None:
        for _ in range(n):
            self.step_slot()

    def kpis(self) -> dict[str, Any]:
        s = sum(x for x, _ in self.recent)
        d = sum(y for _, y in self.recent)
        lat = sorted(self.latencies)
        links = self.link_msgs()
        return {
            "delivery_pct": round(100 * d / s, 1) if s else 100.0,
            "delivery_total_pct": round(100 * self.total_delivered / self.total_sent, 1) if self.total_sent else 100.0,
            "hop_latency_ms": round(float(np.median(lat)), 1) if lat else None,
            "hop_latency_p95_ms": round(float(np.percentile(lat, 95)), 1) if lat else None,
            "outage_ms": round(self.outage_ms, 1),
            "healthy_links": sum(1 for l in links if l["routed"] and l["status"] == "ok"),
            "total_links": sum(1 for l in links if l["routed"]),
            "hops": self.hops,
            "decision_time_ms": self.decision_time_ms,
            "frames_verified": self.total_delivered,
            "frames_rejected": self.frames_rejected,
            "frames_forged": self.frames_forged,
        }

    def link_msgs(self) -> list[dict[str, Any]]:
        net = self.net
        routed = set()
        for nid, p in net.parent.items():
            if p is not None:
                routed.add(net.pair_index[tuple(sorted((net.index[nid], net.index[p])))])
        out = []
        for k, (i, j) in enumerate(net.pairs):
            is_routed = k in routed
            if not is_routed and net.sinr_ema[k] < 15:
                continue
            pdr = float(net.pdr_ema[k])
            status = "ok" if pdr >= 0.9 else ("degraded" if pdr >= 0.5 else "down")
            out.append({"a": net.nodes[i].id, "b": net.nodes[j].id, "sinr_db": round(float(net.sinr_ema[k]), 1),
                        "status": status, "channel": self.channel, "delivery_pct": round(100 * pdr, 1), "routed": is_routed})
        return out

    def state_msg(self, view: str, paused: bool, speed: int) -> dict[str, Any]:
        net = self.net
        nodes = []
        for nd in net.nodes:
            e = self.node_ema.get(nd.id, 1.0)
            status = "ok" if nd.id == "CP" or e >= 0.9 else ("degraded" if e >= 0.5 else "down")
            nodes.append({"id": nd.id, "kind": nd.kind, "pos": [round(float(v), 2) for v in nd.pos],
                          "heading_deg": round(nd.heading, 1), "channel": self.channel,
                          "tx_power_dbm": TX_POWER_DBM + net.tx_boost_db, "modulation": net.modulation, "status": status,
                          **({"parent": net.parent.get(nd.id)} if net.parent.get(nd.id) else {})})
        return envelope("state", SRC, world=self.world_id, tick=self.tick, sim_time_s=round(self.t, 3),
                        ai_enabled=self.ai_enabled, defender=self.defender_name, hop_mode=self.hop_mode, anti_follow=self.anti_follow, view=view,
                        mode="arena", scenario=None, paused=paused, speed=speed, nodes=nodes, links=self.link_msgs(),
                        jammers=[j.to_msg() for j in self.jammers], estimates=getattr(self.defender, "estimates", []),
                        obstacles=net.obstacles, blacklist=sorted(self.active_blacklist()), kpis=self.kpis())

    def spectrum_msg(self) -> dict[str, Any]:
        w = self.sense("CP")
        self.last_window = w
        bins = mw_to_dbm(dbm_to_mw(w).mean(axis=0))
        msg = envelope("spectrum", SRC, world=self.world_id, node_id="CP", f_start_mhz=F_START_MHZ, f_stop_mhz=F_STOP_MHZ,
                       bins=[round(float(b), 1) for b in bins], anomaly=bool(np.max(bins) > NOISE_INBAND_DBM - 6 + 20))
        extra = getattr(self.defender, "spectrum_extras", None)
        if callable(extra):
            msg.update(extra(w))
        return msg

    def tick_messages(self, view: str, paused: bool, speed: int, with_spectrum: bool = True) -> list[dict]:
        self.tick += 1
        out = [self.state_msg(view, paused, speed)]
        if with_spectrum and self.tick % self.spectrum_every == 0:
            out.append(self.spectrum_msg())
        out.extend(self.outbox)
        self.outbox = []
        return out


class SimArena:
    """World interface for the server."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.seed = cfg.seed
        self.phy = get_phy(cfg.signal_backend)
        self.view = "single"
        self.ai_enabled = True
        self.paused = False
        self.speed = 1
        self.leaderboard: dict[str, int] = {}
        self._acc = 0.0
        self._jid = 0
        self._active: list[tuple] = []        # (type, pos, power, owner) currently deployed
        self._build()
        if self.phy.name != cfg.signal_backend:
            self._notice = f"Signal backend '{cfg.signal_backend}' unavailable; using '{self.phy.name}'."
        else:
            self._notice = None

    def _build(self, relaunch_after_s: Optional[float] = None) -> None:
        if self.view == "single":
            self.worlds = {"main": SimWorld("main", self.seed, AI_ON_DEFENDER if self.ai_enabled else AI_OFF_DEFENDER, self.phy)}
        else:
            self.worlds = {"ai_off": SimWorld("ai_off", self.seed, AI_OFF_DEFENDER, self.phy, spectrum_every=2),
                           "ai_on": SimWorld("ai_on", self.seed, AI_ON_DEFENDER, self.phy)}
        self._acc = 0.0
        self._relaunch_at = relaunch_after_s if self._active else None

    def _new_jammer_set(self, jtype, pos, power, owner) -> str:
        self._jid += 1
        jid = f"J{self._jid}"
        for w in self.worlds.values():
            w.launch(make_jammer(jid, jtype, pos, power, owner))
        return jid

    # ---------- World protocol ----------
    def hello_info(self) -> dict[str, Any]:
        w = next(iter(self.worlds.values()))
        return {"server_version": "0.2.0", "schema_version": "1.0", "world_source": "sim", "signal_backend": self.phy.name,
                "channels_mhz": CHANNELS_MHZ, "fft_bins": FFT_BINS, "bounds": ARENA_BOUNDS,
                "jammer_types": [t for t in JAMMER_TYPES if t != "smart"], "classes": CNN_CLASSES,
                "ai_enabled": self.ai_enabled, "view": self.view, "key_fingerprint": fingerprint(w.key),
                "ai_off_defender": AI_OFF_DEFENDER, "ai_on_defender": w.defender_name if w.ai_enabled else AI_ON_DEFENDER,
                "obstacles": w.net.obstacles}

    def step(self, dt: float) -> list[dict]:
        out: list[dict] = []
        if self._notice:
            out.append(envelope("event", SRC, level="warn", text=self._notice))
            self._notice = None
        if not self.paused:
            self._acc += dt * self.speed
            n = int(self._acc / SLOT_S + 1e-9)
            # never more than 2x the normal work per tick: an overloaded laptop slows simulated time a
            # little instead of falling further behind each tick (no death spiral, no frozen screens)
            n = min(n, 2 * SLOTS_PER_TICK * self.speed)
            self._acc -= n * SLOT_S
            self._acc = min(self._acc, SLOT_S)
            for w in self.worlds.values():
                w.run_slots(n)
            if self._relaunch_at is not None and next(iter(self.worlds.values())).t >= self._relaunch_at:
                self._relaunch_at = None
                for jtype, pos, power, owner in self._active:
                    self._new_jammer_set(jtype, pos, power, owner)
                out.append(envelope("event", SRC, level="alert", text="Same attack launched in both worlds."))
        for w in self.worlds.values():
            out.extend(w.tick_messages(self.view, self.paused, self.speed, with_spectrum=not self.paused))
        return out

    def handle(self, cmd: C.Command) -> list[dict]:
        rid = {"req_id": cmd.id} if cmd.id else {}
        ev = lambda level, text: envelope("event", SRC, level=level, text=text, **rid)  # noqa: E731
        if isinstance(cmd, C.LaunchJammer):
            if cmd.jammer_type == "smart":
                return [envelope("error", SRC, code="not_implemented", message="The smart jammer arrives in a later phase.", **rid)]
            x = float(np.clip(cmd.pos[0], *ARENA_BOUNDS["x"]))
            y = float(np.clip(cmd.pos[1], *ARENA_BOUNDS["y"]))
            jid = self._new_jammer_set(cmd.jammer_type, (x, y), cmd.power_dbm, cmd.player)
            self._active.append((cmd.jammer_type, (x, y), cmd.power_dbm, cmd.player))
            out = [ev("alert", f"{cmd.player or 'Someone'} launched a {cmd.jammer_type} jammer ({jid}) at ({x:.0f}, {y:.0f}).")]
            if cmd.player:
                self.leaderboard[cmd.player] = self.leaderboard.get(cmd.player, 0) + 1
                out.append(envelope("score", SRC, leaderboard=[{"player": p, "attacks": n} for p, n in
                                                               sorted(self.leaderboard.items(), key=lambda kv: -kv[1])]))
            return out
        if isinstance(cmd, C.ClearJammers):
            self._active.clear()
            for w in self.worlds.values():
                w.clear_jammers()
            return [ev("good", "All jammers cleared.")]
        if isinstance(cmd, C.ToggleAI):
            self.ai_enabled = (not self.ai_enabled) if cmd.enabled is None else cmd.enabled
            if "main" in self.worlds:
                self.worlds["main"].set_defender(AI_ON_DEFENDER if self.ai_enabled else AI_OFF_DEFENDER)
            name = self.worlds["main"].defender_name if "main" in self.worlds else ""
            return [ev("info", f"AI defender {'ON' if self.ai_enabled else 'OFF'}"
                       + (" (conventional fixed-pattern hopping)." if not self.ai_enabled else f" ({name}).")) ]
        if isinstance(cmd, C.SetView):
            self.view = cmd.view
            self._build(relaunch_after_s=1.0)
            if cmd.view == "side_by_side":
                return [ev("info", "Side by side: AI OFF (fixed hopping, left) vs AI ON (right). Same seed, same attack from t = 1 s.")]
            return [ev("info", "Single view.")]
        if isinstance(cmd, C.Pause):
            self.paused = True
            return [ev("info", "Paused.")]
        if isinstance(cmd, C.Play):
            self.paused = False
            return [ev("info", "Playing.")]
        if isinstance(cmd, C.SetSpeed):
            self.speed = cmd.speed
            return [ev("info", f"Speed {cmd.speed}x.")]
        if isinstance(cmd, C.Restart):
            self._active.clear()
            self.paused = False
            self._build()
            return [ev("info", "Restarted from t = 0 with the same seed.")]
        return [envelope("error", SRC, code="not_implemented", message=f"'{cmd.action}' arrives in a later phase.", **rid)]
