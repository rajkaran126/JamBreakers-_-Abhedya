"""Interference engine: jammer behaviours.

Each jammer, once per 10 ms slot, decides which channels it hits and how hard (`frac`: the
fraction of its EIRP that lands inside our 2.7 MHz signal on each channel, linear). The link budget
uses `frac`; the spectrogram uses `emitters()`, which describes the actual waveform.

  barrage     noise over the whole 80 MHz band, all the time
  random      noise on 3 random channels, re-picked after a random 0.4-1.5 s dwell
  sweep       a tone sweeping the band every 1.2 ms (hits every channel briefly, over and over)
  reactive    listens on one channel and jams only while it hears a packet; rescans when idle
  deceptive   transmits look-alike QPSK frames on the channel it found (collisions + forged frames)
  accidental  a friendly emitter: bursty OFDM on one channel, low duty cycle, no hostile intent
  follower    wideband sensor: re-tunes to our channel ~25 ms after we hop, and learns any
              repeating hop pattern so it can jump to the next channel before we do
  smart       an adaptive adversary: every second a UCB1 bandit picks one of five tactics
              (follow, predict, wide, pulse, spoof) and scores it by how often it actually landed
              on our channel. It only uses channels it has heard us on.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .phy import EmitterSpec
from .radio import FS, N_CH, NARROW_JAM_BW_HZ, SIG_BW_HZ, SLOT_S, WINDOW_ROWS, channel_offset_hz

NARROW_FRAC = min(1.0, SIG_BW_HZ / NARROW_JAM_BW_HZ)      # 0.54
WIDE_FRAC = SIG_BW_HZ / FS                                # 0.034 (barrage over 80 MHz)
SWEEP_BURST_PENALTY = 2.0                                 # bursty hits hurt coded packets more than their average power

DEFAULT_POWER_DBM = {"barrage": 40.0, "random": 37.0, "sweep": 40.0, "reactive": 34.0, "deceptive": 32.0,
                     "accidental": 20.0, "follower": 34.0, "smart": 36.0,
                     "novel": 38.0, "novel_staircase": 38.0}


@dataclass
class SlotCtx:
    slot: int
    t: float
    our_channel: int
    rng: np.random.Generator


@dataclass
class Jammer:
    id: str
    type: str
    pos: list[float]
    power_dbm: float
    owner: Optional[str] = None
    friendly: bool = False
    frac: np.ndarray = field(default_factory=lambda: np.zeros(N_CH))
    channels: list[int] = field(default_factory=list)
    forging: bool = False          # sending look-alike frames this slot (deceptive)

    def start(self, ctx: SlotCtx) -> None:
        """Called once on the first slot after launch."""

    def update(self, ctx: SlotCtx) -> None:
        raise NotImplementedError

    def emitters(self, rx_dbm: float, t: float, rng: np.random.Generator) -> list[EmitterSpec]:
        """Waveforms at a receiver where this jammer's total power is rx_dbm."""
        return []

    def to_msg(self) -> dict:
        m = {"id": self.id, "type": self.type, "pos": [round(v, 1) for v in self.pos], "power_dbm": self.power_dbm,
             "channels": sorted(self.channels), "active": bool(self.channels), "airborne": getattr(self, "route", None) is not None and self.pos[2] > 20}
        if self.owner:
            m["owner"] = self.owner
        return m


def _narrow(ch: int, rx_dbm: float, gate=None) -> EmitterSpec:
    return EmitterSpec("noise", rx_dbm, channel_offset_hz(ch), NARROW_JAM_BW_HZ, gate=gate)


class Barrage(Jammer):
    def update(self, ctx):
        self.frac = np.full(N_CH, WIDE_FRAC)
        self.channels = list(range(N_CH))

    def emitters(self, rx_dbm, t, rng):
        return [EmitterSpec("noise", rx_dbm, 0.0, FS * 0.97)]


class RandomJ(Jammer):
    n = 3
    dwell_s = (0.4, 1.5)

    def start(self, ctx):
        self.next_pick = ctx.slot

    def update(self, ctx):
        if ctx.slot >= self.next_pick:
            self.channels = sorted(ctx.rng.choice(N_CH, self.n, replace=False).tolist())
            self.next_pick = ctx.slot + int(ctx.rng.uniform(*self.dwell_s) / SLOT_S)
        self.frac = np.zeros(N_CH)
        self.frac[self.channels] = NARROW_FRAC / self.n

    def emitters(self, rx_dbm, t, rng):
        return [_narrow(c, rx_dbm - 10 * np.log10(self.n)) for c in self.channels]


