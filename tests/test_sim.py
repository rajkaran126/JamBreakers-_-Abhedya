"""Phase 1 tests: physics, jammers, baselines, determinism, twin worlds, GNU Radio parity."""
from __future__ import annotations

import numpy as np
import pytest

from backend.commands import parse_command
from backend.config import Settings
from sim.experiment import run_episode
from sim.hopping import FIXED_PATTERN, keyed_channel
from sim.phy import EmitterSpec, NumpyPhy
from sim.radio import (
    BINS_PER_CH, NFFT, NOISE_BAND_DBM, channel_offset_hz, packet_delivery, segment_hits_box,
)
from sim.world import SimArena, SimWorld

# ---------- physics ----------


def test_obstacle_intersection():
    box = ([0, 0], [10, 10, 20])
    assert segment_hits_box(np.array([-50, 0, 5.0]), np.array([50, 0, 5.0]), *box)
    assert not segment_hits_box(np.array([-50, 0, 30.0]), np.array([50, 0, 30.0]), *box)   # flies over
    assert not segment_hits_box(np.array([-50, 20, 5.0]), np.array([50, 20, 5.0]), *box)   # passes beside


def test_packet_delivery_curve():
    s = np.array([-10, 0, 3, 6, 10, 20])
    q = packet_delivery(s, "QPSK")
    assert np.all(np.diff(q) >= 0) and q[0] < 0.01 and q[-1] > 0.999
    assert np.all(packet_delivery(s, "BPSK") >= q)          # BPSK fallback is more robust


def test_spectrogram_calibration():
    rng = np.random.default_rng(0)
    phy = NumpyPhy()
    floor = np.mean([np.mean(10 ** (phy.synthesize([], rng) / 10)) for _ in range(5)])
    assert abs(10 * np.log10(floor) - (NOISE_BAND_DBM - 10 * np.log10(NFFT))) < 1.0
    S = np.mean([10 ** (phy.synthesize([EmitterSpec("qpsk", -70.0, channel_offset_hz(3))], rng) / 10) for _ in range(10)], axis=0)
    ch3 = 10 * np.log10(S.mean(axis=0)[3 * BINS_PER_CH:4 * BINS_PER_CH].sum())
    assert abs(ch3 - (-70.0)) < 1.5


def test_keyed_hopping_agrees_and_avoids_blacklist():
    key = b"k" * 32
    seq = [keyed_channel(key, s, blacklist={2, 5}) for s in range(2000)]
    assert seq == [keyed_channel(key, s, blacklist={2, 5}) for s in range(2000)]   # both ends agree
    assert 2 not in seq and 5 not in seq
    counts = np.bincount(seq, minlength=8)[[0, 1, 3, 4, 6, 7]]
    assert counts.min() > 250                                                    # spread over the allowed band
    assert seq != [keyed_channel(b"x" * 32, s, blacklist={2, 5}) for s in range(2000)]   # key matters


# ---------- network and jammers ----------


def test_clean_network_is_healthy():
    r = run_episode(None, "none", duration_s=5)
    assert r.delivery_pct > 98
    w = r.world
    assert all(w.net.path_links(n.id) for n in w.net.nodes if n.id != "CP")


@pytest.mark.parametrize("jammer", ["barrage", "random", "sweep", "reactive", "deceptive", "follower"])
def test_every_hostile_jammer_hurts_an_undefended_network(jammer):
    assert run_episode(jammer, "none", duration_s=8).delivery_pct < 70


def test_accidental_interference_is_mild():
    assert run_episode("accidental", "none", duration_s=8).delivery_pct > 70


def test_energy_defender_hops_away_fast():
    r = run_episode("deceptive", "energy", duration_s=8)
    assert r.delivery_pct > 95 and r.hops >= 1
    assert r.hop_latency_median_ms is not None and r.hop_latency_median_ms < 100
    assert any(d["action"] == "hop" for d in r.decisions)


