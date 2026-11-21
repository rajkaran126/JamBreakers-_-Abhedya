"""Hop sequences.

FIXED_PATTERN is the conventional FHSS baseline: a public, repeating pattern (anyone who watches for
8 slots knows it). keyed_channel() is AEGIS-LINK's sequence: both ends compute
HMAC-SHA256(key, slot) and map it onto the channels that are not blacklisted, so they always agree
and a jammer without the key cannot predict it.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Iterable

from .radio import N_CH

FIXED_PATTERN = [0, 3, 6, 1, 4, 7, 2, 5]


def fixed_channel(slot: int) -> int:
    return FIXED_PATTERN[slot % len(FIXED_PATTERN)]


def keyed_index(key: bytes, slot: int) -> int:
    digest = hmac.new(key, b"hop" + slot.to_bytes(8, "big"), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def keyed_channel(key: bytes, slot: int, blacklist: Iterable[int] = (), avoid: Iterable[int] = ()) -> int:
    """next channel = HMAC-SHA256(key, slot) mod |allowed|, over channels not blacklisted.
    'avoid' (e.g. +-1 of the last 3 channels in fast mode) is a soft preference: dropped if it would
    leave nothing. Both ends pass the same blacklist (sent in authenticated frames), so they agree."""
    bl = set(blacklist)
    allowed = [c for c in range(N_CH) if c not in bl] or list(range(N_CH))
    preferred = [c for c in allowed if c not in set(avoid)] or allowed
    return preferred[keyed_index(key, slot) % len(preferred)]


def rendezvous_channel(key: bytes, epoch: int) -> int:
    """Key-derived channel where a lost node listens to rejoin; changes every key epoch."""
    digest = hmac.new(key, b"rdv" + epoch.to_bytes(8, "big"), hashlib.sha256).digest()
    return digest[0] % N_CH
