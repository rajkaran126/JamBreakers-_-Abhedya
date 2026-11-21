"""Drone batteries: what happens when a drone runs low, and why the AI is careful with transmit power.

Model (small quadcopter, realistic orders of magnitude):
  battery 100 Wh; hover ~240 W  ->  ~25 min of flight
  radio: 4 W for the radio electronics (receiver, processor, synthesiser: a typical range for drone datalink
         modules is 2-8 W) plus the amplifier: 27 dBm (0.5 W RF) at 25 % efficiency = 2 W; the AI's +9 dB step
         means 4 W RF = 16 W from the battery (~7 % of the drain)
  return home: not a fixed percentage. A drone turns back when what is left only just covers the flight home
         (distance / speed x hover power) plus a 10 % reserve, so a drone far from base turns back earlier.
  These are modelled values, not measurements: real figures depend on airframe, payload, wind and the radio.
For the demo, batteries drain DEMO_TIME_SCALE x faster than real so judges see it in minutes.

Lifecycle of a drone:  flying --(battery < RTB_AT)--> returning to the command post --> charging (battery
swap, SWAP_S) --> relaunching to its route at 100 % --> flying. While it is away the mesh routes around it
(widest path), and its packets are not counted as lost: it is not trying to send.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

CAPACITY_WH = 100.0
HOVER_W = 240.0
PA_EFFICIENCY = 0.25
DEMO_TIME_SCALE = 5.0
RTB_AT = 25.0                 # % : floor for returning to base (the distance rule usually triggers first far out)
RESERVE_PCT = 10.0            # % kept for landing / wind on top of the energy to fly home
RADIO_BASE_W = 4.0            # radio electronics, independent of transmit power
LOW_AT = 35.0                 # % : the AI starts saving transmit power
SWAP_S = 20.0                 # battery swap at the command post (real seconds)
FLY_SPEED = 25.0              # m/s on the way home / back out
ARENA_START = {"D1": 92.0, "D2": 80.0, "D3": 71.0, "D4": 58.0}


def drain_pct_per_s(tx_dbm: float) -> float:
    radio_w = RADIO_BASE_W + 10 ** (tx_dbm / 10) / 1000 / PA_EFFICIENCY
    return (HOVER_W + radio_w) / (CAPACITY_WH * 3600) * 100 * DEMO_TIME_SCALE


def _line(p0, p1, t0: float, speed: float):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    dist = float(np.linalg.norm(p1[:2] - p0[:2]))
    dur = max(dist / speed, 1.0)
    heading = float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))

    def path(t: float):
        a = min(max((t - t0) / dur, 0.0), 1.0)
        return tuple(p0 + (p1 - p0) * a), heading
    return path, t0 + dur


def init(nodes, arena: bool) -> None:
    for n in nodes:
        n.battery = (ARENA_START.get(n.id, 95.0) if arena else 100.0) if n.kind in ("drone", "relay") else None
        n.phase = "flying"
        n.route_path = n.path
        n.phase_until = None


def update(w, dt: float) -> None:
    """Called once per tick (50 ms of simulated time)."""
    from .radio import TX_POWER_DBM
    cp = w.net.nodes[w.net.index["CP"]].pos
    tx = TX_POWER_DBM + w.net.tx_boost_db
    for n in w.net.nodes:
        if getattr(n, "battery", None) is None:
            continue
        if n.phase in ("flying", "returning", "relaunching"):
            n.battery = max(0.0, n.battery - drain_pct_per_s(tx if n.phase != "returning" else TX_POWER_DBM) * dt)
        if n.phase == "flying" and n.kind == "drone" and n.battery < return_threshold(n, cp):
            n.phase = "returning"
            home = (cp[0] + 25, cp[1] + 15, 2.0)
            n.path, n.phase_until = _line(n.pos, home, w.t, FLY_SPEED)
            w.event("warn", f"{n.id} battery {n.battery:.0f} %: returning to the command post for a battery swap. "
                            f"The mesh reroutes around it.")
        elif n.phase == "returning" and w.t >= n.phase_until:
            n.phase, n.phase_until = "charging", w.t + SWAP_S
            w.event("info", f"{n.id} landed: battery swap ({SWAP_S:.0f} s).")
        elif n.phase == "charging" and w.t >= n.phase_until:
            n.battery = 100.0
            target, _ = n.route_path(w.t + 15.0)
            n.path, n.phase_until = _line(n.pos, target, w.t, FLY_SPEED)
            n.phase = "relaunching"
            w.event("good", f"{n.id} relaunched at 100 %, flying back to its route.")
        elif n.phase == "relaunching" and w.t >= n.phase_until:
            n.phase, n.path, n.phase_until = "flying", n.route_path, None


def return_threshold(n, cp) -> float:
    """Battery % at which this drone must turn back: energy to fly home from here + reserve, never below RTB_AT."""
    from .radio import TX_POWER_DBM
    dist = float(np.hypot(n.pos[0] - cp[0], n.pos[1] - cp[1]))
    need = drain_pct_per_s(TX_POWER_DBM) * dist / FLY_SPEED
    return max(RTB_AT, need + RESERVE_PCT)


def relay_penalty_db(n) -> float:
    """How much worse a route through this drone is made to look: 0 above 50 %, rising to 12 dB at 25 %,
    unusable while it is flying home or swapping batteries. Keeps the mesh from leaning on a dying relay."""
    b = getattr(n, "battery", None)
    if getattr(n, "phase", "flying") in ("returning", "charging"):
        return float("inf")
    if b is None or b >= 50.0:
        return 0.0
    return float(min(12.0, (50.0 - b) / 25.0 * 12.0))


def away(n) -> bool:
    """Landed for a battery swap: not part of the network, not sending."""
    return getattr(n, "phase", "flying") == "charging"


def lowest(w) -> Optional[float]:
    b = [n.battery for n in w.net.nodes if getattr(n, "battery", None) is not None and n.phase != "charging"]
    return min(b) if b else None
