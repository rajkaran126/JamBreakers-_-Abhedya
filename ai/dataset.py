"""Labelled spectrogram windows for the 7-class CNN.

Two sources, as the build plan's lessons learned demand:
  synthetic  emitters with random power, channel, timing and fading, built directly
  live       windows captured from the running simulation (random jammer, position, power, seed,
             defender), labelled with the jammer that was actually on the air

Without the live windows, accuracy on the running world dropped to ~70 % in our earlier test.
A follower looks like a single narrowband block in any one window, so it is labelled 'random';
the defender recognises it from its behaviour over time instead.

    python -m ai.dataset --out ai/data --synthetic 2400 --live 900
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from sim.jammers import DEFAULT_POWER_DBM, make_jammer
from sim.phy import EmitterSpec, NumpyPhy
from sim.radio import FS, N_CH, NARROW_JAM_BW_HZ, WINDOW_ROWS, channel_offset_hz
from sim.world import SimWorld

from .features import CLASSES, normalize

LIVE_LABEL = {"barrage": "barrage", "random": "random", "sweep": "sweep", "reactive": "reactive",
              "deceptive": "deceptive", "accidental": "accidental", "follower": "random"}
# total received power a jammer needs at the receiver to be visible in the window (>= ~8 dB per bin)
MIN_VISIBLE_DBM = {"barrage": -84.0, "sweep": -95.0, "accidental": -94.0}


# ---------- synthetic ----------
def _own(rng, ch):
    if rng.random() < 0.12:
        return []
    return [EmitterSpec("qpsk", float(rng.uniform(-100, -55)), channel_offset_hz(ch), k_db=float(rng.uniform(2, 10)))]


def synthetic_window(cls: str, rng: np.random.Generator, phy) -> np.ndarray:
    ch = int(rng.integers(N_CH))
    em = _own(rng, ch)
    t0 = float(rng.uniform(0, 1))
    if cls == "barrage":
        em.append(EmitterSpec("noise", float(rng.uniform(-84, -35)), 0.0, FS * 0.97))
    elif cls == "random":
        k = int(rng.choice([1, 2, 3], p=[0.4, 0.25, 0.35]))
        p = float(rng.uniform(-90, -45))
        for c in rng.choice(N_CH, k, replace=False):
            em.append(EmitterSpec("noise", p - 10 * np.log10(k) + float(rng.normal(0, 1.5)), channel_offset_hz(int(c)), NARROW_JAM_BW_HZ))
    elif cls == "sweep":
        period = float(rng.uniform(0.8e-3, 2.0e-3))
        em.append(EmitterSpec("chirp", float(rng.uniform(-92, -40)), chirp_f0_hz=float(rng.uniform(-FS / 2, FS / 2)),
                              chirp_rate_hz_s=FS / period))
    elif cls == "reactive":
        if not em:
            em = [EmitterSpec("qpsk", float(rng.uniform(-95, -60)), channel_offset_hz(ch), k_db=6.0)]
        gate = np.zeros(WINDOW_ROWS)
        gate[int(rng.integers(2, 6)):] = 1
        em.append(EmitterSpec("noise", float(rng.uniform(-90, -45)), channel_offset_hz(ch), NARROW_JAM_BW_HZ, gate=gate))
    elif cls == "deceptive":
        pattern = np.array([1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1], dtype=float)
        gate = np.roll(pattern, int(rng.integers(0, 5)))
        off = float(rng.choice([-1, 1])) * float(rng.uniform(0.8e6, 1.3e6))
        em.append(EmitterSpec("qpsk", float(rng.uniform(-90, -45)), channel_offset_hz(ch) + off, gate=gate))
    elif cls == "accidental":
        c = ch if rng.random() < 0.6 else int(rng.integers(N_CH))
        a = int(rng.integers(0, 8))
        gate = np.zeros(WINDOW_ROWS)
        gate[a:min(WINDOW_ROWS, a + int(rng.integers(2, 6)))] = 1
        em.append(EmitterSpec("ofdm", float(rng.uniform(-92, -55)), channel_offset_hz(c), 4e6, gate=gate))
    return phy.synthesize(em, rng, t0=t0)


def make_synthetic(n_per_class: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    phy = NumpyPhy()
    X, y = [], []
    for k, cls in enumerate(CLASSES):
        for _ in range(n_per_class):
            X.append(normalize(synthetic_window(cls, rng, phy)))
            y.append(k)
    return np.stack(X), np.array(y)


# ---------- live capture from the running world ----------
def _jammer_on_air(jm) -> bool:
    if jm.type == "reactive":
        return bool(getattr(jm, "hit", False))
    if jm.type == "deceptive":
        return bool(jm.forging)
    return bool(jm.channels)


def capture_live(n_per_class: int, seed: int, every: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Run many short worlds and keep windows where the label is unambiguous."""
    rng = np.random.default_rng(seed)
    phy = NumpyPhy()
    need = {c: n_per_class for c in CLASSES}
    X, y = [], []
    types = list(LIVE_LABEL)
    run = 0
    while any(v > 0 for v in need.values()):
        run += 1
        jt = types[run % len(types)] if need[LIVE_LABEL[types[run % len(types)]]] > 0 else None
        if jt is None and need["clean"] <= 0:
            continue
        w = SimWorld("main", int(rng.integers(1 << 30)), str(rng.choice(["none", "energy", "fixed_hopping"])), phy)
        w.run_slots(int(rng.integers(10, 60)))
        jm = None
        if jt is not None:
            pos = (float(rng.uniform(-250, 1150)), float(rng.uniform(-350, 850)))
            jm = make_jammer("J1", jt, pos, DEFAULT_POWER_DBM[jt] + float(rng.uniform(-8, 4)), None)
            w.launch(jm)
        for step in range(400):
            w.step_slot()
            if step % every:
                continue
            node = str(rng.choice([n.id for n in w.net.nodes]))
            ni = w.net.index[node]
            if jm is None:
                if need["clean"] > 0:
                    X.append(normalize(w.sense(node)))
                    y.append(0)
                    need["clean"] -= 1
                if step > 120:
                    break
                continue
            label = LIVE_LABEL[jt]
            if need[label] <= 0:
                break
            if not _jammer_on_air(jm) or not w.jammers:
                continue
            rx = jm.power_dbm + w.net.jam_gain_db[0, ni]
            if rx < MIN_VISIBLE_DBM.get(jt, -92.0):
                continue
            X.append(normalize(w.sense(node)))
            y.append(CLASSES.index(label))
            need[label] -= 1
    return np.stack(X), np.array(y)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ai/data")
    ap.add_argument("--synthetic", type=int, default=2400, help="windows per class")
    ap.add_argument("--live", type=int, default=900, help="live windows per class (training)")
    ap.add_argument("--test", type=int, default=120, help="live windows per class (held-out test, other seeds)")
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    Xs, ys = make_synthetic(a.synthetic, a.seed)
    print(f"synthetic {Xs.shape} in {time.time() - t:.0f}s")
    t = time.time()
    Xl, yl = capture_live(a.live, a.seed + 1)
    print(f"live train {Xl.shape} in {time.time() - t:.0f}s")
    t = time.time()
    Xt, yt = capture_live(a.test, a.seed + 999)
    print(f"live test {Xt.shape} in {time.time() - t:.0f}s")
    np.savez_compressed(out / "windows.npz", Xs=Xs, ys=ys, Xl=Xl, yl=yl, Xt=Xt, yt=yt)
    print("saved", out / "windows.npz")


if __name__ == "__main__":
    main()