class Sweep(Jammer):
    period_s = 1.2e-3

    def update(self, ctx):
        self.frac = np.full(N_CH, WIDE_FRAC * SWEEP_BURST_PENALTY)
        self.channels = list(range(N_CH))

    def emitters(self, rx_dbm, t, rng):
        f0 = ((t % self.period_s) / self.period_s) * FS - FS / 2
        return [EmitterSpec("chirp", rx_dbm, chirp_f0_hz=f0, chirp_rate_hz_s=FS / self.period_s)]


class Reactive(Jammer):
    idle_timeout_slots = 12      # 120 ms without hearing us -> start scanning
    scan_dwell_slots = 3

    def start(self, ctx):
        self.monitor = ctx.our_channel
        self.last_heard = ctx.slot
        self.hit = False

    def update(self, ctx):
        self.hit = ctx.our_channel == self.monitor
        if self.hit:
            self.last_heard = ctx.slot
        elif ctx.slot - self.last_heard > self.idle_timeout_slots and (ctx.slot - self.last_heard) % self.scan_dwell_slots == 0:
            self.monitor = (self.monitor + 1) % N_CH
        self.frac = np.zeros(N_CH)
        if self.hit:
            self.frac[self.monitor] = NARROW_FRAC
        self.channels = [self.monitor] if self.hit else []

    def emitters(self, rx_dbm, t, rng):
        if not self.hit:
            return []
        onset = int(rng.integers(2, 6))      # reacts a few microseconds after our packet starts
        gate = np.zeros(WINDOW_ROWS)
        gate[onset:] = 1
        return [_narrow(self.monitor, rx_dbm, gate)]


class Deceptive(Jammer):
    duty = 0.6

    def start(self, ctx):
        self.channel = ctx.our_channel

    def update(self, ctx):
        self.forging = bool(ctx.rng.random() < self.duty)
        self.frac = np.zeros(N_CH)
        if self.forging:
            self.frac[self.channel] = 1.0       # same modulation and bandwidth as us: all of it lands in-band
        self.channels = [self.channel] if self.forging else []

    def emitters(self, rx_dbm, t, rng):
        if not self.forging:
            return []
        # look-alike frames: same modulation, imperfect carrier sync (~1 MHz off), short frames with gaps
        pattern = np.array([1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1], dtype=float)
        gate = np.roll(pattern, int(rng.integers(0, 5)))
        offset = float(rng.choice([-1.0, 1.0])) * float(rng.uniform(0.8, 1.3)) * 1e6
        return [EmitterSpec("qpsk", rx_dbm, channel_offset_hz(self.channel) + offset, gate=gate)]


class Accidental(Jammer):
    duty = 0.35

    def start(self, ctx):
        self.channel = ctx.our_channel
        self.friendly = True

    def update(self, ctx):
        on = bool(ctx.rng.random() < self.duty)
        self.frac = np.zeros(N_CH)
        if on:
            self.frac[self.channel] = min(1.0, SIG_BW_HZ / 4e6)
        self.channels = [self.channel] if on else []

    def emitters(self, rx_dbm, t, rng):
        if not self.channels:
            return []
        a = int(rng.integers(0, 8))
        b = min(WINDOW_ROWS, a + int(rng.integers(2, 6)))   # short bursts
        gate = np.zeros(WINDOW_ROWS)
        gate[a:b] = 1
        return [EmitterSpec("ofdm", rx_dbm, channel_offset_hz(self.channel), 4e6, gate=gate)]


