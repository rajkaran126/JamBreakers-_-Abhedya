"""Defenders: what the network does about interference.

A defender sees only what a real radio could measure (packet loss, wideband energy per channel, a
spectrogram on request) and never the ground-truth jammer list. Each slot it may return actions;
the world sends them as a control frame and they take effect only once that frame is delivered.

  none            stays on channel 0 forever
  fixed_hopping   conventional FHSS: a public repeating pattern, one channel per slot (the AI OFF side)
  energy          hops to the quietest channel when loss passes 10 % (no classification)
  aegis           the CNN defender (ai/defender.py, Phase 2)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .radio import N_CH, SLOT_S

LOSS_TRIGGER = 0.10


@dataclass
class Action:
    kind: str                     # 'hop' | 'mode' | 'power' | 'rate' | 'relay' | 'blacklist'
    channel: Optional[int] = None
    mode: Optional[str] = None    # 'dwell' | 'keyed' | 'fixed'
    delta_db: float = 0.0
    modulation: Optional[str] = None
    channels: tuple[int, ...] = ()
    ttl_s: float = 0.0
    between: tuple[str, str] = ("", "")
    anti_follow: bool = False     # keyed mode: also never reuse the last 3 channels (only needed against a follower)


@dataclass
class Decision:
    cls: str                      # CNN class or 'unknown'
    confidence: float
    action: str                   # schema action_taken
    reason: str
    actions: list[Action] = field(default_factory=list)
    from_channel: Optional[int] = None
    to_channel: Optional[int] = None
    decision_time_ms: Optional[float] = None


@dataclass
class SlotObs:
    slot: int
    t: float
    channel: int
    hop_mode: str
    sent: int
    delivered: int
    loss_recent: float                       # over the last 5 slots
    energy_dbm: np.ndarray                   # in-band energy per channel at the command post
    tx_boost_db: float
    modulation: str
    control_pending: bool
    blacklist: frozenset
    sense: Callable[[str], np.ndarray]      # spectrogram window (12 x 128 dBm) at a node, on request
    world: object = None                     # for observation helpers only (positions, link SINR)


class HopGuard:
    """At most `max_hops` hops in `window_s`, then hold for `hold_s` (stops thrashing)."""

    def __init__(self, max_hops: int = 3, window_s: float = 5.0, hold_s: float = 5.0):
        self.max_hops, self.window_s, self.hold_s = max_hops, window_s, hold_s
        self.times: deque[float] = deque()
        self.hold_until = -1.0

    def allowed(self, t: float) -> bool:
        while self.times and t - self.times[0] > self.window_s:
            self.times.popleft()
        return t >= self.hold_until

    def record(self, t: float) -> None:
        self.times.append(t)
        if len(self.times) >= self.max_hops:
            self.hold_until = t + self.hold_s
            self.times.clear()


class Defender:
    name = "base"
    initial_mode = "dwell"

    def __init__(self, rng: Optional[np.random.Generator] = None):
        self.rng = rng or np.random.default_rng(0)

    def on_slot(self, obs: SlotObs) -> Optional[Decision]:
        return None


class NoDefense(Defender):
    name = "none"


class FixedHopping(Defender):
    name = "fixed_hopping"
    initial_mode = "fixed"


class EnergyDetector(Defender):
    """Classic adaptive radio: when loss passes 10 %, hop to the channel with the least energy."""
    name = "energy"

    def __init__(self, rng=None):
        super().__init__(rng)
        self.guard = HopGuard()

    def on_slot(self, obs: SlotObs) -> Optional[Decision]:
        if obs.control_pending or obs.loss_recent <= LOSS_TRIGGER or not self.guard.allowed(obs.t):
            return None
        e = obs.energy_dbm.copy()
        e[obs.channel] = np.inf
        to = int(np.argmin(e))
        self.guard.record(obs.t)
        return Decision("unknown", 0.0, "hop",
                        f"Loss {obs.loss_recent:.0%} on channel {obs.channel}; hopping to the quietest channel {to}.",
                        [Action("hop", channel=to)], obs.channel, to)


DEFENDERS: dict[str, type[Defender]] = {"none": NoDefense, "fixed_hopping": FixedHopping, "energy": EnergyDetector}


def make_defender(name: str, rng: np.random.Generator) -> Defender:
    if name == "aegis":
        try:
            from ai.defender import AegisDefender  # Phase 2
            return AegisDefender(rng)
        except ImportError:
            name = "energy"
    return DEFENDERS[name](rng)
