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
                     "accidental": 20.0, "follower": 34.0, "smart": 36.0}


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
             "channels": sorted(self.channels), "active": bool(self.channels)}
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


JAMMER_CLASSES = {"barrage": Barrage, "random": RandomJ, "sweep": Sweep, "reactive": Reactive,
                  "deceptive": Deceptive, "accidental": Accidental, "follower": Follower}


def make_jammer(jid: str, jtype: str, pos, power_dbm: Optional[float], owner: Optional[str]) -> Jammer:
    if jtype not in JAMMER_CLASSES:
        raise ValueError(f"jammer type '{jtype}' is not available yet")
    cls = JAMMER_CLASSES[jtype]
    z = 2.0 if len(pos) < 3 else pos[2]
    return cls(id=jid, type=jtype, pos=[float(pos[0]), float(pos[1]), float(z)],
               power_dbm=DEFAULT_POWER_DBM[jtype] if power_dbm is None else float(power_dbm), owner=owner)