class Follower(Jammer):
    reaction_slots = 3           # ~25 ms to detect our new channel and re-tune
    max_period = 16

    def start(self, ctx):
        self.observed: deque[int] = deque(maxlen=64)
        self.pending: deque[int] = deque([ctx.our_channel] * self.reaction_slots, maxlen=self.reaction_slots)
        self.target = ctx.our_channel
        self.predicting = False

    def _period(self) -> Optional[int]:
        h = list(self.observed)
        for p in range(2, self.max_period + 1):
            if len(h) >= 3 * p and h[-p:] == h[-2 * p:-p] == h[-3 * p:-2 * p] and len(set(h[-p:])) > 1:
                return p
        return None

    def update(self, ctx):
        # what it sees now becomes known only after the reaction delay
        self.observed.append(self.pending[0])
        self.pending.append(ctx.our_channel)
        p = self._period()
        self.predicting = p is not None
        if p is not None:
            # observed[-1] is slot s-R. The pattern says ch(s) = ch(s - m*p) for the smallest m*p >= R.
            r = self.reaction_slots
            m = -(-r // p)
            self.target = self.observed[-(m * p - r + 1)]
        else:
            self.target = self.observed[-1]
        self.frac = np.zeros(N_CH)
        self.frac[self.target] = NARROW_FRAC
        self.channels = [self.target]

    def emitters(self, rx_dbm, t, rng):
        return [_narrow(self.target, rx_dbm)]


class Novel(Jammer):
    """A jammer the CNN never saw in training (for the open-set test): a 'comb' that alternates between the
    even and the odd channels every 2 rows of the window, a checkerboard in time x frequency. It exists to
    show what the AI does with something new: say 'unknown', fall back to a safe response, and remember it."""
    def update(self, ctx):
        self.channels = list(range(N_CH))
        self.frac = np.full(N_CH, NARROW_FRAC / 4 * 0.5)          # 4 channels at a time, half the time each

    def emitters(self, rx_dbm, t, rng):
        out = []
        for parity in (0, 1):
            gate = np.zeros(WINDOW_ROWS)
            for r in range(WINDOW_ROWS):
                if (r // 2) % 2 == parity:
                    gate[r] = 1
            for c in range(parity, N_CH, 2):
                out.append(EmitterSpec("noise", rx_dbm - 10 * np.log10(4), channel_offset_hz(c), 0.6e6, gate=gate))
        return out


class NovelStaircase(Jammer):
    """A second never-seen pattern (benchmark only): a block of 3 adjacent channels that steps DOWN the band
    every 3 rows of the window, switched on half the time. Unlike the sweep it is narrow and moves the other
    way; unlike the comb it is contiguous. Used to check that 'unknown' is not just the comb."""
    def update(self, ctx):
        self.channels = list(range(N_CH))
        self.frac = np.full(N_CH, NARROW_FRAC * 3 / N_CH * 0.5)

    def emitters(self, rx_dbm, t, rng):
        out = []
        start = int(t * 1000) % N_CH
        for r0 in range(0, WINDOW_ROWS, 3):
            gate = np.zeros(WINDOW_ROWS)
            gate[r0:r0 + 3] = 1 if (r0 // 3) % 2 == 0 else 0
            base = (start - r0 // 3) % N_CH
            for c in (base, (base + 1) % N_CH, (base + 2) % N_CH):
                out.append(EmitterSpec("noise", rx_dbm - 10 * np.log10(3), channel_offset_hz(c), 2.0e6, gate=gate))
        return out


class Smart(Jammer):
    """Learns which attack works against whatever defence it meets (multi-armed bandit, UCB1).

    It hears our transmissions with the same ~25 ms delay as the follower and never sees anything
    else: every tactic aims at channels it has heard us use.
      follow   jam the channel it last heard us on
      predict  jam the channel its transition counts say we will move to next
      wide     split its power over the 3 channels it has heard us use most
      pulse    short full-power bursts (30 % duty, 2x power) on the last heard channel
      spoof    look-alike frames with forged headers on the last heard channel
    Reward per 1 s epoch = share of slots in which its energy landed on our channel, weighted by
    how much of its power was there (NARROW_FRAC = 1).
    """
    TACTICS = ("follow", "predict", "wide", "pulse", "spoof")
    reaction_slots = 3
    epoch_slots = 100            # re-decide every 1 s
    ucb_c = 0.35                 # exploration weight (rewards are in 0..1)

    def start(self, ctx):
        self.pending: deque[int] = deque([ctx.our_channel] * self.reaction_slots, maxlen=self.reaction_slots)
        self.heard = np.zeros(N_CH)                     # how often each channel was heard
        self.trans = np.ones((N_CH, N_CH)) * 0.05       # slot-to-slot transition counts heard[t-1] -> heard[t]
        self.last = ctx.our_channel
        self.n = np.zeros(len(self.TACTICS))
        self.value = np.zeros(len(self.TACTICS))
        self.total = 0
        self.tactic = 0
        self.epoch_start = ctx.slot
        self.epoch_reward = 0.0
        self.epoch_n = 0
        self.history: list[tuple[float, str, float]] = []   # (t, tactic, reward) for the UI / tests
        self.targets: list[int] = []
        self.forging = False

    @property
    def tactic_name(self) -> str:
        return self.TACTICS[self.tactic]

    def _choose(self) -> int:
        untried = np.flatnonzero(self.n == 0)
        if len(untried):
            return int(untried[0])
        ucb = self.value + self.ucb_c * np.sqrt(2 * np.log(max(self.total, 1)) / self.n)
        return int(np.argmax(ucb))

    def _close_epoch(self, t: float) -> None:
        r = self.epoch_reward / max(self.epoch_n, 1)
        k = self.tactic
        self.n[k] += 1
        self.total += 1
        self.value[k] += (r - self.value[k]) / self.n[k]
        self.history.append((round(t, 2), self.TACTICS[k], round(float(r), 3)))
        self.history = self.history[-60:]
        self.tactic = self._choose()
        self.epoch_reward, self.epoch_n = 0.0, 0

    def update(self, ctx):
        # sense: what it hears now is only known after the reaction delay
        heard = self.pending[0]
        self.pending.append(ctx.our_channel)
        self.trans[self.last, heard] += 1            # slot-to-slot transitions (staying counts too)
        self.heard *= 0.995
        self.heard[heard] += 1
        self.last = heard
        if ctx.slot - self.epoch_start >= self.epoch_slots:
            self._close_epoch(ctx.t)
            self.epoch_start = ctx.slot

        name = self.TACTICS[self.tactic]
        self.frac = np.zeros(N_CH)
        self.forging = False
        if name == "follow":
            self.targets = [heard]
            self.frac[heard] = NARROW_FRAC
        elif name == "predict":
            # it hears us R slots late, so it must look R hops ahead: chain its transition estimate R times
            P = self.trans / self.trans.sum(axis=1, keepdims=True)
            v = np.zeros(N_CH); v[heard] = 1.0
            for _ in range(self.reaction_slots):
                v = v @ P
            nxt = int(np.argmax(v))
            self.targets = [nxt]
            self.frac[nxt] = NARROW_FRAC
        elif name == "wide":
            self.targets = [int(c) for c in np.argsort(-self.heard)[:3]]
            self.frac[self.targets] = NARROW_FRAC / 3
        elif name == "pulse":
            on = (ctx.slot % 10) < 3
            self.targets = [heard] if on else []
            if on:
                self.frac[heard] = min(1.0, NARROW_FRAC * 2.0)
        else:                                   # spoof
            self.forging = bool(ctx.rng.random() < 0.6)
            self.targets = [heard] if self.forging else []
            if self.forging:
                self.frac[heard] = 1.0
        self.channels = list(self.targets)
        # score: did the energy land where we actually were?
        self.epoch_reward += min(float(self.frac[ctx.our_channel]), NARROW_FRAC) / NARROW_FRAC
        self.epoch_n += 1

    def emitters(self, rx_dbm, t, rng):
        name = self.TACTICS[self.tactic]
        if not self.targets:
            return []
        if name == "spoof":
            gate = np.roll(np.array([1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1], dtype=float), int(rng.integers(0, 5)))
            off = float(rng.choice([-1.0, 1.0])) * float(rng.uniform(0.8, 1.3)) * 1e6
            return [EmitterSpec("qpsk", rx_dbm, channel_offset_hz(self.targets[0]) + off, gate=gate)]
        if name == "wide":
            return [_narrow(c, rx_dbm - 10 * np.log10(3)) for c in self.targets]
        if name == "pulse":
            gate = np.zeros(WINDOW_ROWS)
            gate[: WINDOW_ROWS // 3] = 1
            return [_narrow(self.targets[0], rx_dbm + 3, gate)]
        return [_narrow(self.targets[0], rx_dbm)]

    def to_msg(self) -> dict:
        m = super().to_msg()
        m["tactic"] = self.tactic_name
        m["tactic_values"] = {k: round(float(v), 3) for k, v in zip(self.TACTICS, self.value)}
        return m


JAMMER_CLASSES = {"barrage": Barrage, "random": RandomJ, "sweep": Sweep, "reactive": Reactive,
                  "deceptive": Deceptive, "accidental": Accidental, "follower": Follower,
                  "smart": Smart, "novel": Novel, "novel_staircase": NovelStaircase}


def make_jammer(jid: str, jtype: str, pos, power_dbm: Optional[float], owner: Optional[str]) -> Jammer:
    if jtype not in JAMMER_CLASSES:
        raise ValueError(f"jammer type '{jtype}' is not available yet")
    cls = JAMMER_CLASSES[jtype]
    z = 2.0 if len(pos) < 3 else pos[2]
    return cls(id=jid, type=jtype, pos=[float(pos[0]), float(pos[1]), float(z)],
               power_dbm=DEFAULT_POWER_DBM[jtype] if power_dbm is None else float(power_dbm), owner=owner)
