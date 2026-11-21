"""Draws docs/benchmark_chart.png from a benchmark JSON (default: docs/benchmark_results.json).

    python scripts/plot_benchmark.py [results/benchmark_xxx.json]
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "benchmark_results.json"
d = json.loads(src.read_text())
DEFS = [x for x in ["none", "fixed_hopping", "energy", "rl", "aegis", "hybrid"] if any(r["defender"] == x for r in d["rows"])]
LABEL = {"none": "No defence", "fixed_hopping": "Fixed hopping", "energy": "Energy detector", "rl": "RL agent", "aegis": "AEGIS (CNN)", "hybrid": "Hybrid (CNN+RL)"}
# validated categorical order (CVD + normal-vision checks pass on light)
COL = {"none": "#2a78d6", "fixed_hopping": "#eb6834", "energy": "#1baf7a", "rl": "#eda100", "aegis": "#e87ba4", "hybrid": "#6250d6"}
INK, MUTED, GRID = "#1f1f1d", "#6b6a63", "#e6e5e0"
jams = list(dict.fromkeys(r["jammer"] for r in d["rows"]))
val = {(r["jammer"], r["defender"]): r["delivery_pct"] for r in d["rows"]}
mean = {o["defender"]: o["delivery_pct"] for o in d["overall"]}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "text.color": INK,
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED})
fig = plt.figure(figsize=(14, 5.6), facecolor="#fcfcfb")
a1 = fig.add_axes([0.06, 0.2, 0.6, 0.66]); a2 = fig.add_axes([0.81, 0.2, 0.16, 0.66])
n, w = len(DEFS), 0.8 / len(DEFS)
for k, dn in enumerate(DEFS):
    xs = [i - 0.4 + w * (k + 0.5) for i in range(len(jams))]
    a1.bar(xs, [val.get((j, dn), 0) for j in jams], width=w - 0.02, color=COL[dn], label=LABEL[dn], edgecolor="#fcfcfb", linewidth=1)
a1.set_xticks(range(len(jams)), jams, fontsize=9.5); a1.set_xlim(-0.5, len(jams) - 0.5)
a1.set_ylim(0, 100); a1.set_ylabel("packets delivered under attack (%)")
a1.axhline(80, color=MUTED, lw=1, ls=(0, (4, 3))); a1.text(len(jams) - 0.42, 80, "target\n80 %", ha="left", va="center", color=MUTED, fontsize=9)
a1.set_title("Each jammer type", loc="left", fontsize=12, color=INK)
a1.legend(ncol=6, frameon=False, loc="upper left", bbox_to_anchor=(0, -0.08), fontsize=9.5)
ys = list(range(len(DEFS)))[::-1]
a2.barh(ys, [mean[x] for x in DEFS], color=[COL[x] for x in DEFS], height=0.62, edgecolor="#fcfcfb", linewidth=1)
for y, x in zip(ys, DEFS):
    a2.text(mean[x] + 1.5, y, f"{mean[x]:.1f} %", va="center", fontsize=10, color=INK, fontweight="bold" if x in ("aegis", "hybrid") else "normal")
a2.set_yticks(ys, [LABEL[x] for x in DEFS]); a2.set_xlim(0, 115); a2.set_xticks([0, 50, 100])
a2.set_title(f"Average over all {len(jams)}", loc="left", fontsize=12, color=INK)
for a in (a1, a2):
    a.set_facecolor("#fcfcfb"); a.grid(axis="y" if a is a1 else "x", color=GRID, lw=0.8); a.set_axisbelow(True)
    for s in ("top", "right"): a.spines[s].set_visible(False)
fig.suptitle(f"AEGIS-LINK benchmark · {d['seeds']} seeds × {d['duration_s']:.0f} s per run, identical seeded attacks for every defence",
             x=0.01, y=0.97, ha="left", fontsize=11, color=MUTED)
out = ROOT / "docs" / "benchmark_chart.png"
fig.savefig(out, dpi=140)
print(out)
