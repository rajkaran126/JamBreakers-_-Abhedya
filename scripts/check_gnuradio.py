"""Check the GNU Radio receiver chain against the NumPy reference. Run with the radioconda Python:

    <radioconda>\\python.exe scripts\\check_gnuradio.py

It (1) builds the flowgraph, (2) compares per-channel power for every emitter type between the two
backends (they should agree within ~2 dB; both are random, so 20 windows are averaged), (3) times both,
and (4) runs the same 10 s attack with each backend and prints delivery. Exit code 0 = all good.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.phy import EmitterSpec, NumpyPhy  # noqa: E402
from sim.radio import BINS_PER_CH, FS, N_CH, channel_offset_hz  # noqa: E402

CASES = {
    "own QPSK only": [EmitterSpec("qpsk", -75, channel_offset_hz(2), k_db=9.0)],
    "barrage": [EmitterSpec("qpsk", -75, channel_offset_hz(2)), EmitterSpec("noise", -60, 0.0, FS * 0.97)],
    "narrowband": [EmitterSpec("qpsk", -75, channel_offset_hz(2)), EmitterSpec("noise", -65, channel_offset_hz(5), 5e6)],
    "sweep": [EmitterSpec("chirp", -62, chirp_f0_hz=-30e6, chirp_rate_hz_s=FS / 1.2e-3)],
    "ofdm burst": [EmitterSpec("ofdm", -70, channel_offset_hz(6), 4e6, gate=np.r_[np.zeros(4), np.ones(5), np.zeros(3)])],
}


def per_channel_db(phy, emitters, n=20, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    acc = np.zeros(N_CH)
    for _ in range(n):
        S = 10 ** (phy.synthesize(emitters, rng) / 10)
        acc += S.mean(axis=0).reshape(N_CH, BINS_PER_CH).sum(axis=1)
    return 10 * np.log10(acc / n)


def main() -> int:
    try:
        from sim.phy_gnuradio import GnuRadioPhy
        gr_phy = GnuRadioPhy()
    except Exception as exc:
        print(f"FAIL: GNU Radio backend did not start: {exc!r}")
        print("Run this with the radioconda Python, and check `python -c \"import gnuradio\"` works.")
        return 1
    np_phy = NumpyPhy()
    ok = True
    print(f"{'case':16s} {'max |diff| dB':>14s}   per-channel dBm (gnuradio)")
    for name, em in CASES.items():
        a, b = per_channel_db(np_phy, em), per_channel_db(gr_phy, em)
        diff = float(np.max(np.abs(a - b)))
        ok &= diff < 2.5
        print(f"{name:16s} {diff:14.2f}   {np.round(b, 1)}  {'OK' if diff < 2.5 else 'MISMATCH'}")

    for phy in (np_phy, gr_phy):
        rng = np.random.default_rng(0)
        t = time.perf_counter()
        for _ in range(20):
            phy.synthesize(CASES["barrage"], rng)
        print(f"{phy.name:9s} {1000 * (time.perf_counter() - t) / 20:6.1f} ms per window")

    from sim.experiment import run_episode
    for phy in (np_phy, gr_phy):
        r = run_episode("deceptive", "aegis", seed=7, duration_s=10, phy=phy)
        print(f"{phy.name:9s} deceptive jammer, defender {r.defender}: delivery {r.delivery_pct}%  hops {r.hops}")
    print("ALL GOOD" if ok else "CHECK THE MISMATCHES ABOVE")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
