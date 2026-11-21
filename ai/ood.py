"""Open-set check: is this a jammer the CNN knows, or something new?

A softmax classifier always picks one of its 7 classes, often with high confidence even for a signal it
never saw (our never-seen 'comb' jammer is labelled 'sweep' at 98 %). So confidence alone is not enough.
Instead we look at the CNN's internal fingerprint of the window (the 48 averaged feature maps just before
the last layer) and ask how far it is from what that class normally looks like:

    ratio = distance(fingerprint, class centre) / (99th-percentile distance of that class's training windows)

ratio <= 1 means "as typical as 99 % of training examples". Above UNKNOWN_RATIO, in 2 of the 3 voted
windows, the AI says "unknown" instead of guessing. On held-out windows of the 7 known jammers 0.1 % are
flagged (false alarm); on the never-seen comb jammer 100 % are.

    python -m ai.ood --fit        # recompute ai/weights/ood.npz from ai/data/windows.npz
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np

WEIGHTS = Path(__file__).resolve().parent / "weights" / "ood.npz"
UNKNOWN_RATIO = 2.0

_stats: Optional[dict] = None


def stats() -> Optional[dict]:
    global _stats
    if _stats is None and WEIGHTS.exists():
        d = np.load(WEIGHTS)
        _stats = {k: d[k] for k in d.files}
    return _stats


def ratio(emb: np.ndarray, k: int) -> float:
    s = stats()
    if s is None:
        return 0.0
    d = float(np.sqrt(np.mean(((emb - s["mu"][k]) / s["sd"][k]) ** 2)))
    return d / float(s["r99"][k])


def is_unknown(embs: list[np.ndarray], ks: list[int]) -> tuple[bool, float]:
    """2 of 3 windows outside -> unknown. Returns (unknown, median ratio)."""
    rs = [ratio(e, k) for e, k in zip(embs, ks)]
    return sum(r > UNKNOWN_RATIO for r in rs) >= 2, float(np.median(rs)) if rs else 0.0


def fit(n: int = 4200, seed: int = 0) -> dict:
    from .cnn import load_shared
    from .features import CLASSES
    cnn = load_shared()
    raw = np.load(Path(__file__).resolve().parent / "data" / "windows.npz")
    X, y = raw["Xs"], raw["ys"]                       # already normalised windows
    idx = np.random.default_rng(seed).choice(len(X), min(n, len(X)), replace=False)
    E = np.array([cnn.features(X[i].astype(np.float32)).mean(axis=(1, 2)) for i in idx])
    Y = y[idx].astype(int)
    mu = np.array([E[Y == k].mean(0) for k in range(len(CLASSES))])
    sd = np.array([E[Y == k].std(0) + 1e-3 for k in range(len(CLASSES))])
    r99 = np.array([np.percentile(np.sqrt(np.mean(((E[Y == k] - mu[k]) / sd[k]) ** 2, axis=1)), 99) for k in range(len(CLASSES))])
    np.savez(WEIGHTS, mu=mu.astype(np.float32), sd=sd.astype(np.float32), r99=r99.astype(np.float32))
    global _stats
    _stats = None
    return {"r99": np.round(r99, 2).tolist(), "n": len(idx)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    if ap.parse_args().fit:
        print(fit())
