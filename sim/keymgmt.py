"""Key management: per-device identities, a rekeyable group key, session keys, signed orders, revocation.

Why: with one shared mission key, any captured radio could read everything and pretend to be any other
unit, and a radio that reboots and restarts its packet counter could reuse an AES-GCM nonce under the same
key (NIST SP 800-38D: a nonce must never repeat under one key). This module closes those gaps.

Keys
  device key DK_i   32 bytes, unique to each radio, loaded with the key loader before the mission. The
                    command post holds every DK_i; a radio holds only its own.
  CP signing key    Ed25519. Its public key is loaded on every radio; only the command post can sign.
  group key GK_g    made by the command post (generation g), sent to each member wrapped under its DK_i
                    (AES-256-GCM). It drives the hop sequence and the rendezvous channel (HKDF per 60 s epoch),
                    which every member must share to hop together. Replaced on every revocation.
  session key       per radio and per JOIN: HKDF(DK_i, "link" | session salt | epoch). The salt is fresh random
                    bytes from the command post at every join or rejoin, so a radio that reboots gets a new key
                    and its packet counter may safely start again at 0: nonce = (src, epoch, seq) never repeats
                    under one key.

What each attack meets
  captured radio    revoke(): its session is deleted (its frames are rejected) and a new group key goes to the
                    others only, so it can no longer follow the hop pattern or the rendezvous channel.
  impersonation     a captured D3 cannot send as D1: D1's frames need D1's session key, derived from DK_1.
  forged orders     channel-switch orders carry the CP's Ed25519 signature; group members cannot sign.
  reboot            the radio JOINs again (authenticated with its DK) and receives a new session salt.
  late joiner       a radio provisioned with a DK joins mid-mission and receives the current group key.

In the simulation every "random" value is derived from the seed, so twin worlds and benchmark replays use
the same keys; on real radios they come from a hardware random generator and the key loader.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass, field
from typing import Optional

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .security import EPOCH_S, KeySchedule, hkdf

GRANT = struct.Struct(">I16s32s")          # generation, session salt, group key (52 bytes, then encrypted)


def _det(seed: int, mission: int, *parts) -> bytes:
    """Deterministic 32 bytes for the simulation (a hardware RNG / key loader on real radios)."""
    h = hashlib.sha256(b"AEGIS-LINK keymgmt|" + str(seed).encode() + b"|" + str(mission).encode())
    for p in parts:
        h.update(b"|" + (p if isinstance(p, bytes) else str(p).encode()))
    return h.digest()


class SessionKeys:
    """KeySchedule-compatible view of one radio's session: .aead(epoch) for its data frames."""

    def __init__(self, dk: bytes, salt: bytes):
        self.root = hkdf(dk, b"AEGIS-LINK|session|" + salt)
        self._ks = KeySchedule(self.root)

    def aead(self, epoch: int) -> AESGCM:
        return self._ks.aead(epoch)

    def key(self, purpose: str, epoch: int) -> bytes:
        return self._ks.key(purpose, epoch)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.root).hexdigest()[:8].upper()


@dataclass
class Radio:
    """What one radio holds: its own device key, the CP's public key, its session and the group key."""
    name: str
    addr: int
    dk: bytes
    cp_public: Ed25519PublicKey
    session: Optional[SessionKeys] = None
    group: Optional[KeySchedule] = None
    generation: int = -1
    seq: int = 0

    def join_request(self, nonce_bytes: bytes) -> bytes:
        """JOIN = address | random challenge | HMAC(DK, ...). Proves the radio holds its device key."""
        body = bytes([self.addr]) + nonce_bytes
        return body + hmac.new(self.dk, b"JOIN|" + body, hashlib.sha256).digest()

    def accept_grant(self, grant: bytes) -> str:
        """Verify the CP's signature, unwrap with the device key, install session + group key."""
        sig, wrapped = grant[:64], grant[64:]
        try:
            self.cp_public.verify(sig, wrapped)
        except InvalidSignature:
            return "grant rejected: not signed by the command post"
        try:
            pt = AESGCM(self.dk).decrypt(wrapped[:12], wrapped[12:], b"GRANT|" + bytes([self.addr]))
        except InvalidTag:
            return "grant rejected: not for this radio"
        gen, salt, gk = GRANT.unpack(pt)
        if gen < self.generation:
            return "grant rejected: older than the group key already held"
        self.session, self.group, self.generation, self.seq = SessionKeys(self.dk, salt), KeySchedule(gk), gen, 0
        return "installed"

    def reboot(self) -> None:
        """Power loss: RAM is gone (session, group key, packet counter). The device key survives."""
        self.session, self.group, self.generation, self.seq = None, None, -1, 0


