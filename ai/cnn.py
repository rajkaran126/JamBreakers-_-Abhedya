"""The CNN in pure NumPy (serving), plus Grad-CAM. Weights come from ai/train.py as an .npz.

Architecture (input 1 x 12 x 128: time rows x frequency bins):
  conv 3x5, 16 ch, ReLU -> maxpool 1x2        -> 16 x 12 x 64
  conv 3x3, 32 ch, ReLU -> maxpool 1x2        -> 32 x 12 x 32
  conv 3x3, 48 ch, ReLU                       -> 48 x 12 x 32   (Grad-CAM layer: 12 time x 32 freq)
  global average pool -> linear 48 -> 7

With a global-average-pool + linear head, Grad-CAM's channel weights are exactly the linear layer's
row for the class (divided by H*W), so the heat map is computed in closed form, no autograd needed.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .features import CLASSES, normalize

WEIGHTS = Path(__file__).resolve().parent / "weights" / "cnn_v1.npz"


def conv2d(x: np.ndarray, w: np.ndarray, b: np.ndarray) -> np.ndarray:
    """'same' convolution. x: (C, H, W), w: (O, C, kh, kw)."""
    _, _, kh, kw = w.shape
    xp = np.pad(x, ((0, 0), (kh // 2, kh // 2), (kw // 2, kw // 2)))
    win = sliding_window_view(xp, (kh, kw), axis=(1, 2))          # (C, H, W, kh, kw)
    return np.einsum("chwij,ocij->ohw", win, w, optimize=True) + b[:, None, None]


def relu(x):
    return np.maximum(x, 0.0)


def pool_w2(x):
    c, h, w = x.shape
    return x[:, :, : w // 2 * 2].reshape(c, h, w // 2, 2).max(axis=-1)


class CNN:
    def __init__(self, path: Path | str = WEIGHTS):
        d = np.load(path)
        self.p = {k: d[k].astype(np.float32) for k in d.files if k not in ("classes", "meta")}
        self.classes = [str(c) for c in d["classes"]] if "classes" in d.files else CLASSES

    def features(self, x: np.ndarray) -> np.ndarray:
        p = self.p
        h = pool_w2(relu(conv2d(x[None], p["c1.w"], p["c1.b"])))
        h = pool_w2(relu(conv2d(h, p["c2.w"], p["c2.b"])))
        return relu(conv2d(h, p["c3.w"], p["c3.b"]))               # (48, 12, 32)

    def logits_from(self, a: np.ndarray) -> np.ndarray:
        return self.p["fc.w"] @ a.mean(axis=(1, 2)) + self.p["fc.b"]

    def predict(self, window_db: np.ndarray, with_cam: bool = False) -> dict:
        """window_db: (12, 128) dBm. Returns probs, class, confidence, optional 12x32 Grad-CAM, ms."""
        t0 = time.perf_counter()
        a = self.features(normalize(window_db))
        z = self.logits_from(a)
        pr = np.exp(z - z.max())
        pr /= pr.sum()
        k = int(np.argmax(pr))
        out = {"probs": pr, "class": self.classes[k], "confidence": float(pr[k]), "k": k,
               "emb": a.mean(axis=(1, 2))}                   # the fingerprint used by the open-set check (ai/ood.py)
        if with_cam:
            out["cam"] = self.gradcam(a, k)
        out["ms"] = (time.perf_counter() - t0) * 1000
        return out

    def gradcam(self, a: np.ndarray, k: int) -> np.ndarray:
        """ReLU(sum_c alpha_c * A_c), alpha_c = d logit_k / d A_c averaged = fc.w[k, c] / (H*W). Scaled to 0..1."""
        cam = relu(np.tensordot(self.p["fc.w"][k], a, axes=(0, 0)))
        # scale on the interior: the outermost columns carry zero-padding artefacts that would otherwise
        # dominate (a barrage must light up the whole band, not just its edge)
        m = cam[:, 1:-1].max()
        return np.clip(cam / m, 0.0, 1.0) if m > 0 else cam

    def predict_vote(self, windows: list[np.ndarray]) -> dict:
        """Average the probabilities of several consecutive windows (the 3-window vote)."""
        t0 = time.perf_counter()
        res = [self.predict(w) for w in windows]
        pr = np.mean([r["probs"] for r in res], axis=0)
        k = int(np.argmax(pr))
        return {"probs": pr, "class": self.classes[k], "confidence": float(pr[k]),
                "votes": [r["class"] for r in res], "embs": [r["emb"] for r in res], "ks": [r["k"] for r in res],
                "ms": (time.perf_counter() - t0) * 1000}


_shared: Optional[CNN] = None


def load_shared() -> Optional[CNN]:
    """One CNN for the whole server (None if weights are missing)."""
    global _shared
    if _shared is None and WEIGHTS.exists():
        _shared = CNN(WEIGHTS)
    return _shared
