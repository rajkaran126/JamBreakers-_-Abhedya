"""Radio constants and link-budget physics shared by the simulation, the baselines and the AI.

Band: 8 channels, 10 MHz apart, 2410-2480 MHz. The receiver digitises the whole 80 MHz band
(2405-2485 MHz) at 80 Msps, so a 128-point FFT gives 625 kHz bins, 16 per channel.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import erfc

# ---------- band and FFT ----------
N_CH = 8
CH_SPACING_HZ = 10e6
F_FIRST_HZ = 2410e6
CHANNELS_HZ = F_FIRST_HZ + CH_SPACING_HZ * np.arange(N_CH)
FS = 80e6                                   # receiver sample rate (whole band)
F_CENTER_HZ = F_FIRST_HZ + CH_SPACING_HZ * (N_CH - 1) / 2   # 2445 MHz
NFFT = 128
BIN_HZ = FS / NFFT                           # 625 kHz
BINS_PER_CH = NFFT // N_CH                   # 16


def channel_offset_hz(ch: int) -> float:
    """Baseband offset of a channel centre from the receiver centre."""
    return float(CHANNELS_HZ[ch] - F_CENTER_HZ)


# ---------- waveform ----------
SYMBOL_RATE = 2e6                            # QPSK 2 Msym/s
RRC_ALPHA = 0.35
SIG_BW_HZ = SYMBOL_RATE * (1 + RRC_ALPHA)    # 2.7 MHz occupied
NARROW_JAM_BW_HZ = 5e6                       # a narrowband noise jammer covers ~half a channel

# ---------- timing ----------
SLOT_S = 0.010                               # TDMA radio slot
WINDOW_S = 0.3e-3                            # spectrogram window the CNN sees
WINDOW_ROWS = 12                             # time rows per window (25 us each)
FFTS_PER_ROW = 4                             # Welch averaging per row
WINDOW_SAMPLES = WINDOW_ROWS * FFTS_PER_ROW * NFFT   # 6144 samples per window

# ---------- link budget ----------
THERMAL_DBM_HZ = -174.0
NOISE_FIGURE_DB = 6.0
NOISE_INBAND_DBM = THERMAL_DBM_HZ + 10 * math.log10(SIG_BW_HZ) + NOISE_FIGURE_DB   # ~ -103.7 dBm
NOISE_BAND_DBM = THERMAL_DBM_HZ + 10 * math.log10(FS) + NOISE_FIGURE_DB            # whole 80 MHz
PL_D0_DB = 20 * math.log10(4 * math.pi * 1.0 * F_CENTER_HZ / 3e8)                 # FSPL at 1 m ~ 40.2 dB
PL_EXPONENT_AIR = 2.2                        # link with a drone (mostly line of sight)
PL_EXPONENT_GROUND = 2.9                     # ground to ground
RICIAN_K_DB_AIR = 9.0
RICIAN_K_DB_GROUND = 3.0
TX_POWER_DBM = 27.0                          # 0.5 W tactical radio
POWER_STEP_DB = 3.0
POWER_CAP_DB = 9.0                           # max boost over nominal
CODING_GAIN_DB = 5.0                         # rate-1/2 convolutional code
PACKET_BITS = (10 + 32 + 16) * 8             # 10 B header + 32 B telemetry + 16 B GCM tag
BUILDING_LOSS_DB = 22.0
HILL_LOSS_DB = 18.0


def path_loss_db(d_m: np.ndarray | float, exponent: np.ndarray | float) -> np.ndarray:
    """Log-distance path loss with a 1 m free-space reference."""
    d = np.maximum(np.asarray(d_m, dtype=float), 1.0)
    return PL_D0_DB + 10.0 * np.asarray(exponent) * np.log10(d)


def rician_gain_db(rng: np.random.Generator, k_db: np.ndarray | float, size) -> np.ndarray:
    """Power gain |h|^2 in dB of a unit-mean Rician channel (block fading, one draw per slot)."""
    k = 10 ** (np.asarray(k_db, dtype=float) / 10)
    los = np.sqrt(k / (k + 1))
    sig = np.sqrt(1 / (2 * (k + 1)))
    h = los + sig * (rng.standard_normal(size) + 1j * rng.standard_normal(size))
    return 10 * np.log10(np.maximum(np.abs(h) ** 2, 1e-6))


MOD_EBN0_DB = {"QPSK": -3.0, "BPSK": 0.0, "BPSK_R2": 3.0}
MOD_RATE = {"QPSK": 1.0, "BPSK": 0.5, "BPSK_R2": 0.25}     # data rate relative to QPSK


def ber(sinr_db: np.ndarray, modulation: str) -> np.ndarray:
    """Coded bit error rate. QPSK: Eb/N0 = SINR - 3 dB. BPSK at half the bit rate: Eb/N0 = SINR.
    BPSK_R2 (survival mode): BPSK with every bit sent twice, a quarter of the QPSK rate: Eb/N0 = SINR + 3 dB."""
    eb_n0_db = np.asarray(sinr_db, dtype=float) + CODING_GAIN_DB + MOD_EBN0_DB.get(modulation, 0.0)
    g = 10 ** (eb_n0_db / 10)
    return 0.5 * erfc(np.sqrt(g))


def packet_delivery(sinr_db: np.ndarray, modulation: str) -> np.ndarray:
    """Probability a 58-byte packet arrives intact."""
    return np.power(1.0 - np.clip(ber(sinr_db, modulation), 0, 0.5), PACKET_BITS)


def dbm_to_mw(dbm):
    return np.power(10.0, np.asarray(dbm, dtype=float) / 10.0)


def mw_to_dbm(mw):
    return 10.0 * np.log10(np.maximum(np.asarray(mw, dtype=float), 1e-30))


# ---------- obstacles ----------
def segment_hits_box(p0: np.ndarray, p1: np.ndarray, center_xy, size_xyz) -> bool:
    """True if the 3D segment p0->p1 passes through an axis-aligned box standing on the ground.
    Slab method. size = [width (x), depth (y), height (z)]."""
    lo = np.array([center_xy[0] - size_xyz[0] / 2, center_xy[1] - size_xyz[1] / 2, 0.0])
    hi = np.array([center_xy[0] + size_xyz[0] / 2, center_xy[1] + size_xyz[1] / 2, size_xyz[2]])
    d = p1 - p0
    t0, t1 = 0.0, 1.0
    for a in range(3):
        if abs(d[a]) < 1e-9:
            if p0[a] < lo[a] or p0[a] > hi[a]:
                return False
            continue
        ta, tb = (lo[a] - p0[a]) / d[a], (hi[a] - p0[a]) / d[a]
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


def obstacle_loss_many(p0, p1, obstacles) -> np.ndarray:
    """Vectorised obstacle_loss_db for M segments p0[m] -> p1[m] at once (same slab method, same result)."""
    p0, p1 = np.asarray(p0, float).reshape(-1, 3), np.asarray(p1, float).reshape(-1, 3)
    if not obstacles or len(p0) == 0:
        return np.zeros(len(p0))
    c = np.array([[o["pos"][0], o["pos"][1]] for o in obstacles], float)
    sz = np.array([o["size"] for o in obstacles], float)
    lo = np.column_stack([c[:, 0] - sz[:, 0] / 2, c[:, 1] - sz[:, 1] / 2, np.zeros(len(c))])
    hi = np.column_stack([c[:, 0] + sz[:, 0] / 2, c[:, 1] + sz[:, 1] / 2, sz[:, 2]])
    loss = np.array([o["loss_db"] for o in obstacles], float)
    d = p1 - p0
    t0 = np.zeros((len(p0), len(c)))
    t1 = np.ones_like(t0)
    hit = np.ones_like(t0, dtype=bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        for a in range(3):
            da, pa = d[:, a:a + 1], p0[:, a:a + 1]
            small = np.abs(da) < 1e-9
            hit &= np.where(small, (pa >= lo[None, :, a]) & (pa <= hi[None, :, a]), True)
            ta, tb = (lo[None, :, a] - pa) / da, (hi[None, :, a] - pa) / da
            t0 = np.where(small, t0, np.maximum(t0, np.minimum(ta, tb)))
            t1 = np.where(small, t1, np.minimum(t1, np.maximum(ta, tb)))
    hit &= t0 <= t1
    return (hit * loss[None, :]).sum(axis=1)


def obstacle_loss_db(p0, p1, obstacles) -> float:
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    loss = 0.0
    for ob in obstacles:
        if segment_hits_box(p0, p1, ob["pos"], ob["size"]):
            loss += ob["loss_db"]
    return loss
