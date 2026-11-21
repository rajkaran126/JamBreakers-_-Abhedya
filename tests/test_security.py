"""Phase 3 tests: AES-256-GCM frames, replay window, key epochs, keyed hopping, security in the running world."""
from __future__ import annotations

import pytest

from sim import security as sec
from sim.experiment import run_episode
from sim.hopping import keyed_channel

MK = sec.mission_key(7, 1)


def _rx():
    return sec.Receiver(sec.KeySchedule(MK), {1, 2, 3})


def _frame(seq, epoch=0, src=2, key=MK, payload=b"x" * 32):
    return sec.seal(sec.KeySchedule(key), sec.T_DATA, src, 1, epoch, seq, payload)


def test_frame_is_58_bytes_and_roundtrips():
    f = _frame(0)
    assert len(f) == sec.HEADER_LEN + sec.TELEMETRY_LEN + sec.TAG_LEN == 58
    r = _rx().open(f, 0)
    assert r.ok and r.payload == b"x" * 32 and r.src == 2


@pytest.mark.parametrize("pos", [0, 3, 9, 10, 25, 41, 57])
def test_any_flipped_bit_is_rejected(pos):
    f = bytearray(_frame(5))
    f[pos] ^= 0x01
    r = _rx().open(bytes(f), 0)
    assert not r.ok


def test_wrong_key_is_rejected():
    r = _rx().open(_frame(0, key=sec.random_key()), 0)
    assert not r.ok and "tag" in r.reason


def test_replay_window():
    rx = _rx()
    assert rx.open(_frame(10), 0).ok
    assert "replay" in rx.open(_frame(10), 0).reason              # exact copy
    assert rx.open(_frame(8), 0).ok                                # late but new, inside the window
    assert not rx.open(_frame(8), 0).ok
    assert rx.open(_frame(200), 0).ok
    assert "older" in rx.open(_frame(100), 0).reason               # fell out of the 64-frame window


def test_epochs_previous_ok_older_rejected_unknown_sender_rejected():
    rx = _rx()
    assert rx.open(_frame(0, epoch=4), 5).ok                       # clock skew: previous epoch accepted
    assert not rx.open(_frame(1, epoch=3), 5).ok                   # two epochs old
    assert "not in this mission" in rx.open(_frame(0, src=9), 0).reason


def test_epoch_keys_differ_and_nonces_unique():
    ks = sec.KeySchedule(MK)
    assert ks.key("enc", 0) != ks.key("enc", 1) != ks.key("hop", 1)
    assert len({sec.nonce(s, e, q) for s in (1, 2) for e in (0, 1) for q in range(50)}) == 200


def test_keyed_sequence_shared_by_both_ends_and_rotates_per_mission():
    a = [keyed_channel(sec.KeySchedule(MK).key("hop", 0), s, {3}) for s in range(500)]
    b = [keyed_channel(sec.KeySchedule(MK).key("hop", 0), s, {3}) for s in range(500)]
    c = [keyed_channel(sec.KeySchedule(sec.mission_key(7, 2)).key("hop", 0), s, {3}) for s in range(500)]
    assert a == b and a != c


def test_fingerprint_reveals_nothing_obvious():
    fp = sec.fingerprint(MK)
    assert MK.hex()[:8].upper() not in fp.replace(":", "") and len(fp) == 19


# ---------- in the running world ----------


def test_forged_frames_all_rejected():
    r = run_episode("deceptive", "fixed_hopping", duration_s=12)
    k = r.world.kpis()
    assert k["frames_forged"] > 20
    assert k["frames_forged_accepted"] == 0
    assert k["frames_rejected"] >= k["frames_forged"]


def test_security_tests_in_world():
    w = run_episode(None, "aegis", duration_s=2).world
    res = {t: w.security_test(t) for t in ("legit", "tamper", "spoof", "replay", "eavesdrop")}
    assert res["legit"]["accepted"]
    assert not any(res[t]["accepted"] for t in ("tamper", "spoof", "replay", "eavesdrop"))
    assert "tag" in res["tamper"]["reason"] and "tag" in res["spoof"]["reason"] and "replay" in res["replay"]["reason"]
    for r in res.values():
        assert len(r["header_hex"]) == 20 and len(r["ciphertext_hex"]) == 96


def test_decisions_travel_as_authenticated_control_frames():
    r = run_episode("random", "aegis", duration_s=8)
    assert r.world.auth_syncs >= len([d for d in r.decisions if d["action"] != "ignore"]) > 0


def test_epoch_rollover_drops_nothing():
    r = run_episode("follower", "aegis", duration_s=64, jam_at_s=50)
    k = r.world.kpis()
    assert k["key_epoch"] == 1 and k["frames_rejected"] == 0 and r.delivery_pct > 95
