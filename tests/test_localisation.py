"""Jammer localisation accuracy against the true position (sim/loc_eval.py)."""
from __future__ import annotations

import numpy as np

from sim.loc_eval import run_case


def test_inside_the_formation_estimates_are_close_and_the_radius_is_honest():
    rows = [run_case(j, p, s) for j in ("barrage", "follower") for p in ((220, 140), (600, 450)) for s in (1, 2)]
    errs = np.array([e for r in rows for e in r["errors"]])
    inside = [i for r in rows for i in r["inside"]]
    assert errs.size >= 20
    assert np.median(errs) < 80 and np.percentile(errs, 95) < 150
    assert np.mean(inside) >= 0.9


def test_a_poorly_observed_jammer_is_not_published_with_false_precision():
    rows = [run_case("barrage", (900, 200), s) for s in (1, 2)]      # beside the hill: readings biased
    for r in rows:
        for e, ok in zip(r["errors"], r["inside"]):
            assert ok or e > 150                                     # if it is wrong, it is wrong visibly, not by a hair
    assert sum(len(r["errors"]) for r in rows) <= sum(r["checks"] for r in rows) // 2
