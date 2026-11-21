"""Preprocessing shared by training (PyTorch) and serving (NumPy)."""
from __future__ import annotations

import numpy as np

from sim.radio import NFFT, NOISE_BAND_DBM

CLASSES = ["clean", "barrage", "random", "sweep", "reactive", "deceptive", "accidental"]
NOISE_BIN_DBM = float(NOISE_BAND_DBM - 10 * np.log10(NFFT))   # calibrated receiver floor per bin (~ -110 dBm)


def normalize(window_db: np.ndarray) -> np.ndarray:
    """(12, 128) dBm -> float32 'dB above the calibrated floor / 20', clipped. Keeps absolute level,
    so a barrage (whole band lifted) stays different from a quiet band."""
    x = (np.asarray(window_db, dtype=np.float32) - NOISE_BIN_DBM) / 20.0
    return np.clip(x, -0.5, 4.0).astype(np.float32)
