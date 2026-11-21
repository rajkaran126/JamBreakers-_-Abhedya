"""RF calibration (ai/calibration.py): faulty front-end measurements restored before the CNN sees them."""
from __future__ import annotations

import numpy as np

from ai.calibration import CH_BINS, Calibrator, Impairments
from ai.cnn import CNN
from ai.features import NOISE_BIN_DBM
from sim.experiment import DEFAULT_JAMMER_POS
from sim.jammers import make_jammer
from sim.phy import NumpyPhy
from sim.world import SimWorld


def _session(jammer, seed, n=60):
    w = SimWorld("main", 30 + seed, "fixed_hopping", NumpyPhy())
    w.run_slots(50)
    imp, cal = Impairments(seed=seed), Calibrator()
    quiet = []
    for _ in range(25):
        w.run_slots(2)
        quiet.append(imp.apply(w.sense("CP")))
    cal.calibrate_quiet(quiet, imp.reported_gain_db)
    if jammer:
        w.launch(make_jammer("J1", jammer, DEFAULT_JAMMER_POS[jammer], None, None))
    w.run_slots(50)
    out = []
    for _ in range(n):
        w.run_slots(2)
        win = w.sense("CP")
        bad = imp.apply(win)
        out.append((win, bad, cal.calibrate(bad, imp.reported_gain_db)))
    return out, w


def test_calibration_restores_cnn_accuracy_on_faulty_measurements():
    cnn = CNN()
    acc = {"clean": [], "raw": [], "cal": []}
    for jam, label in (("barrage", "barrage"), ("sweep", "sweep"), (None, "clean")):
        for seed in (1, 2):
            rows, _ = _session(jam, seed, n=40)
            for win, bad, fixed in rows:
                acc["clean"].append(cnn.predict(win)["class"] == label)
                acc["raw"].append(cnn.predict(bad)["class"] == label)
                acc["cal"].append(cnn.predict(fixed)["class"] == label)
    clean, raw, cal = (100 * np.mean(acc[k]) for k in ("clean", "raw", "cal"))
    assert cal >= clean - 2 and cal > raw + 5, (clean, raw, cal)


def test_a_barrage_is_not_calibrated_away():
    rows, _ = _session("barrage", 3, n=150)                           # 3 s of barrage after calibration
    levels = [float(np.median(fixed)) - NOISE_BIN_DBM for _, _, fixed in rows]
    assert min(levels) > 10                                           # still clearly above the floor after 3 s
    assert abs(levels[-1] - levels[0]) < 1.0                          # and not drifting down into it


def test_occupancy_is_measured_over_the_occupied_bandwidth():
    assert all(len(b) == 4 for b in CH_BINS)                          # the 2.7 MHz signal -> 4 bins of 625 kHz
    rows, w = _session("random", 4, n=30)
    jammed = set(w.jammers[0].channels)
    occ = Calibrator.occupancy(rows[-1][2])
    hot = {o["channel"] for o in occ if o["occupied"]}
    assert jammed <= hot
    assert len(hot - jammed) <= 1                                     # at most our own transmission besides the jammer
