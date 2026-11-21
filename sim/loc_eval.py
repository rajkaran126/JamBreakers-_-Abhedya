"""How accurate is jammer localisation? Error between the AI's estimate and the jammer's true position.

For each case: launch one jammer, let the AEGIS defender localise it for a few seconds (an estimate every
0.5 s, published only when its 95 % radius is under 300 m), and record for every published estimate:
the distance to the true position, and whether the true position lies inside the published radius
(an honest radius should contain it about 95 % of the time). Coverage = share of checks with an estimate.

Known limits, visible in the per-position table: a jammer far outside the drones' formation is pulled towards
them (signal strength alone cannot pin it down from one side); one beside a hill gets a large honest radius
and is often not published. Remedies: move a drone towards it, or add bearing (direction) measurements.

    python -m sim.loc_eval            -> docs/localisation_results.json and a printed table
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .jammers import make_jammer
from .phy import NumpyPhy
from .world import SimWorld
from . import scenarios as scn

ROOT = Path(__file__).resolve().parents[1]
JAMMERS = ("barrage", "random", "sweep", "reactive", "follower", "smart")
ARENA_POSITIONS = [(220, 140), (600, 450), (900, 200), (350, -150), (100, 650), (800, 700)]
SCENARIOS = ("urban_patrol", "forest_ambush", "border_convoy")      # buildings, trees, ridges


def run_case(jammer: str, pos, seed: int, scenario=None, seconds: float = 8.0) -> dict:
    w = SimWorld("main", seed, "aegis", NumpyPhy(), scenario=scn.get(scenario) if scenario else None)
    if scenario:
        w.schedule = []                                          # only our test jammer
    w.run_slots(100)
    w.launch(make_jammer("J1", jammer, pos, None, None))
    errs, inside, checks = [], [], 0
    for _ in range(int(seconds / 0.5)):
        w.run_slots(50)
        if w.t < 4.0:
            continue                                             # let the first readings come in
        checks += 1
        est = w.defender.estimates
        if not est:
            continue
        e = est[0]
        tx, ty = w.jammers[0].pos[0], w.jammers[0].pos[1]
        d = float(np.hypot(e["pos"][0] - tx, e["pos"][1] - ty))
        errs.append(d)
        inside.append(d <= e["radius_m"])
    return {"errors": errs, "inside": inside, "checks": checks}


def summarise(rows: list[dict]) -> dict:
    errs = np.array([e for r in rows for e in r["errors"]])
    ins = [i for r in rows for i in r["inside"]]
    checks = sum(r["checks"] for r in rows)
    if errs.size == 0:
        return {"estimates": 0, "coverage_pct": 0.0}
    return {"estimates": int(errs.size), "coverage_pct": round(100 * errs.size / max(checks, 1), 1),
            "mean_m": round(float(errs.mean()), 1), "median_m": round(float(np.median(errs)), 1),
            "p95_m": round(float(np.percentile(errs, 95)), 1), "worst_m": round(float(errs.max()), 1),
            "inside_radius_pct": round(100 * float(np.mean(ins)), 1)}


def main(seeds=(1, 2, 3)) -> dict:
    out = {"by_jammer": {}, "by_position": {}, "by_terrain": {}, "positions": ARENA_POSITIONS}
    all_rows, per_pos = [], {p: [] for p in ARENA_POSITIONS}
    for j in JAMMERS:
        rows = []
        for p in ARENA_POSITIONS:
            r = [run_case(j, p, s) for s in seeds]
            per_pos[p] += r
            rows += r
        out["by_jammer"][j] = summarise(rows)
        all_rows += rows
    for p, rows in per_pos.items():
        out["by_position"][f"({p[0]}, {p[1]})"] = summarise(rows)
    out["by_terrain"]["open field (arena)"] = summarise(all_rows)
    for sc in SCENARIOS:
        rows = [run_case(j, p, s, scenario=sc) for j in ("barrage", "random", "follower") for p in ARENA_POSITIONS[:4] for s in seeds[:2]]
        out["by_terrain"][sc] = summarise(rows)
    out["overall"] = summarise(all_rows)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "localisation_results.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = main()
    print(f"{'case':28} {'cover':>6} {'mean':>7} {'median':>7} {'p95':>7} {'worst':>7} {'in radius':>9}")
    for group in ("by_jammer", "by_position", "by_terrain"):
        for k, v in r[group].items():
            if v.get("estimates"):
                print(f"{k:28} {v['coverage_pct']:5.0f}% {v['mean_m']:6.0f}m {v['median_m']:6.0f}m {v['p95_m']:6.0f}m {v['worst_m']:6.0f}m {v['inside_radius_pct']:8.0f}%")
            else:
                print(f"{k:28} no estimate published")