def test_follower_learns_the_fixed_pattern():
    """Conventional FHSS is predictable: the follower learns it and jams almost every slot."""
    assert FIXED_PATTERN and run_episode("follower", "fixed_hopping", duration_s=8).delivery_pct < 20


def test_fixed_hopping_survives_a_single_narrowband_jammer_but_not_random():
    assert run_episode("deceptive", "fixed_hopping", duration_s=8).delivery_pct > 85
    assert run_episode("random", "fixed_hopping", duration_s=8).delivery_pct < 80


def test_same_seed_same_run_and_different_seed_differs():
    a = run_episode("random", "energy", seed=11, duration_s=6)
    b = run_episode("random", "energy", seed=11, duration_s=6)
    c = run_episode("random", "energy", seed=12, duration_s=6)
    key = lambda r: (r.world.total_delivered, r.world.hops, r.world.outage_ms, tuple(r.world.latencies))  # noqa: E731
    assert key(a) == key(b)
    assert key(a) != key(c)


def test_relay_flies_above_the_tallest_obstacle():
    w = SimWorld("main", 1, "none", NumpyPhy())
    w._dispatch_relay("CP", "V2")
    relay = [n for n in w.net.nodes if n.kind == "relay"][0]
    assert relay.pos[2] == max(o["size"][2] for o in w.net.obstacles) + 30
    w.run_slots(20)   # network still runs with the extra node


# ---------- arena (server-facing) ----------


def _arena_run(a: SimArena, seconds: float) -> list[dict]:
    out = []
    for _ in range(int(seconds * 20)):
        out.extend(a.step(0.05))
    return out


def test_side_by_side_twins_share_time_and_attack():
    a = SimArena(Settings())
    a.handle(parse_command({"type": "cmd", "action": "set_view", "view": "side_by_side"}))
    a.handle(parse_command({"type": "cmd", "action": "launch_jammer", "jammer_type": "follower", "pos": [150, 80]}))
    msgs = _arena_run(a, 4)
    off = [m for m in msgs if m["type"] == "state" and m["world"] == "ai_off"]
    on = [m for m in msgs if m["type"] == "state" and m["world"] == "ai_on"]
    assert len(off) == len(on) == 80
    assert off[-1]["sim_time_s"] == on[-1]["sim_time_s"]
    assert off[-1]["defender"] == "fixed_hopping" and on[-1]["defender"] != "fixed_hopping"
    assert [j["id"] for j in off[-1]["jammers"]] == [j["id"] for j in on[-1]["jammers"]] == ["J1"]


def test_arena_pause_and_speed():
    a = SimArena(Settings())
    _arena_run(a, 0.5)
    t0 = [m for m in a.step(0.05) if m["type"] == "state"][0]["sim_time_s"]
    a.handle(parse_command({"type": "cmd", "action": "pause"}))
    t1 = [m for m in _arena_run(a, 0.5) if m["type"] == "state"][-1]["sim_time_s"]
    assert t1 == t0
    a.handle(parse_command({"type": "cmd", "action": "play"}))
    a.handle(parse_command({"type": "cmd", "action": "set_speed", "speed": 4}))
    t2 = [m for m in _arena_run(a, 1.0) if m["type"] == "state"][-1]["sim_time_s"]
    assert 3.5 < t2 - t1 < 4.5


# ---------- GNU Radio parity (runs only where GNU Radio is installed) ----------


def test_gnuradio_matches_numpy():
    pytest.importorskip("gnuradio.digital")
    from sim.phy_gnuradio import GnuRadioPhy
    em = [EmitterSpec("qpsk", -75, channel_offset_hz(2)), EmitterSpec("noise", -65, channel_offset_hz(5), 5e6)]
    def per_ch(phy):
        rng = np.random.default_rng(1)
        S = np.mean([10 ** (phy.synthesize(em, rng) / 10) for _ in range(10)], axis=0)
        return 10 * np.log10(S.mean(axis=0).reshape(8, BINS_PER_CH).sum(axis=1))
    assert np.max(np.abs(per_ch(NumpyPhy()) - per_ch(GnuRadioPhy()))) < 2.5
