"""Vehicle trips: drive a named route from a source to a destination and back.

The route is a hand-made polyline that keeps clear of buildings and hills; its corners are rounded
(Chaikin smoothing), so the truck follows curves instead of turning on the spot. Each leg uses a
trapezoid speed profile (accelerate, cruise, brake), then the truck waits at the end (unloading at the
destination, loading at the source) and drives back.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

ACCEL_DIST_M = 80.0          # distance used to speed up from rest, and to brake to a stop (≈ 3–4 m/s², a loaded truck)
DWELL_S = 8.0                # stop at each end
SMOOTH_ITER = 3


def smooth(route, iters: int = SMOOTH_ITER) -> np.ndarray:
    """Chaikin corner cutting; the end points stay where they are. The viewer runs the same algorithm."""
    p = np.asarray(route, dtype=float)
    for _ in range(iters):
        if len(p) < 3:
            break
        q = [p[0]]
        for a, b in zip(p[:-1], p[1:]):
            q.append(0.75 * a + 0.25 * b)
            q.append(0.25 * a + 0.75 * b)
        q.append(p[-1])
        p = np.array(q)
    return p


class Trip:
    """Callable like the other node paths: f(t) -> ((x, y, z), heading_deg). Also reports trip status."""

    def __init__(self, route, src: str, dst: str, speed: float = 9.0, alt: float = 1.5, offset_s: float = 0.0,
                 dwell_s: float = DWELL_S, leg_s: Optional[float] = None):
        self.src, self.dst, self.alt, self.dwell = src, dst, float(alt), float(dwell_s)
        self.pts = smooth(route)
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        self.seg, self.cum = seg, np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])
        d = min(ACCEL_DIST_M, self.length / 2)
        # leg_s: pick the cruising speed so one leg (start to destination) takes exactly that long
        self.speed = (self.length + 2 * d) / float(leg_s) if leg_s else float(speed)
        self.acc = self.speed ** 2 / (2 * d)                       # m/s²
        self.t_acc = self.speed / self.acc
        self.d_acc = d
        self.t_leg = 2 * self.t_acc + (self.length - 2 * d) / self.speed
        self.period = 2 * (self.t_leg + self.dwell)
        self.offset = float(offset_s)
        self._heading = 0.0

    # distance travelled along the leg after tau seconds (trapezoid speed profile)
    def _dist(self, tau: float) -> float:
        if tau <= 0:
            return 0.0
        if tau >= self.t_leg:
            return self.length
        if tau < self.t_acc:
            return 0.5 * self.acc * tau * tau
        if tau > self.t_leg - self.t_acc:
            r = self.t_leg - tau
            return self.length - 0.5 * self.acc * r * r
        return self.d_acc + (tau - self.t_acc) * self.speed

    def _at(self, s: float):
        s = min(max(s, 0.0), self.length)
        i = min(int(np.searchsorted(self.cum, s, side="right") - 1), len(self.seg) - 1)
        f = (s - self.cum[i]) / self.seg[i] if self.seg[i] > 0 else 0.0
        return self.pts[i] + f * (self.pts[i + 1] - self.pts[i]), self.pts[i + 1] - self.pts[i]

    def phase(self, t: float):
        """(state, outbound, distance from the source, seconds left in this state)."""
        u = (t + self.offset) % self.period
        if u < self.t_leg:
            return "driving", True, self._dist(u), self.t_leg - u
        u -= self.t_leg
        if u < self.dwell:
            return "unloading", True, self.length, self.dwell - u
        u -= self.dwell
        if u < self.t_leg:
            return "returning", False, self.length - self._dist(u), self.t_leg - u
        return "loading", False, 0.0, self.dwell - (u - self.t_leg)

    def __call__(self, t: float):
        state, out, s, _ = self.phase(t)
        p, d = self._at(s)
        if state in ("driving", "returning"):
            if not out:
                d = -d
            self._heading = (90 - math.degrees(math.atan2(d[1], d[0]))) % 360
        elif state == "unloading":                                  # parked facing the way it came in
            d = self.pts[-1] - self.pts[-2]
            self._heading = (90 - math.degrees(math.atan2(d[1], d[0]))) % 360
        else:
            d = self.pts[1] - self.pts[0]
            self._heading = (90 - math.degrees(math.atan2(-d[1], -d[0]))) % 360
        return (float(p[0]), float(p[1]), self.alt), self._heading

    def info(self, t: float) -> dict:
        state, out, s, left = self.phase(t)
        frm, to = (self.src, self.dst) if out else (self.dst, self.src)
        done = s / self.length if out else 1 - s / self.length
        if state in ("unloading", "loading"):
            done = 1.0
        return {"from": frm, "to": to, "state": state, "progress": round(done, 3), "eta_s": round(left, 1),
                "src": self.src, "dst": self.dst, "src_pos": [round(float(v), 1) for v in self.pts[0]],
                "dst_pos": [round(float(v), 1) for v in self.pts[-1]]}
