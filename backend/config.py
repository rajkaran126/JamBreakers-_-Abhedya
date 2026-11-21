"""Runtime configuration, read from environment variables (all optional)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


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


settings = Settings()
