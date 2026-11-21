"""Runtime configuration, read from environment variables (all optional)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: _env("AEGIS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("AEGIS_PORT", "8000")))
    tick_hz: float = field(default_factory=lambda: float(_env("AEGIS_TICK_HZ", "20")))
    slot_ms: float = field(default_factory=lambda: float(_env("AEGIS_SLOT_MS", "10")))
    seed: int = field(default_factory=lambda: int(_env("AEGIS_SEED", "42")))
    # 'sim' = the real simulation; 'fake' = lightweight placeholder world for UI work
    world: str = field(default_factory=lambda: _env("AEGIS_WORLD", "sim"))
    # 'gnuradio' | 'numpy' — used by sim/ from Phase 1
    signal_backend: str = field(default_factory=lambda: _env("SIGNAL_BACKEND", "numpy"))
    # Per-client outgoing queue size; oldest messages are dropped for slow clients
    client_queue: int = field(default_factory=lambda: int(_env("AEGIS_CLIENT_QUEUE", "200")))
    # sign-in for every screen that is not the demo laptop itself (see backend/auth.py); AEGIS_AUTH=0 switches it off
    auth: bool = field(default_factory=lambda: _env("AEGIS_AUTH", "1") != "0")
    # a phone must also show the join code from the laptop's QR (proves it is in the room)
    require_join_code: bool = field(default_factory=lambda: _env("AEGIS_JOIN_CODE", "1") != "0")
    users_file: str = field(default_factory=lambda: _env("AEGIS_USERS_FILE", str(_ROOT / "data" / "users.json")))


settings = Settings()
