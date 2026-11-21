"""Measured vs predicted: does the simulator's link model match the bench?

Reads a bench CSV (hil/bench_test.py) and, for every link-budget row, compares the measured packet error
rate with the simulator's prediction at the same SINR. Reports the SINR offset that best aligns the two
curves (an implementation loss in dB: real receivers are worse than theory by a few dB) and the remaining
error. That offset is the number to feed back into sim/radio.py before trusting the benchmark on hardware.

    python -m hil.compare results/bench_sdr.csv
"""
from __future__ import annotations

import csv
import sys

import numpy as np

from .radio_backend import predicted_per


def compare(path: str) -> dict:
    with open(path, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["test"] == "link_budget" and r.get("sinr_db")]
    sinr = np.array([float(r["sinr_db"]) for r in rows])
    per = np.array([float(r["per"]) for r in rows])
    best = None
    for off in np.arange(-6, 6.01, 0.25):
        pred = np.array([predicted_per(s - off) for s in sinr])
        err = float(np.sqrt(np.mean((pred - per) ** 2)))
        if best is None or err < best[1]:
            best = (float(off), err)
    pred0 = np.array([predicted_per(s) for s in sinr])
    return {"rows": len(rows), "rms_per_error_as_is": round(float(np.sqrt(np.mean((pred0 - per) ** 2))), 4),
            "implementation_loss_db": best[0], "rms_per_error_after_offset": round(best[1], 4)}


if __name__ == "__main__":
    print(compare(sys.argv[1]))
