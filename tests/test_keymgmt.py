"""Key management (sim/keymgmt.py): per-radio keys, nonce safety across reboots, revocation, late join."""
from __future__ import annotations

from sim import security as sec
from sim.keymgmt import KeyManager, SessionReceiver

MEMBERS = {"D1": 2, "D2": 3, "D3": 4}


def _net():
    km = KeyManager(7, 1, MEMBERS)
    radios = {n: km.provision(n, a) for n, a in MEMBERS.items()}
    for n, r in radios.items():
        grant, why = km.handle_join(r.join_request(n.encode().ljust(16, b"x")))
        assert r.accept_grant(grant) == "installed", why
    return km, radios, SessionReceiver(km)


def _frame(r, seq, epoch=0):
    return sec.seal(r.session, sec.T_DATA, r.addr, 1, epoch, seq, sec.telemetry(r.addr, 0.0, (0, 0, 0), 0))


def test_every_radio_has_its_own_key_and_cannot_pose_as_another():
    km, radios, rx = _net()
    assert len({r.dk for r in radios.values()}) == 3
    assert rx.open(_frame(radios["D1"], 0), 0).ok
    d3 = radios["D3"]
    fake = sec.seal(d3.session, sec.T_DATA, radios["D1"].addr, 1, 0, 1, sec.telemetry(2, 0.0, (0, 0, 0), 9))
    res = rx.open(fake, 0)
    assert not res.ok and "D1's session key" in res.reason


def test_no_nonce_repeats_under_one_key_even_after_reboots():
    """(key, nonce) pairs over many frames, several radios and two reboots: all unique."""
    km, radios, rx = _net()
    seen = set()
    for boot in range(3):
        for r in radios.values():
            for seq in range(50):                       # the counter restarts at 0 after every reboot
                key_fp = r.session.fingerprint()
                pair = (key_fp, sec.nonce(r.addr, 0, seq))
                assert pair not in seen
                seen.add(pair)
                assert rx.open(_frame(r, seq), 0).ok
            r.reboot()
            grant, _ = km.handle_join(r.join_request(f"{r.name}{boot}".encode().ljust(16, b"y")))
            assert r.accept_grant(grant) == "installed"
    assert len(seen) == 3 * 3 * 50


def test_join_needs_the_device_key_and_grants_need_the_cp_signature():
    km, radios, _ = _net()
    req = bytearray(radios["D2"].join_request(b"z" * 16))
    req[-1] ^= 1
    grant, why = km.handle_join(bytes(req))
    assert grant is None and "wrong device key" in why
    good, _ = km.handle_join(radios["D2"].join_request(b"q" * 16))
    forged = bytearray(good)
    forged[5] ^= 1                                       # alter the signature
    assert "not signed" in radios["D2"].accept_grant(bytes(forged))
    assert "not for this radio" in radios["D3"].accept_grant(good)


def test_revoked_radio_is_cut_off_and_loses_the_hop_pattern():
    km, radios, rx = _net()
    old_hop = radios["D3"].group.key("hop", 0)
    grants = km.revoke("D3")
    assert set(grants) == {"D1", "D2"}
    for n, g in grants.items():
        assert radios[n].accept_grant(g) == "installed"
    assert not rx.open(_frame(radios["D3"], 99), 0).ok
    assert radios["D1"].group.key("hop", 0) == km.group.key("hop", 0) != old_hop
    assert rx.open(_frame(radios["D1"], 5), 0).ok      # the others keep working
    grant, why = km.handle_join(radios["D3"].join_request(b"r" * 16))
    assert grant is None and "revoked" in why


def test_a_new_radio_can_join_mid_mission():
    km, radios, rx = _net()
    km.revoke("D2")                                      # the group key has moved on
    late = km.provision("D5", 9)
    grant, why = km.handle_join(late.join_request(b"l" * 16))
    assert late.accept_grant(grant) == "installed", why
    assert late.generation == km.generation and late.group.key("hop", 3) == km.group.key("hop", 3)
    assert rx.open(_frame(late, 0), 0).ok


def test_orders_need_the_command_post_signature():
    from sim.phy import NumpyPhy
    from sim.world import SimWorld
    w = SimWorld("main", 7, "hybrid", NumpyPhy())
    frame, sig = w.control_frame(b"\x01" * 32)
    assert w.verify_control(frame, sig)[0]
    # a radio holding the group key can seal an order, but cannot sign it
    d3 = w.radios["D3"]
    fake = sec.seal(d3.group, sec.T_CONTROL, 1, sec.BROADCAST, w.epoch, 9, b"\x02" * 32)
    assert not w.verify_control(fake, sig)[0]
    for t in ("impersonate", "reboot", "capture"):
        r = w.security_test(t)
        assert r["accepted"] is (t == "reboot"), r
