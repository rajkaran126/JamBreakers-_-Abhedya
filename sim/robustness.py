"""Robustness benchmark: does the result hold when the conditions change?

AI OFF (fixed hopping) vs AI ON (hybrid), identical seeded runs, one condition changed at a time:

  power        jammer at 30 / default / 46 dBm
  distance     jammer close to the formation / default / far out (800, 650)
  speed        drones at 0.5x / 1x / 2x their patrol speed
  size         4 drones (default) / 8 drones
  background   none / two low-power Wi-Fi-like interferers switching on and off at random places
  stacked      several jammers at once (4 combinations)
  unseen       two patterns the CNN was never trained on (comb, staircase)

For every cell: mean, standard deviation, 95 % confidence interval of the mean (t distribution over seeds),
worst run. Across all AI ON runs: decision-to-network-switch latency p50 / p95 / p99.

    python -m sim.robustness [--seeds 8] [--duration 12]   -> docs/robustness_results.json + docs/ROBUSTNESS.md
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
JAMMERS = ("barrage", "random", "sweep", "follower", "smart")
DEFENDERS = ("fixed_hopping", "hybrid")
T95 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26, 12: 2.20, 16: 2.13, 20: 2.09}
STACKS = {"sweep + follower": [("sweep", (500, 300)), ("follower", (200, 100))],
          "sweep + follower + smart": [("sweep", (500, 300)), ("follower", (200, 100)), ("smart", (350, 250))],
          "random + follower": [("random", (160, 90)), ("follower", (200, 100))],
          "barrage + follower": [("barrage", (600, 400)), ("follower", (200, 100))]}
EXTRA_DRONES = [(250, 450, 200, 150, 0.04, 0.5, 105), (700, -50, 250, 120, -0.045, 2.0, 90),
                (950, 350, 180, 220, 0.05, 3.3, 100), (100, 250, 160, 200, -0.04, 5.0, 95)]


def _world(seed, defender, speed=1.0, size=4):
    import sim.world as W
    from .network import Node, arena_nodes, drone_path
    if size > 4:
        base = arena_nodes()
        for k, (cx, cy, rx, ry, w, ph, alt) in enumerate(EXTRA_DRONES[: size - 4]):
            n = Node(f"D{5 + k}", "drone", drone_path(cx, cy, rx, ry, w, ph, alt))
            n.move(0.0)
            base.append(n)
            W.NODE_ADDR.setdefault(n.id, 10 + k)
        orig = W.arena_nodes
        W.arena_nodes = lambda: base
        try:
            w = W.SimWorld("main", seed, defender, W_phy())
        finally:
            W.arena_nodes = orig
    else:
        w = W.SimWorld("main", seed, defender, W_phy())
    if speed != 1.0:
        for n in w.net.nodes:
            if n.kind == "drone" and n.path is not None:
                p0 = n.path
                n.path = (lambda f: (lambda t: f(t * speed)))(p0)
                n.route_path = n.path
    return w


def W_phy():
    from .phy import NumpyPhy
    return NumpyPhy()


def run(case: dict) -> dict:
    from ai.defender import SIGNATURES
    from .jammers import make_jammer
    from .experiment import DEFAULT_JAMMER_POS
    SIGNATURES.clear()
    w = _world(case["seed"], case["defender"], case.get("speed", 1.0), case.get("size", 4))
    rng = np.random.default_rng(case["seed"] + 77)
    w.run_slots(200)
    s0, d0 = w.total_sent, w.total_delivered
    for i, (j, pos, pw) in enumerate(case["jammers"]):
        w.launch(make_jammer(f"J{i}", j, pos or DEFAULT_JAMMER_POS[j], pw, None))
    if case.get("background"):
        for k in range(2):
            w.launch(make_jammer(f"B{k}", "accidental", (float(rng.uniform(-100, 1000)), float(rng.uniform(-200, 700))), 24.0, None))
    w.run_slots(int(case["duration"] * 100))
    sent = w.total_sent - s0
    return {**{k: v for k, v in case.items() if k != "jammers"}, "jammers": [j for j, _, _ in case["jammers"]],
            "delivery": 100 * (w.total_delivered - d0) / max(sent, 1), "latencies": list(w.latencies),
            "response": list(w.response_latencies)}


def cases(seeds, duration):
    out = []
    def add(group, cond, jams, **kw):
        for d in DEFENDERS:
            for s in seeds:
                out.append({"group": group, "condition": cond, "defender": d, "seed": s, "duration": duration, "jammers": jams, **kw})
    for j in JAMMERS:
        for label, pw in (("30 dBm", 30.0), ("default", None), ("46 dBm", 46.0)):
            add("jammer power", f"{j}, {label}", [(j, None, pw)])
        for label, pos in (("close", (120, 60)), ("default", None), ("far (800, 650)", (800, 650))):
            add("jammer distance", f"{j}, {label}", [(j, pos, None)])
        for sp in (0.5, 1.0, 2.0):
            add("drone speed", f"{j}, {sp:g}x", [(j, None, None)], speed=sp)
        for size in (4, 8):
            add("network size", f"{j}, {size} drones", [(j, None, None)], size=size)
        for bg in (False, True):
            add("background interference", f"{j}, {'with' if bg else 'no'} background", [(j, None, None)], background=bg)
    for name, jams in STACKS.items():
        add("stacked", name, [(j, p, None) for j, p in jams])
    for j in ("novel", "novel_staircase"):
        add("unseen", j, [(j, None, None)])
    return out


def stats(v) -> dict:
    v = np.asarray(v, float)
    n = len(v)
    sd = float(v.std(ddof=1)) if n > 1 else 0.0
    t = T95.get(n - 1, 2.0)
    half = t * sd / np.sqrt(n) if n > 1 else 0.0
    return {"n": n, "mean": round(float(v.mean()), 1), "sd": round(sd, 1), "ci95": [round(float(v.mean() - half), 1),
            round(float(min(100.0, v.mean() + half)), 1)], "worst": round(float(v.min()), 1)}


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--duration", type=float, default=12.0)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    seeds = list(range(101, 101 + a.seeds))
    todo = cases(seeds, a.duration)
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        rows = list(ex.map(run, todo, chunksize=4))
    cells: dict = {}
    for r in rows:
        cells.setdefault((r["group"], r["condition"]), {}).setdefault(r["defender"], []).append(r["delivery"])
    table = [{"group": g, "condition": c, **{d: stats(v) for d, v in per.items()}} for (g, c), per in cells.items()]
    lat = np.array([x for r in rows if r["defender"] == "hybrid" for x in r["latencies"]])
    on = [r["delivery"] for r in rows if r["defender"] == "hybrid"]
    off = [r["delivery"] for r in rows if r["defender"] == "fixed_hopping"]
    out = {"created": time.strftime("%Y-%m-%d %H:%M"), "seeds": seeds, "duration_s": a.duration, "runs": len(rows),
           "wall_s": round(time.time() - t0), "table": table,
           "overall": {"ai_on": stats(on), "ai_off": stats(off)},
           "latency_ms": {"n": int(lat.size), "p50": round(float(np.percentile(lat, 50)), 1),
                          "p95": round(float(np.percentile(lat, 95)), 1), "p99": round(float(np.percentile(lat, 99)), 1),
                          "max": round(float(lat.max()), 1)} if lat.size else None,
           "latency_by_group": {}}
    for g in sorted({r["group"] for r in rows}):
        lg = np.array([x for r in rows if r["defender"] == "hybrid" and r["group"] == g for x in r["latencies"]])
        if lg.size:
            out["latency_by_group"][g] = {"n": int(lg.size), "p50": round(float(np.percentile(lg, 50)), 1),
                                          "p95": round(float(np.percentile(lg, 95)), 1), "p99": round(float(np.percentile(lg, 99)), 1)}
    resp = np.array([x for r in rows if r["defender"] == "hybrid" for x in r["response"]])
    if resp.size:
        out["response_latency_ms"] = {"n": int(resp.size), **{f"p{q}": round(float(np.percentile(resp, q)), 1) for q in (50, 95, 99)}}
    single = np.array([x for r in rows if r["defender"] == "hybrid" and r["group"] not in ("stacked", "unseen")
                       and len(r["jammers"]) == 1 and not r.get("background") for x in r["latencies"]])
    if single.size:
        out["latency_single_jammer"] = {"n": int(single.size), "p50": round(float(np.percentile(single, 50)), 1),
                                        "p95": round(float(np.percentile(single, 95)), 1), "p99": round(float(np.percentile(single, 99)), 1)}
    (ROOT / "docs" / "robustness_results.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    r = main()
    print(json.dumps({k: r[k] for k in ("runs", "wall_s", "overall", "latency_ms")}, indent=1))
    for row in r["table"]:
        on, off = row["hybrid"], row["fixed_hopping"]
        print(f"{row['group']:24} {row['condition']:34} AI ON {on['mean']:5.1f} ±{on['sd']:4.1f} CI {on['ci95']} worst {on['worst']:5.1f} | AI OFF {off['mean']:5.1f} worst {off['worst']:5.1f}")
