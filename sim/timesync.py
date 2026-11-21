"""Network time: every radio has its own imperfect clock; the network keeps them aligned to the time master.

Why: a hop happens at a slot boundary. If drone 2's clock is late by more than the guard time, it is still
on the old channel when the others have moved, and its packets are lost even with no jammer at all.

Model (all times in seconds)
  clock error     each radio's crystal drifts by a fixed rate (+/-20 ppm, a common TCXO-less oscillator spec)
                  plus a slow random wander (temperature). Error is measured against the time master's clock.
  guard time      0.5 ms at the start of each 10 ms slot: a radio whose error exceeds it misses the slot.
  sync beacon     the time master sends a signed beacon with its timestamp once a second (part of the control
                  traffic). A radio that hears it measures its error (+/-2 us timestamp jitter), corrects the
                  offset, and refines its drift estimate from successive corrections (least squares).
  holdover        a radio that misses beacons keeps running on its drift estimate: only the residual drift
                  (well under 1 ppm after a few beacons) accumulates, so it stays inside the guard for minutes.
  master loss     if the command post's beacons stop (destroyed, jammed, clock failure) for 3 s, the healthy
                  radio with the lowest address takes over as time master (pre-agreed order, no negotiation),
                  and everyone re-aligns to it. The network only needs a common time, not the true time.
  reboot          a rebooted radio's clock starts tens of ms off; it is out of sync until it hears a beacon on
                  the rendezvous channel (the existing resync path), which also carries the time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

GUARD_S = 0.5e-3
BEACON_EVERY_S = 1.0
DRIFT_PPM = 20.0
WANDER_PPM_PER_SQRT_S = 0.02
JITTER_S = 2e-6
MASTER_TIMEOUT_S = 3.0
REBOOT_ERROR_S = 0.05


@dataclass
class Clock:
    drift: float                          # true rate error vs the master (s/s)
    err: float = 0.0                      # current error vs the master's clock (s)
    est: float = 0.0                      # estimated drift, used to correct between beacons
    fixes: list = field(default_factory=list)      # (t, measured error before correction) for the drift fit
    last_fix: float = 0.0


class TimeSync:
    def __init__(self, node_ids: list[str], seed: int, master: str = "CP", sync: bool = True):
        self.rng = np.random.default_rng(seed + 424242)
        self.sync = sync
        self.master = master
        self.backup_order = sorted(n for n in node_ids if n != master)
        self.clocks = {n: Clock(drift=0.0 if n == master else float(self.rng.uniform(-DRIFT_PPM, DRIFT_PPM)) * 1e-6)
                       for n in node_ids}
        self.master_alive = True
        self.last_beacon = 0.0
        self.next_beacon = BEACON_EVERY_S
        self.beacons = 0
        self.max_err_hist: list[float] = []
        self.events: list[tuple[str, str]] = []

    # ---------- time passes ----------
    def advance(self, dt: float) -> None:
        for n, c in self.clocks.items():
            if n == self.master:
                continue
            c.drift += float(self.rng.normal(0, WANDER_PPM_PER_SQRT_S * 1e-6 * np.sqrt(dt)))
            c.err += (c.drift - c.est) * dt

    def tick(self, t: float, dt: float, heard: dict[str, bool], usable: set[str]) -> list[str]:
        """Advance clocks by dt; send/receive beacons; handle master loss. Returns radios now outside the guard."""
        self.advance(dt)
        if not self.master_alive and self.master in usable:
            usable = usable - {self.master}
        if self.master_alive or self.master != "CP":
            if t >= self.next_beacon:
                self.next_beacon = t + BEACON_EVERY_S
                self.beacons += 1
                self.last_beacon = t
                if self.sync:
                    for n, ok in heard.items():
                        # a radio already outside the guard listens in the wrong time window and cannot decode the
                        # regular beacon: it needs the rendezvous resync (which waits on wide windows)
                        if ok and n in self.clocks and n != self.master and abs(self.clocks[n].err) <= GUARD_S:
                            self.fix(n, t)
        elif t - self.last_beacon > MASTER_TIMEOUT_S:
            self._elect(t, usable)
        out = [n for n, c in self.clocks.items() if n != self.master and abs(c.err) > GUARD_S]
        self.max_err_hist.append(self.max_error_us())
        if len(self.max_err_hist) > 200:
            self.max_err_hist.pop(0)
        return out

    def fix(self, n: str, t: float) -> None:
        """A beacon heard: measure the error, correct it, refine the drift estimate."""
        c = self.clocks[n]
        measured = c.err + float(self.rng.normal(0, JITTER_S))
        if c.fixes and t > c.fixes[-1][0]:
            # the error found now built up since the last correction: that rate is what the estimate still misses
            c.est += 0.8 * measured / (t - c.fixes[-1][0])
        c.fixes.append((t, measured))
        c.fixes = c.fixes[-8:]
        c.err -= measured
        c.last_fix = t

    def resynced(self, n: str, t: float) -> None:
        """The rendezvous beacon also carries the master's time."""
        if n in self.clocks and n != self.master:
            self.fix(n, t)

    def reboot(self, n: str) -> None:
        c = self.clocks[n]
        c.err = float(self.rng.choice([-1, 1]) * self.rng.uniform(0.5, 1.0) * REBOOT_ERROR_S)
        c.est, c.fixes = 0.0, []

    def lose_master(self, t: float) -> None:
        """The command post's clock / beacons are gone (destroyed, jammed, failed)."""
        self.master_alive = False
        self.last_beacon = min(self.last_beacon, t)
        self.events.append(("warn", f"Time master {self.master} silent: radios run on their drift estimates (holdover)."))

    def _elect(self, t: float, usable: set[str]) -> None:
        cand = next((n for n in self.backup_order if n in usable), None)
        if cand is None:
            return
        ref = self.clocks[cand]
        # everyone's error is now measured against the new master's clock
        for n, c in self.clocks.items():
            if n == cand:
                continue
            c.err -= ref.err
            c.drift -= ref.drift
            c.est -= ref.est
        old = self.master
        self.master = cand
        ref.err = ref.drift = ref.est = 0.0
        self.backup_order = [n for n in self.backup_order if n != cand] + ([old] if old != "CP" else [])
        self.next_beacon = t
        self.last_beacon = t
        self.events.append(("good", f"{cand} took over as time master after {MASTER_TIMEOUT_S:.0f} s without beacons from {old}; "
                                    f"every radio re-aligns to it."))

    def max_error_us(self, among: Optional[set[str]] = None) -> float:
        errs = [abs(c.err) for n, c in self.clocks.items() if n != self.master and (among is None or n in among)]
        return round(1e6 * max(errs), 1) if errs else 0.0
