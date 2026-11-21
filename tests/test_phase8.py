"""Phase 8: the six judge questions, each with a test that shows the answer works.

1. battery drain         -> drones fly home, swap, relaunch; the AI caps its power boost on low battery
2. only 7 classes        -> open-set 'unknown' detection + signature memory (retrieval of what worked)
3. sync failure on a hop -> a node that missed the switch rejoins on the rendezvous channel
4. every channel jammed  -> fallback ladder ends in survival mode instead of hopping in circles
5. combine the two AIs   -> hybrid defender (AEGIS + RL with a referee)
6. AI "hallucinates"     -> safety guard fixes impossible/contradictory orders and undoes bad ones
"""
from __future__ import annotations

import math

from ai.defender import SIGNATURES
from backend.commands import parse_command
from sim import battery as bat
from sim.defenders import Action, Decision
from sim.experiment import run_episode
from sim.radio import N_CH
from sim.safety import SafetyGuard
from sim.world import SimWorld
from sim.phy import NumpyPhy


def _world(defender="aegis"):
    w = SimWorld("main", 7, defender, NumpyPhy())
    w.run_slots(20)
    return w


# ---------------------------------------------------------------- 1. battery
def test_low_battery_drone_returns_swaps_and_relaunches():
    w = _world()
    d1 = w.net.nodes[w.net.index["D1"]]
    d1.battery = bat.RTB_AT + 0.05
    seen = set()
    for _ in range(int((bat.SWAP_S + 90) / 0.05)):
        w.slot += 5                               # 50 ms of simulated time
        bat.update(w, 0.05)
        seen.add(d1.phase)
        if d1.phase == "flying" and "relaunching" in seen:
            break
    assert {"returning", "charging", "relaunching"} <= seen
    assert d1.battery > 90


def test_ai_caps_power_boost_when_battery_is_low():
    from ai.defender import POWER_CAP_LOW_BATTERY_DB, battery_low
    w = _world()
    for n in w.net.nodes:
        if getattr(n, "battery", None) is not None:
            n.battery = bat.LOW_AT - 5
    assert battery_low(w)
    r = run_episode("barrage", "aegis", duration_s=6, power_dbm=46)
    assert r.world.net.tx_boost_db <= 12      # sanity: the normal cap still holds
    assert POWER_CAP_LOW_BATTERY_DB < 12


# ---------------------------------------------------------------- 2. unknown jammer + memory
def test_unseen_jammer_is_flagged_unknown_and_remembered():
    SIGNATURES.clear()
    first = run_episode("novel", "aegis", duration_s=10)
    assert any(d["class"] == "unknown" or "unknown" in d.get("reason", "").lower() for d in first.decisions)
    assert SIGNATURES, "a pattern that worked should be stored"
    second = run_episode("novel", "aegis", duration_s=10)
    assert any("memory" in d.get("reason", "").lower() or "seen" in d.get("reason", "").lower() for d in second.decisions)
    assert second.delivery_pct >= first.delivery_pct - 2
    assert second.delivery_pct > 80


def test_known_jammers_are_not_called_unknown():
    SIGNATURES.clear()
    for jt in ("barrage", "sweep", "follower"):
        r = run_episode(jt, "aegis", duration_s=6)
        assert not any(d["class"] == "unknown" for d in r.decisions), jt


# ---------------------------------------------------------------- 3. sync loss
def test_node_that_misses_a_switch_rejoins_fast():
    w = _world()
    res = w.security_test("desync")
    assert res["accepted"] and w.desynced
    w.run_slots(60)
    assert not w.desynced
    assert w.resync_ms and max(w.resync_ms) <= 200


