"""The interface every world (fake now, real simulation later) must provide to the server.

The server knows nothing about radios: it calls step() every broadcast tick and handle() for each
validated command, and broadcasts whatever messages come back. Swapping the fake world for the
real simulation in Phase 1 touches only the factory in backend/app.py.
"""
from __future__ import annotations

from typing import Any, Protocol

from .commands import Command

Message = dict[str, Any]


class World(Protocol):
    def hello_info(self) -> dict[str, Any]:
        """Fields for the hello message (everything except the envelope and session_id)."""
        ...

    def step(self, dt: float) -> list[Message]:
        """Advance by dt seconds of wall time; return messages to broadcast (state, spectrum, events...)."""
        ...

    def handle(self, cmd: Command) -> list[Message]:
        """Apply a validated command; return messages to broadcast (events, security results, errors...)."""
        ...
