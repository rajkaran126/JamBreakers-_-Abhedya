"""Every command: a valid example is accepted, answered without errors and every reply matches the schema;
malformed versions are rejected by the parser before they reach the simulation."""
from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.commands import parse_command
from backend.config import Settings
from backend.protocol import load_schema
from sim.world import SimArena

SCHEMA = load_schema()
V = Draft202012Validator(SCHEMA)
CMD = Draft202012Validator({**SCHEMA, "$ref": "#/$defs/cmd"})

VALID = {
    "launch_jammer": {"jammer_type": "smart", "pos": [300, 150], "power_dbm": 30},
    "clear_jammers": {},
    "toggle_ai": {"enabled": False},
    "set_view": {"view": "side_by_side"},
    "run_benchmark": {"quick": True, "duration_s": 2},
    "security_test": {"test": "replay"},
    "load_scenario": {"name": "coastal_watch"},
    "exit_scenario": {},
    "play": {},
    "pause": {},
    "set_speed": {"speed": 2},
    "restart": {},
    "replay": {"name": "sim_capture_sweep"},
}
INVALID = [
    {"action": "launch_jammer", "jammer_type": "laser", "pos": [0, 0]},          # unknown jammer type
    {"action": "launch_jammer", "jammer_type": "random"},                        # no position
    {"action": "launch_jammer", "jammer_type": "random", "pos": [99999, 0]},     # off the map
    {"action": "launch_jammer", "jammer_type": "random", "pos": [0, 0], "power_dbm": 90},
    {"action": "set_view", "view": "split"},
    {"action": "set_speed", "speed": 3},
    {"action": "security_test", "test": "rowhammer"},
    {"action": "load_scenario", "name": "disaster_zone"},
    {"action": "run_benchmark", "seeds": 50},
    {"action": "toggle_ai", "enabled": "yes please"},
    {"action": "play", "surprise": 1},                                           # unknown field
    {"action": "self_destruct"},
    {"player": "x" * 40, "action": "play"},                                      # name too long
]


def test_every_command_in_the_parser_has_a_case_here():
    from backend import commands as C
    actions = {f.annotation.__args__[0] for m in C._Cmd.__subclasses__() for n, f in m.model_fields.items() if n == "action"}
    assert actions == set(VALID)


@pytest.mark.parametrize("action", list(VALID))
def test_valid_command_is_handled_cleanly(action):
    a = SimArena(Settings())
    msg = {"type": "cmd", "id": "t1", "player": "Judge", "action": action, **VALID[action]}
    CMD.validate(msg)                                     # the schema agrees with the parser
    out = a.handle(parse_command(msg))
    assert not [m for m in out if m["type"] == "error"], out
    for m in out:
        V.validate(m)
    for _ in range(6):                                    # and the world keeps running afterwards
        for m in a.step(0.05):
            V.validate(m)


@pytest.mark.parametrize("bad", INVALID, ids=[str(i) for i in range(len(INVALID))])
def test_malformed_command_is_rejected(bad):
    with pytest.raises(ValidationError):
        parse_command({"type": "cmd", **bad})