class KeyManager:
    """The command post's side."""

    def __init__(self, seed: int, mission: int, members: dict[str, int]):
        self.seed, self.mission = seed, mission
        self._sk = Ed25519PrivateKey.from_private_bytes(_det(seed, mission, "cp-sign"))
        self.public = self._sk.public_key()
        self.dk = {n: _det(seed, mission, "device", n) for n in members}           # key loader
        self.addr = dict(members)
        self.by_addr = {a: n for n, a in members.items()}
        self.revoked: set[str] = set()
        self.sessions: dict[str, SessionKeys] = {}
        self.joins: dict[str, int] = {}
        self.generation = 0
        self.group_key = _det(seed, mission, "group", 0)
        self.group = KeySchedule(self.group_key)

    # ---- radios ----
    def provision(self, name: str, addr: int) -> Radio:
        """Key loader: a new radio (also one added mid-mission) gets only its own device key + the CP public key."""
        if name not in self.dk:
            self.dk[name] = _det(self.seed, self.mission, "device", name)
            self.addr[name] = addr
            self.by_addr[addr] = name
        return Radio(name, self.addr[name], self.dk[name], self.public)

    def handle_join(self, request: bytes) -> tuple[Optional[bytes], str]:
        addr, body, mac = request[0], request[:-32], request[-32:]
        name = self.by_addr.get(addr)
        if name is None:
            return None, f"JOIN from unknown address {addr}"
        if name in self.revoked:
            return None, f"JOIN from {name} refused: revoked"
        if not hmac.compare_digest(mac, hmac.new(self.dk[name], b"JOIN|" + body, hashlib.sha256).digest()):
            return None, f"JOIN claiming to be {name} refused: wrong device key"
        self.joins[name] = self.joins.get(name, 0) + 1
        salt = _det(self.seed, self.mission, "salt", name, self.joins[name])[:16]
        self.sessions[name] = SessionKeys(self.dk[name], salt)
        return self._grant(name, salt), f"{name} joined (session {self.sessions[name].fingerprint()})"

    def _grant(self, name: str, salt: bytes) -> bytes:
        iv = _det(self.seed, self.mission, "iv", name, self.joins.get(name, 0), self.generation)[:12]
        wrapped = iv + AESGCM(self.dk[name]).encrypt(iv, GRANT.pack(self.generation, salt, self.group_key),
                                                      b"GRANT|" + bytes([self.addr[name]]))
        return self._sk.sign(wrapped) + wrapped

    def revoke(self, name: str) -> dict[str, bytes]:
        """Drop the radio's session and replace the group key; returns the new grants for every other member."""
        self.revoked.add(name)
        self.sessions.pop(name, None)
        self.generation += 1
        self.group_key = _det(self.seed, self.mission, "group", self.generation)
        self.group = KeySchedule(self.group_key)
        out = {}
        for n in list(self.sessions):
            # members keep their session salt; only the group key changes
            salt = _det(self.seed, self.mission, "salt", n, self.joins[n])[:16]
            out[n] = self._grant(n, salt)
        return out

    # ---- frames ----
    def session_aead(self, addr: int, epoch: int) -> Optional[AESGCM]:
        name = self.by_addr.get(addr)
        s = self.sessions.get(name) if name else None
        return s.aead(epoch) if s is not None else None

    def sign(self, message: bytes) -> bytes:
        return self._sk.sign(message)

    def epoch_of(self, t: float) -> int:
        return int(t // EPOCH_S)


@dataclass
class SessionReceiver:
    """The command post's frame check with per-radio session keys (same checks and order as security.Receiver)."""
    km: KeyManager
    windows: dict = field(default_factory=dict)

    def open(self, frame: bytes, now_epoch: int):
        from .security import HEADER, HEADER_LEN, TAG_LEN, VERSION, OpenResult, ReplayWindow, nonce
        if len(frame) < HEADER_LEN + TAG_LEN:
            return OpenResult(False, "frame too short")
        ver, ftype, src, dst, ep16, seq = HEADER.unpack(frame[:HEADER_LEN])
        if ver != VERSION:
            return OpenResult(False, f"unknown version {ver}")
        name = self.km.by_addr.get(src)
        if name is None:
            return OpenResult(False, f"sender {src} is not in this mission")
        if name in self.km.revoked:
            return OpenResult(False, f"sender {name} is revoked (captured or compromised)")
        epoch = now_epoch if (now_epoch & 0xFFFF) == ep16 else now_epoch - 1
        if (epoch & 0xFFFF) != ep16:
            return OpenResult(False, f"key epoch {ep16} is not current (expected {now_epoch & 0xFFFF})")
        aead = self.km.session_aead(src, epoch)
        if aead is None:
            return OpenResult(False, f"{name} has no session: it must JOIN first")
        sess = self.km.sessions[name].fingerprint()
        win = self.windows.setdefault((src, sess, epoch), ReplayWindow())
        why = win.check(seq)
        if why:
            return OpenResult(False, why, src, seq, ftype)
        try:
            pt = aead.decrypt(nonce(src, epoch, seq), frame[HEADER_LEN:], frame[:HEADER_LEN])
        except InvalidTag:
            return OpenResult(False, f"GCM tag does not verify under {name}'s session key (forged, altered or another radio's key)",
                              src, seq, ftype)
        win.accept(seq)
        if len(self.windows) > 512:
            for k in [k for k in self.windows if k[2] < now_epoch - 1]:
                self.windows.pop(k, None)
        return OpenResult(True, "verified", src, seq, ftype, pt)