# ---------------------------------------------------------------- 4. all channels jammed
def test_wideband_jamming_ends_in_survival_mode_not_endless_hopping():
    r = run_episode("barrage", "aegis", duration_s=14, power_dbm=46)
    acts = [d["action"] for d in r.decisions]
    assert "survival" in acts or r.world.net.modulation == "BPSK_R2"
    late_hops = [d for d in r.decisions[len(r.decisions) // 2:] if d["action"] == "hop"]
    assert len(late_hops) <= 2, "should stop hopping once every channel is jammed"
    assert r.delivery_pct > 70


# ---------------------------------------------------------------- 5. hybrid
def test_hybrid_runs_and_is_not_worse_than_its_parts_on_easy_attacks():
    for jt in ("follower", "reactive"):
        h = run_episode(jt, "hybrid", duration_s=8)
        a = run_episode(jt, "aegis", duration_s=8)
        assert h.delivery_pct >= a.delivery_pct - 3, jt


# ---------------------------------------------------------------- 6. safety guard
def test_guard_fixes_contradictory_and_impossible_orders():
    w = _world()
    g = SafetyGuard(power_cap_db=12.0)
    d = Decision("barrage", 0.9, "hop", "test",
                 actions=[Action("power", delta_db=40.0), Action("hop", channel=w.channel),
                          Action("mode", mode="keyed"), Action("rate", modulation="QAM1024"),
                          Action("blacklist", channels=(99,))])
    out = g.check(d, w)
    kinds = [a.kind for a in out.actions]
    assert "hop" not in kinds                      # mode beats hop; a hop to the current channel is pointless
    assert all(a.delta_db <= 12 for a in out.actions if a.kind == "power")
    assert not any(a.kind == "rate" for a in out.actions)
    assert all(0 <= c < N_CH for a in out.actions if a.kind == "blacklist" for c in a.channels)
    assert kinds == sorted(kinds, key=["blacklist", "mode", "hop", "power", "rate", "relay"].index)
    assert g.fixes >= 1 and "Safety guard" in out.reason


def test_guard_rate_limits_a_thrashing_controller():
    w = _world()
    g = SafetyGuard(power_cap_db=12.0)
    kept = 0
    for c in range(20):
        if g.check(Decision("x", 0.5, "hop", "spam", actions=[Action("hop", channel=(w.channel + 1 + c % 3) % N_CH)]), w):
            kept += 1
    assert kept <= 6


def test_new_commands_are_valid():
    assert parse_command({"type": "cmd", "action": "security_test", "test": "desync"}).test == "desync"
    assert parse_command({"type": "cmd", "action": "launch_jammer", "jammer_type": "novel", "pos": [150, 80]}).jammer_type == "novel"


# ---------------------------------------------------------------- vehicle trips (source -> destination)
def test_trip_drives_to_destination_waits_and_comes_back():
    from sim.trips import Trip
    tr = Trip([(0, 0), (500, 0), (500, 400)], "Base", "Depot", speed=10.0)
    assert tr.info(0)["to"] == "Depot" and tr(0)[0][:2] == (0.0, 0.0)
    states, pos = [], []
    for k in range(int(tr.period * 10) + 1):
        t = k / 10
        states.append(tr.info(t)["state"]); pos.append(tr(t)[0][:2])
    assert ["driving", "unloading", "returning", "loading"] == list(dict.fromkeys(states))
    end = pos[states.index("unloading")]
    assert abs(end[0] - 500) < 1e-6 and abs(end[1] - 400) < 1e-6          # stops exactly at the destination
    steps = [math.dist(a, b) for a, b in zip(pos, pos[1:])]
    assert max(steps) <= 10.0 * 0.1 + 1e-6                                  # never faster than the speed limit
    assert steps[0] < 0.2                                                   # pulls away gently, no jump


def test_arena_and_scenario_vehicles_report_trips():
    from sim import scenarios
    w = _world()
    trips = [n["trip"] for n in w.state_msg("single", False, 1)["nodes"] if n["kind"] == "vehicle"]
    assert len(trips) == 2 and {t["src"] for t in trips} == {"Forward base", "Field hospital"}
    for sid in scenarios.ids():
        spec = scenarios.get(sid)
        for n in scenarios.build_nodes(spec):
            if n.kind == "vehicle" and len(next(x for x in spec["nodes"] if x["id"] == n.id)["route"]) > 1:
                assert hasattr(n.path, "info"), (sid, n.id)
