"""Pydantic models for client->server commands. Kept in step with $defs/cmd in shared/schema.json."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from .protocol import ARENA_BOUNDS, STUDIO_BOUNDS

JammerType = Literal["barrage", "random", "sweep", "reactive", "deceptive", "accidental", "follower", "smart", "novel"]


class _Cmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cmd"]
    id: Optional[str] = Field(default=None, max_length=64)
    player: Optional[str] = Field(default=None, max_length=24)


class LaunchJammer(_Cmd):
    action: Literal["launch_jammer"]
    jammer_type: JammerType
    pos: tuple[float, float]
    power_dbm: Optional[float] = Field(default=None, ge=0, le=50)

    @field_validator("pos")
    @classmethod
    def _in_bounds(cls, v: tuple[float, float]) -> tuple[float, float]:
        # Accept anything inside the larger Studio map; the world clamps to its own bounds.
        x, y = v
        xb, yb = STUDIO_BOUNDS["x"], STUDIO_BOUNDS["y"]
        if not (min(xb[0], ARENA_BOUNDS["x"][0]) <= x <= max(xb[1], ARENA_BOUNDS["x"][1])):
            raise ValueError(f"x={x} outside map")
        if not (min(yb[0], ARENA_BOUNDS["y"][0]) <= y <= max(yb[1], ARENA_BOUNDS["y"][1])):
            raise ValueError(f"y={y} outside map")
        return v


class ClearJammers(_Cmd):
    action: Literal["clear_jammers"]


class ToggleAI(_Cmd):
    action: Literal["toggle_ai"]
    enabled: Optional[bool] = None  # None = flip


class SetView(_Cmd):
    action: Literal["set_view"]
    view: Literal["single", "side_by_side"]


class RunBenchmark(_Cmd):
    action: Literal["run_benchmark"]
    seed: Optional[int] = None
    duration_s: Optional[float] = Field(default=None, gt=0, le=120)
    seeds: Optional[int] = Field(default=None, ge=1, le=10)
    quick: Optional[bool] = None


class SecurityTest(_Cmd):
    action: Literal["security_test"]
    test: Literal["legit", "tamper", "spoof", "replay", "eavesdrop", "desync", "impersonate", "capture", "reboot", "clock_loss"]


class LoadScenario(_Cmd):
    action: Literal["load_scenario"]
    name: Literal["border_convoy", "urban_patrol", "coastal_watch", "forest_ambush", "airbase_spoof", "relief_camp",
                  "drone_delivery"]


class ExitScenario(_Cmd):
    action: Literal["exit_scenario"]


class Play(_Cmd):
    action: Literal["play"]


class Pause(_Cmd):
    action: Literal["pause"]


class SetSpeed(_Cmd):
    action: Literal["set_speed"]
    speed: Literal[1, 2, 4, 10]


class Replay(_Cmd):
    """Feed the CNN panel from a recorded spectrum file in recordings/ instead of the simulator; name=None stops."""
    action: Literal["replay"]
    name: Optional[Annotated[str, Field(max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")]] = None


class Restart(_Cmd):
    action: Literal["restart"]


Command = Annotated[
    Union[LaunchJammer, ClearJammers, ToggleAI, SetView, RunBenchmark, SecurityTest,
          LoadScenario, ExitScenario, Play, Pause, SetSpeed, Restart, Replay],
    Field(discriminator="action"),
]

command_adapter: TypeAdapter[Command] = TypeAdapter(Command)


def parse_command(data: object) -> Command:
    """Validate a decoded JSON object. Raises pydantic.ValidationError."""
    return command_adapter.validate_python(data)
