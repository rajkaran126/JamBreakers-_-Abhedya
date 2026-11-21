"""Guided scenarios (shared/scenarios.json): one per jammer type, each with its own map, units,
routes, jammer schedule and narration. The simulation treats them exactly like the arena; only the
geometry, the routes and the timeline differ."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .trips import Trip

from .network import Node
from .radio import BUILDING_LOSS_DB, HILL_LOSS_DB

PATH = Path(__file__).resolve().parent.parent / "shared" / "scenarios.json"


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def get(scenario_id: str) -> dict:
    for s in catalog()["scenarios"]:
        if s["id"] == scenario_id:
            return s
    raise KeyError(scenario_id)


def ids() -> list[str]:
    return [s["id"] for s in sorted(catalog()["scenarios"], key=lambda s: s["order"])]


def route_path(route, mode: str = "static", speed: float = 10.0, alt: float = 0.0, offset_m: float = 0.0,
               bob: bool = False) -> Callable[[float], tuple]:
    """Position along a polyline at constant speed. Returns f(t) -> ((x, y, z), heading_deg)."""
    pts = np.array(route, dtype=float)
    if mode == "loop" and len(pts) > 1 and not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[:1]])
    if len(pts) == 1 or mode == "static":
        p = pts[0]
        return lambda t: ((float(p[0]), float(p[1]), alt + (4 * math.sin(t * 0.8) if bob else 0.0)), 0.0)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])

    def at(s: float):
        s = min(max(s, 0.0), total)
        i = int(np.searchsorted(cum, s, side="right") - 1)
        i = min(i, len(seg) - 1)
        f = (s - cum[i]) / seg[i] if seg[i] > 0 else 0.0
        return pts[i] + f * (pts[i + 1] - pts[i]), pts[i + 1] - pts[i]

    def fn(t: float):
        s = t * speed + offset_m
        if mode == "loop":
            s %= total
            sign = 1.0
        else:                                    # pingpong
            s %= 2 * total
            sign = 1.0
            if s > total:
                s, sign = 2 * total - s, -1.0
        p, d = at(s)
        d = d * sign
        heading = (90 - math.degrees(math.atan2(d[1], d[0]))) % 360
        z = alt + (6 * math.sin(t * 0.7 + offset_m * 0.01) if bob else 0.0)
        return (float(p[0]), float(p[1]), z), heading
    return fn


def build_nodes(spec: dict) -> list[Node]:
    nodes = []
    for n in spec["nodes"]:
        kind = n["kind"]
        alt = n.get("alt", 6.0 if kind == "command_post" else 1.5 if kind == "vehicle" else 100.0)
        if n.get("mode") == "trip":
            # leaves the start at t = delay_s (a convoy's second truck waits a few seconds) and arrives
            # leg_s later, so the whole scenario plays out while the truck drives the road
            path = Trip(n["route"], n["from"], n["to"], n.get("speed", 9.0), alt, offset_s=-n.get("delay_s", 0.0),
                        leg_s=n.get("leg_s"))
        else:
            path = route_path(n["route"], n.get("mode", "static"), n.get("speed", 10.0), alt, n.get("offset_m", 0.0),
                              bob=kind in ("drone", "relay"))
        node = Node(n["id"], kind, path)
        node.move(0.0)
        nodes.append(node)
    order = {"CP": 0}
    nodes.sort(key=lambda nd: order.get(nd.id, 1))       # command post first
    return nodes


def build_obstacles(spec: dict) -> list[dict]:
    out = []
    for o in spec.get("obstacles", []):
        out.append({"id": o["id"], "kind": o["kind"], "pos": [float(v) for v in o["pos"]], "size": [float(v) for v in o["size"]],
                    "loss_db": BUILDING_LOSS_DB if o["kind"] == "building" else HILL_LOSS_DB})
    return out


def jammer_route(j: dict) -> Optional[Callable[[float], tuple]]:
    if "route" not in j:
        return None
    return route_path(j["route"], j.get("mode", "pingpong"), j.get("speed", 10.0), j.get("alt", 2.0), j.get("offset_m", 0.0),
                      bob=j.get("alt", 2.0) > 20)
