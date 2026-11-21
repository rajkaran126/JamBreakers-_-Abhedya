"""Network time synchronisation (sim/timesync.py) and its use in the world."""
from __future__ import annotations

from sim.phy import NumpyPhy
from sim.timesync import GUARD_S, TimeSync
from sim.world import SimWorld

NODES = ["CP", "D1", "D2", "D3", "D4", "V1", "V2"]


def _run(ts, seconds, heard=lambda n, t: True, start=0.0):
    worst, first_out = 0.0, None
    for k in range(int(seconds / 0.05)):
        t = start + (k + 1) * 0.05
        out = ts.tick(t, 0.05, {n: heard(n, t) for n in NODES}, set(NODES))
        worst = max(worst, ts.max_error_us())
        if out and first_out is None:
            first_out = t
    return worst, first_out


def test_free_running_clocks_leave_the_guard_and_sync_keeps_them_inside():
    worst, first_out = _run(TimeSync(NODES, 7, sync=False), 300)
    assert first_out is not None and first_out < 120             # +/-20 ppm crystals: out within two minutes
    worst, first_out = _run(TimeSync(NODES, 7), 300)
    assert first_out is None and worst < 50                        # synced: tens of microseconds


def test_holdover_keeps_a_radio_inside_the_guard_without_beacons():
    ts = TimeSync(NODES, 7)
    _run(ts, 30)                                                   # learns its drift first
    _run(ts, 120, heard=lambda n, t: n != "D2", start=30)
    assert abs(ts.clocks["D2"].err) < GUARD_S / 2


def test_backup_time_master_takes_over_when_the_command_post_clock_is_lost():
    ts = TimeSync(NODES, 7)
    _run(ts, 20)
    ts.lose_master(20.0)
    worst, first_out = _run(ts, 60, start=20)
    assert ts.master == "D1" and first_out is None and worst < 100


def test_rebooted_radio_is_caught_by_the_guard_and_rejoins():
    w = SimWorld("main", 7, "hybrid", NumpyPhy())
    w.run_slots(500)
    assert w.kpis()["clock_error_us"] < 50
    r = w.security_test("reboot")
    assert r["accepted"]
    w.run_slots(300)
    assert w.resync_ms and not w.desynced
    assert w.kpis()["clock_error_us"] < 50
    w.security_test("clock_loss")
    w.run_slots(600)
    assert w.kpis()["time_master"] == "D1" and w.kpis()["delivery_pct"] > 90
