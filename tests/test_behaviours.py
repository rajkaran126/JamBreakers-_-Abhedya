"""Multi-label interference assessment (ai/behaviours.py) and the context-aware Hybrid referee."""
from __future__ import annotations

from collections import Counter

import numpy as np

from ai.behaviours import BehaviourTracker
from sim.jammers import make_jammer
from sim.phy import NumpyPhy
from sim.world import SimWorld


def _labels(jams, defender="fixed_hopping", seed=5, slots=600):
    w = SimWorld("main", seed, defender, NumpyPhy())
    w.run_slots(100)
    for i, (j, p) in enumerate(jams):
        w.launch(make_jammer(f"J{i}", j, p, None, None))
    bt, orig, out = BehaviourTracker(), w.defender.on_slot, []

    def spy(obs):
        bt.update(obs.energy_dbm, obs.channel)
        if obs.slot % 25 == 0:
            out.append(tuple(bt.assess().detected))
        return orig(obs)
    w.defender.on_slot = spy
    w.run_slots(slots)
    return Counter(out[3:]).most_common(1)[0][0]


def test_single_jammers_get_one_label_and_no_false_tracking():
    assert _labels([("sweep", (500, 300))]) == ("wideband",)
    assert _labels([("barrage", (220, 140))]) == ("wideband",)
    assert _labels([("follower", (150, 80))]) == ("tracking",)
    assert _labels([("random", (160, 90))]) == ("narrowband",)
    assert _labels([]) == ()


def test_overlapping_jammers_are_reported_together():
    assert _labels([("sweep", (200, 120)), ("follower", (150, 80))]) == ("wideband", "tracking")
    assert set(_labels([("random", (160, 90)), ("follower", (200, 100))])) == {"tracking", "narrowband"}


def test_combined_response_lifts_the_worst_case_on_a_stack():
    """Same seeds, AEGIS with and without the multi-label step, follower (+ smart) hiding under a sweep.
    Measured over 8 seeds the gain is +3 to +5 points on average and the spread drops by two thirds;
    here 4 seeds: the average must not drop and the worst run must improve."""
    import ai.defender as D
    from ai.defender import SIGNATURES

    def run(seed):
        SIGNATURES.clear()
        w = SimWorld("main", seed, "aegis", NumpyPhy())
        w.run_slots(100)
        s0, d0 = w.total_sent, w.total_delivered
        for i, (j, p) in enumerate((("sweep", (500, 300)), ("follower", (200, 100)), ("smart", (350, 250)))):
            w.launch(make_jammer(f"J{i}", j, p, None, None))
        w.run_slots(1500)
        return 100 * (w.total_delivered - d0) / (w.total_sent - s0)
    seeds = (21, 22, 23, 24)
    with_ml = [run(s) for s in seeds]
    keep_c, keep_t = D.AegisDefender._combined, D.AegisDefender.tracking
    try:
        D.AegisDefender._combined = lambda self, obs: None
        D.AegisDefender.tracking = lambda self, t: False
        without = [run(s) for s in seeds]
    finally:
        D.AegisDefender._combined, D.AegisDefender.tracking = keep_c, keep_t
    assert np.mean(with_ml) >= np.mean(without), (with_ml, without)
    assert min(with_ml) > min(without), (with_ml, without)


def test_referee_keeps_aegis_on_a_stack_and_learns_per_context():
    w = SimWorld("main", 6, "hybrid", NumpyPhy())
    w.run_slots(100)
    w.launch(make_jammer("J1", "sweep", (200, 120), None, None))
    w.launch(make_jammer("J2", "follower", (150, 80), None, None))
    ctx = []
    for _ in range(30):
        w.run_slots(50)
        ctx.append((w.defender.ctx, w.defender.leader))
    assert ("stacked", "aegis") in ctx
    assert sum(c == "stacked" for c, _ in ctx[10:]) >= 12
    assert any(k[0] == "stacked" for k in w.defender.score)          # the scoreboard records what worked
