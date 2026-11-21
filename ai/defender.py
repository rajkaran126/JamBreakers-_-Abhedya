"""AEGIS-LINK defender: sense -> classify -> decide.

Trigger: packet loss over the last 5 slots above 10 %. Then capture 3 spectrogram windows at the
receiver that is losing packets, run the CNN on each and average (the 3-window vote), and respond:

  barrage     covers the whole band, so hopping is pointless: raise power (+3 dB steps, cap +9 dB),
              then drop QPSK -> BPSK (+3 dB more margin)
  sweep       crosses every channel, so hopping only thrashes: raise power and hold, then BPSK
  random      blacklist the channels it is sitting on and hop to the cleanest one left
  reactive    it listens on one channel: switch to the key-derived fast hop sequence and blacklist
              the channel it is listening on, so it rarely hears us again
  deceptive   look-alike frames (authentication rejects them): hop away and blacklist that channel
  accidental  a friendly emitter, not an attack: no alarm, quietly move to a clean channel
  clean       loss but nothing in the spectrum: a link is blocked (building, hill): send a relay drone

Behaviour over time:
  follower    if the jammer lands on our new channel within 0.8 s of a hop, twice, it is following:
              switch to the key-derived fast hop sequence (it cannot predict HMAC(key, slot))
  hop guard   at most 3 hops in 5 s; when it trips, go to keyed fast hopping instead of sitting still
  recovery    when the band has been quiet for a while, step power back down, return to QPSK and
              leave fast-hop mode

It also estimates where the jammer is (RSSI least squares) every 0.5 s while the band is noisy.
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from sim.defenders import Action, Decision, Defender, HopGuard, LOSS_TRIGGER, SlotObs
from sim.radio import N_CH, NOISE_INBAND_DBM, POWER_CAP_DB, POWER_STEP_DB

from .cnn import load_shared
from .features import CLASSES
from .localize import ANNOUNCE_RADIUS_M, PUBLISH_RADIUS_M, locate

HOT_DB = 10.0                 # channel counts as occupied if its energy is this far above the noise floor
FOLLOW_WINDOW_S = 0.3
CALM_S = 6.0
LOCATE_EVERY_S = 0.5
EVAL_AFTER_ACTION_S = 0.05
EVAL_AFTER_HOLD_S = 0.25
ARENA = ((-300.0, 1200.0), (-400.0, 900.0))


class AegisDefender(Defender):
    name = "aegis"

    def __init__(self, rng=None):
        super().__init__(rng)
        self.cnn = load_shared()
        if self.cnn is None:
            raise ImportError("CNN weights missing (ai/weights/cnn_v1.npz); run python -m ai.train")
        self.guard = HopGuard(4, 5.0, 2.0)
        self.last_change_t = -10.0
        self.last_channel: Optional[int] = None
        self.last_action = ""
        self.follow_hits = 0
        self.calm_since: Optional[float] = None
        self.estimates: list[dict] = []
        self.events: list[tuple[str, str]] = []
        self._next_locate = 0.0
        self._announced = False
        self._next_eval = 0.0
        self.trail: deque[tuple[int, int]] = deque(maxlen=40)    # (our channel, hottest channel or -1) per slot

    # ---------- helpers ----------
    def _hot(self, obs: SlotObs) -> list[int]:
        return [c for c in range(N_CH) if obs.energy_dbm[c] > NOISE_INBAND_DBM + HOT_DB]

    def _cleanest(self, obs: SlotObs, exclude: set[int]) -> int:
        e = obs.energy_dbm.copy()
        for c in exclude | set(obs.blacklist):
            e[c] = np.inf
        if np.all(np.isinf(e)):
            e = obs.energy_dbm.copy()
            e[obs.channel] = np.inf
        return int(np.argmin(e))

    def _sense_node(self, obs: SlotObs) -> str:
        """Receiver of the node that is losing the most packets (its parent on the route)."""
        w = obs.world
        if w is None:
            return "CP"
        worst = min((n for n in w.node_ema if n != "CP" and n in w.net.index), key=lambda n: w.node_ema[n], default=None)
        return (w.net.parent.get(worst) or "CP") if worst else "CP"

    def spectrum_extras(self, window_db: np.ndarray) -> dict:
        r = self.cnn.predict(window_db, with_cam=True)
        out = {"probs": {c: round(float(p), 4) for c, p in zip(CLASSES, r["probs"])}, "verdict": r["class"],
               "confidence": round(r["confidence"], 4)}
        if r["class"] != "clean":
            out["gradcam"] = np.round(r["cam"], 2).tolist()
        return out

    # ---------- main ----------
    def _copies_us(self) -> Optional[int]:
        """While we hop every slot: does the jammed channel match where we were L slots ago? A follower
        re-tunes to our old channel, so one lag lines up far more often than chance (1 in 8)."""
        tr = list(self.trail)
        hot = [i for i, (_, h) in enumerate(tr) if h >= 0]
        if len(hot) < 10:
            return None
        for lag in (1, 2, 3, 4):
            pairs = [(tr[i][1], tr[i - lag][0]) for i in hot if i >= lag]
            if len(pairs) >= 8 and sum(a == b for a, b in pairs) / len(pairs) >= 0.5:
                return lag
        return None

    def on_slot(self, obs: SlotObs) -> Optional[Decision]:
        e = obs.energy_dbm
        k = int(np.argmax(e))
        self.trail.append((obs.channel, k if e[k] > NOISE_INBAND_DBM + HOT_DB else -1))
        if obs.channel != self.last_channel and obs.hop_mode == "dwell":
            self.last_change_t = obs.t
        self.last_channel = obs.channel
        self._localize(obs)
        if obs.control_pending:
            return None
        if obs.loss_recent <= LOSS_TRIGGER:
            return self._recover(obs)
        self.calm_since = None
        if obs.t < self._next_eval:
            return None

        node = self._sense_node(obs)
        vote = self.cnn.predict_vote([obs.sense(node) for _ in range(3)])
        cls, conf, ms = vote["class"], vote["confidence"], round(vote["ms"], 2)
        hot = self._hot(obs)
        if cls == "clean" and obs.channel in hot:
            cls = "random"                       # energy says otherwise: treat as narrowband interference
        if len(hot) >= 6 and cls != "sweep":
            cls = "barrage"                      # 6+ of 8 channels occupied: whole-band jamming, whatever one window looked like
        d = self._respond(obs, cls, conf, hot)
        # don't re-classify every 10 ms: soon after acting, later after deciding to hold
        self._next_eval = obs.t + (EVAL_AFTER_ACTION_S if d is not None else EVAL_AFTER_HOLD_S)
        if d is not None:
            d.decision_time_ms = ms
            self.last_action = d.action
        return d

    def _respond(self, obs: SlotObs, cls: str, conf: float, hot: list[int]) -> Optional[Decision]:
        ch, t = obs.channel, obs.t
        pct = f"{conf:.0%}"
        keyed = obs.hop_mode == "keyed"

        if cls in ("barrage", "sweep"):
            what = "Barrage covers the whole band" if cls == "barrage" else "Sweep crosses every channel"
            if obs.tx_boost_db < POWER_CAP_DB:
                acts = [Action("power", delta_db=POWER_STEP_DB)]
                if cls == "barrage" and obs.modulation == "QPSK":
                    acts.append(Action("rate", modulation="BPSK"))
                return Decision(cls, conf, "raise_power",
                                f"CNN sees {cls} ({pct}). {what}, so hopping won't help: raised power to "
                                f"+{min(obs.tx_boost_db + POWER_STEP_DB, POWER_CAP_DB):.0f} dB"
                                + (" and dropped to BPSK." if len(acts) > 1 else " and holding the channel."), acts)
            if obs.modulation == "QPSK":
                return Decision(cls, conf, "lower_rate", f"CNN sees {cls} ({pct}). Power is at maximum: dropped QPSK to BPSK for 3 dB more margin.",
                                [Action("rate", modulation="BPSK")])
            return None                           # everything is already at maximum: hold

        if cls == "clean":
            w = obs.world
            if w is not None and not any(n.kind == "relay" for n in w.net.nodes):
                worst = min((n for n in w.node_ema if n != "CP" and n in w.net.index), key=lambda n: w.node_ema[n])
                return Decision("clean", conf, "relay",
                                f"Loss {obs.loss_recent:.0%} but the spectrum is clean ({pct}): {worst}'s link is blocked. "
                                f"Sending a relay drone above the tallest obstacle.", [Action("relay", between=(worst, "CP"))])
            return None

        # follower: the jammer found our new channel right after a hop
        if cls in ("random", "reactive") and not keyed and self.last_action == "hop" and t - self.last_change_t < FOLLOW_WINDOW_S:
            # re-found within 100 ms counts double: a random jammer landing on our exact new channel that
            # fast is very unlikely, a follower does it every time
            self.follow_hits += 2 if t - self.last_change_t < 0.1 else 1
        elif cls not in ("random", "reactive"):
            self.follow_hits = 0
        if self.follow_hits >= 2 and not keyed:
            self.follow_hits = 0
            self.guard.record(t)
            return Decision(cls, conf, "fast_hop",
                            f"Jammer re-found our channel {1000 * (t - self.last_change_t):.0f} ms after the hop: it is following us. "
                            f"Switched to the key-derived hop sequence, a new channel every 10 ms that it cannot predict.",
                            [Action("mode", mode="keyed", anti_follow=True)], ch, None)

        if cls == "reactive" and keyed and not getattr(obs.world, "anti_follow", False) and self._copies_us() is not None:
            cls = "random"                       # behaviour says follower; handled by the keyed branch below
        if cls == "reactive":
            acts = [Action("blacklist", channels=(ch,), ttl_s=6.0)]
            if not keyed:
                acts.insert(0, Action("mode", mode="keyed"))
            self.guard.record(t)
            return Decision(cls, conf, "fast_hop",
                            f"CNN sees reactive jamming ({pct}): it only fires when it hears us on channel {ch}. "
                            f"{'Switched to keyed fast hopping and b' if not keyed else 'B'}lacklisted channel {ch}.", acts, ch, None)

        if keyed and not getattr(obs.world, "anti_follow", False):
            lag = self._copies_us()
            if lag is not None:
                self.trail.clear()
                return Decision("random", conf, "fast_hop",
                                f"The jammer copies the channel we used {lag * 10} ms earlier: it is following us. "
                                f"The key-derived sequence now never reuses the last 3 channels.",
                                [Action("mode", mode="keyed", anti_follow=True)], ch, None)

        if keyed:
            # already hopping every slot: keep it off channels that stay occupied. Against a follower the
            # channels we just used are skipped (it sits there, and the sequence already avoids them).
            anti = bool(getattr(obs.world, "anti_follow", False))
            recent = (set(getattr(obs.world, "recent_channels", ())) | {ch}) if anti else set()
            bl = tuple(sorted(set(hot) - recent))
            if not bl or set(bl) <= set(obs.blacklist):
                return None                       # nothing new to blacklist: stay quiet
            return Decision(cls, conf, "fast_hop", f"CNN sees {cls} ({pct}) while fast hopping: blacklisted channels {', '.join(map(str, bl))}.",
                            [Action("blacklist", channels=bl, ttl_s=3.0)], ch, None)

        if not self.guard.allowed(t):
            if obs.loss_recent < 0.5:
                return None                       # hop guard: hold instead of thrashing
            # holding would mean losing most packets: go to keyed fast hopping off the occupied channels
            return Decision(cls, conf, "fast_hop", f"Too many hops in 5 s and still losing {obs.loss_recent:.0%}: switched to keyed fast hopping.",
                            [Action("mode", mode="keyed"), Action("blacklist", channels=tuple(sorted(set(hot) | {ch})), ttl_s=3.0)], ch, None)

        ttl = {"random": 3.0, "deceptive": 15.0, "accidental": 6.0}.get(cls, 3.0)
        bl = set(hot) | {ch} if cls == "random" else {ch}
        to = self._cleanest(obs, bl)
        self.guard.record(t)
        reasons = {
            "random": f"CNN sees random-channel jamming ({pct}) on channel{'s' if len(hot) > 1 else ''} {', '.join(map(str, sorted(hot))) or ch}. Hopped {ch} → {to}.",
            "deceptive": f"CNN sees deceptive look-alike frames ({pct}) on channel {ch}; authentication rejects them, and we hopped {ch} → {to}.",
            "accidental": f"Interference on channel {ch} looks like a friendly emitter ({pct}), not an attack. No alarm; moved quietly to channel {to}.",
        }
        return Decision(cls, conf, "hop", reasons.get(cls, f"CNN sees {cls} ({pct}). Hopped {ch} → {to}."),
                        [Action("blacklist", channels=tuple(sorted(bl)), ttl_s=ttl), Action("hop", channel=to)], ch, to)

    def _recover(self, obs: SlotObs) -> Optional[Decision]:
        """Quiet band for a while: undo the emergency measures one step at a time."""
        busy = bool(self._hot(obs))
        if busy or (obs.tx_boost_db == 0 and obs.modulation == "QPSK" and obs.hop_mode != "keyed"):
            self.calm_since = None if busy else obs.t
            return None
        if self.calm_since is None:
            self.calm_since = obs.t
            return None
        if obs.t - self.calm_since < CALM_S:
            return None
        self.calm_since = obs.t
        if obs.hop_mode == "keyed":
            to = self._cleanest(obs, set())
            return Decision("clean", 0.99, "hop", f"Band quiet for {CALM_S:.0f} s: leaving fast-hop mode, settling on channel {to}.",
                            [Action("mode", mode="dwell", channel=to)], obs.channel, to)
        if obs.modulation == "BPSK":
            return Decision("clean", 0.99, "lower_rate", "Band quiet: back to QPSK (full data rate).", [Action("rate", modulation="QPSK")])
        return Decision("clean", 0.99, "raise_power", f"Band quiet: power back down to +{max(obs.tx_boost_db - POWER_STEP_DB, 0):.0f} dB.",
                        [Action("power", delta_db=-POWER_STEP_DB)])

    def _localize(self, obs: SlotObs) -> None:
        if obs.t < self._next_locate or obs.world is None:
            return
        self._next_locate = obs.t + LOCATE_EVERY_S
        pos, rssi, exps = obs.world.rssi_reports()
        if len(pos) < 4:                          # fewer than 4 nodes hear anything hostile
            self.estimates = []
            self._announced = False
            return
        est = locate(pos, rssi, ARENA, exps)
        if est is None or est.radius_m > PUBLISH_RADIUS_M:
            return
        x, y = float(np.clip(est.x, *ARENA[0])), float(np.clip(est.y, *ARENA[1]))
        self.estimates = [{"pos": [round(x, 1), round(y, 1)], "radius_m": round(est.radius_m, 1)}]
        nearest = obs.world.nearest_jammer_id(x, y)
        if nearest:
            self.estimates[0]["jammer_id"] = nearest
        if est.radius_m < ANNOUNCE_RADIUS_M and not self._announced:
            self._announced = True
            self.events.append(("info", f"Jammer located near ({x:.0f}, {y:.0f}) m, ±{est.radius_m:.0f} m"
                                        f" ({est.used} nodes{f', {est.dropped} blocked reading dropped' if est.dropped else ''})."))
