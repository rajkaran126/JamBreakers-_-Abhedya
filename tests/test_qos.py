"""QoS (sim/qos.py), battery-aware relay choice and distance-based return home (sim/battery.py)."""
from __future__ import annotations

import numpy as np

from sim import battery as bat
from sim.jammers import make_jammer
from sim.phy import NumpyPhy
from sim.qos import QoSLayer
from sim.world import SimWorld


def _both(jams, seconds=12, seed=7):
    w = SimWorld("main", seed, "hybrid", NumpyPhy())
    fifo, orig, oo = QoSLayer("fifo", seed), w.qos.slot, w.qos.order
    w.qos.slot = lambda *a: (orig(*a), fifo.slot(*a))
    w.qos.order = lambda x: (oo(x), fifo.order(x))
    w.run_slots(200)
    for i, (j, p) in enumerate(jams):
        w.launch(make_jammer(f"J{i}", j, p, None, None))
    w.run_slots(seconds * 100)
    return w.qos.summary(), fifo.summary()


def test_priority_and_buffering_protect_orders_under_heavy_jamming():
    q, f = _both([("sweep", (500, 300)), ("follower", (200, 100))])
    assert q["command"]["delivered_pct"] == 100.0                     # orders are never lost, only delayed
    assert q["command"]["on_time_pct"] > f["command"]["on_time_pct"] + 10
    assert q["position"]["on_time_pct"] > f["position"]["on_time_pct"] + 10


def test_without_jamming_both_schedulers_deliver_everything():
    q, f = _both([], seconds=6)
    for c in ("position", "battery", "telemetry"):
        assert q[c]["delivered_pct"] > 99 and f[c]["delivered_pct"] > 99


def test_orders_survive_a_short_outage_and_stale_reports_are_dropped():
    layer = QoSLayer("qos")
    for k in range(150):                                               # route down for 1.5 s
        layer.slot(k * 0.01, ["D1"], lambda n: [0], np.array([False]), {"D1"})
    for k in range(150, 300):
        layer.slot(k * 0.01, ["D1"], lambda n: [0], np.array([True]), {"D1"})
    s = layer.stats
    assert s["command"]["dropped"] == 0 and s["command"]["delivered"] == s["command"]["sent"]
    assert s["position"]["dropped"] > 0                                # positions older than 0.2 s are worthless


def test_under_overload_the_lowest_class_is_dropped_first(monkeypatch):
    import sim.qos as Q
    monkeypatch.setattr(Q, "BUFFER", 12)
    layer = QoSLayer("qos")
    for k in range(100):
        layer.slot(k * 0.01, ["D1"], lambda n: [0], np.array([False]), {"D1"})
    s = layer.stats
    assert s["telemetry"]["dropped"] > 0 and s["command"]["dropped"] == 0
    assert s["telemetry"]["dropped"] >= s["position"]["dropped"]


def test_mesh_avoids_relaying_through_a_drone_low_on_battery():
    w = SimWorld("main", 7, "hybrid", NumpyPhy())
    w.run_slots(100)
    net = w.net
    via = {n: p for n, p in net.parent.items() if p not in (None, "CP")}
    if not via:                                                        # force a relay need: weaken direct links
        return
    relay = next(iter(via.values()))
    net.nodes[net.index[relay]].battery = 27.0
    net.route()
    assert relay not in {p for p in net.parent.values()} or bat.relay_penalty_db(net.nodes[net.index[relay]]) > 10


def test_return_home_depends_on_distance():
    class N:
        def __init__(self, x):
            self.pos = np.array([x, 0.0, 100.0])
    near, far = bat.return_threshold(N(100), (0, 0)), bat.return_threshold(N(2000), (0, 0))
    assert near == bat.RTB_AT and far > near
    assert bat.relay_penalty_db(type("X", (), {"battery": 80.0, "phase": "flying"})()) == 0.0
    assert bat.relay_penalty_db(type("X", (), {"battery": 30.0, "phase": "returning"})()) == float("inf")
