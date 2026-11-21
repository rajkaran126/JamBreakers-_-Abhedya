"""Guided scenarios: every one loads, narrates itself, ends with a report, and the AI beats fixed hopping."""
from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from backend.commands import parse_command
from backend.config import Settings
from backend.protocol import load_schema
from sim import scenarios as scn
from sim.world import SimArena

SCHEMA = load_schema()
IDS = scn.ids()


def validate(msg):
    Draft202012Validator(SCHEMA).validate(msg)


def test_catalog_is_complete():
    assert len(IDS) == 7
    jammers = {scn.get(i)["jammer"] for i in IDS}
    assert jammers == {"barrage", "random", "sweep", "reactive", "deceptive", "accidental", "follower"}
    themes = {scn.get(i)["theme"] for i in IDS}
    assert len(themes) == 7                                   # a different environment for each scenario
    for i in IDS:
        sc = scn.get(i)
        assert sc["nodes"][0]["id"] == "CP" or any(n["id"] == "CP" for n in sc["nodes"])
        assert sc["steps"] and all(a["t"] < b["t"] for a, b in zip(sc["steps"], sc["steps"][1:]))
        assert sc["steps"][-1]["t"] < sc["duration_s"]
        for key in ("title", "story", "watch", "ai_response", "expected", "camera", "time_of_day"):
            assert sc.get(key), (i, key)


@pytest.mark.parametrize("sid", IDS)
def test_scenario_runs_end_to_end(sid):
    a = SimArena(Settings())
    out = a.handle(parse_command({"type": "cmd", "action": "load_scenario", "name": sid}))
    hello = [m for m in out if m["type"] == "hello"]
    assert hello and hello[0]["scenario"] == sid and hello[0]["theme"] == scn.get(sid)["theme"]
    for m in out:
        validate(m)
    assert a.paused                                           # waits on the briefing
    a.handle(parse_command({"type": "cmd", "action": "play"}))
    a.handle(parse_command({"type": "cmd", "action": "set_speed", "speed": 4}))
    captions, report, states = [], None, 0
    for _ in range(int(scn.get(sid)["duration_s"] / 0.05 / 4) + 200):
        for m in a.step(0.05):
            if m["type"] == "event" and m.get("caption"):
                captions.append(m); validate(m)
            elif m["type"] == "report":
                report = m; validate(m)
            elif m["type"] == "state" and states < 3:
                states += 1; validate(m); assert "scenario_t" in m
        if report:
            break
    assert len(captions) == len(scn.get(sid)["steps"])
    assert report is not None and report["scenario"] == sid
    off, on = report["ai_off"]["delivery_attack_pct"], report["ai_on"]["delivery_attack_pct"]
    assert on >= off - 0.5, (sid, off, on)
    assert on >= 85, (sid, on)
    assert report["ai_on"].get("frames_forged_accepted", 0) == 0


def test_exit_returns_to_arena():
    a = SimArena(Settings())
    a.handle(parse_command({"type": "cmd", "action": "load_scenario", "name": "urban_patrol"}))
    out = a.handle(parse_command({"type": "cmd", "action": "exit_scenario"}))
    hello = [m for m in out if m["type"] == "hello"][0]
    assert hello["scenario"] is None and hello["theme"] == "field"


def test_focus_is_shared_and_captions_drive_it():
    a = SimArena(Settings())
    a.handle(parse_command({"type": "cmd", "action": "load_scenario", "name": "drone_delivery"}))
    a.handle(parse_command({"type": "cmd", "action": "play"}))
    seen = set()
    for _ in range(int(20 / 0.05)):
        for m in a.step(0.05):
            if m["type"] == "state":
                seen.add(m["focus"])
    assert seen == {"ai_on", "ai_off"}                        # captions switched the shown defence
    out = a.handle(parse_command({"type": "cmd", "action": "toggle_ai", "enabled": False}))
    assert out[0]["focus"] == "ai_off" and a.focus_manual
    validate(out[0])
    for _ in range(int(12 / 0.05)):
        for m in a.step(0.05):
            if m["type"] == "state":
                assert m["focus"] == "ai_off"                 # a person's choice wins over the captions
