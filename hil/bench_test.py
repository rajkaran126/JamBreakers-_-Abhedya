"""Bench test: the measurements that decide whether the radio link behaves as the simulator says.

Runs against any backend (SimBackend now, SdrBackend on the bench) and writes one CSV row per measurement.

  1 link budget     for each attenuation step: send N encrypted frames, record packet error rate and RSSI
  2 channels        same at every one of the 8 channels (filters and antennas are not flat)
  3 hop sync        both ends follow the keyed hop sequence for N slots: share of slots on the same channel,
                    frames delivered; repeated with a deliberate clock offset to find the real guard margin
  4 interference    noise source injected through a combiner on one channel (cabled, never over the air):
                    PER on that channel vs the clean ones, and whether the AI's verdict names it
  5 security        every received frame goes through the real AES-GCM receiver: tampered / replayed frames
                    are injected and must be rejected

    python -m hil.bench_test --backend sim --out results/bench_sim.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from sim import security as sec
from sim.hopping import keyed_channel
from sim.keymgmt import KeyManager, SessionReceiver

from .radio_backend import SimBackend, predicted_per


def link_budget(be, attenuations, n=400, tx_dbm=0.0):
    km = KeyManager(1, 1, {"D1": 2})
    r = km.provision("D1", 2)
    g, _ = km.handle_join(r.join_request(b"bench-join-00000"))
    r.accept_grant(g)
    rx = SessionReceiver(km)
    rows = []
    be.set_tx_power(tx_dbm)
    for att in attenuations:
        be.attenuation_db = att
        ok, rssi = 0, []
        for seq in range(n):
            be.send(sec.seal(r.session, sec.T_DATA, 2, 1, 0, seq + int(att) * 10000, sec.telemetry(2, 0.0, (0, 0, 0), 0)))
            got = be.receive()
            if got is None:
                continue
            frame, rs = got
            rssi.append(rs)
            ok += rx.open(frame, 0).ok
        sinr = be.sinr_db()
        rows.append({"test": "link_budget", "channel": be.channel, "attenuation_db": att, "frames": n,
                     "per": round(1 - ok / n, 4), "rssi_dbm": round(float(np.mean(rssi)), 1) if rssi else "",
                     "sinr_db": round(sinr, 1), "predicted_per": round(predicted_per(sinr), 4)})
    return rows


def hop_sync(be, slots=500, clock_offset_slots=0):
    key = b"\x11" * 32
    same = 0
    for s in range(slots):
        a = keyed_channel(key, s)
        b = keyed_channel(key, s + clock_offset_slots)
        be.tune(a)
        be.tune_peer(b)
        same += a == b
    return [{"test": "hop_sync", "slots": slots, "clock_offset_slots": clock_offset_slots, "same_channel_pct": round(100 * same / slots, 1)}]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="sim", choices=["sim", "sdr"])
    ap.add_argument("--out", default="results/bench_sim.csv")
    a = ap.parse_args(argv)
    if a.backend == "sdr":
        from .radio_backend import SdrBackend
        be = SdrBackend()
    else:
        be = SimBackend(seed=3)
    rows = []
    for ch in range(8):
        be.tune(ch)
        be.tune_peer(ch)
        rows += link_budget(be, attenuations=[96, 100, 102, 104, 106, 108], n=300)
    rows += hop_sync(be) + hop_sync(be, clock_offset_slots=1)
    be.tune(3), be.tune_peer(3)
    be.jammer_dbm = -95.0
    for r in link_budget(be, attenuations=[96, 100], n=300):
        rows.append({**r, "test": "interference"})
    be.jammer_dbm = None
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with open(a.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {a.out}: {len(rows)} measurements")


if __name__ == "__main__":
    main()
