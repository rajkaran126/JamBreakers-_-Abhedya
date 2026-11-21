"""Jammer localisation from RSSI.

Each node reports the hostile power its wideband receiver measures. Model:
    rssi_i = P0 - 10 * n_i * log10(d_i),   d_i = distance from node i to the jammer (x, y, z=2 m)
Unknowns x, y, P0. n_i is known per node (2.2 for airborne nodes, 2.9 on the ground). Solve by least squares: a coarse grid search for a start
point, then Gauss-Newton. NLOS pass: a node whose residual is over 8 dB (blocked by a building
or hill, so it reads low) is dropped and the fit repeated. The 95 % uncertainty radius comes from
the covariance of the fit. An estimate is published only if the radius is under 300 m.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

N_EXP = 2.6                      # default when per-node exponents are not given
MEAS_SIGMA2_MIN = 4.0            # at least 2 dB of measurement noise after averaging
NLOS_DB = 8.0
PUBLISH_RADIUS_M = 300.0
ANNOUNCE_RADIUS_M = 150.0
CHI2_2DOF_95 = 5.991
JAMMER_Z = 2.0


@dataclass
class Estimate:
    x: float
    y: float
    radius_m: float
    used: int
    dropped: int


def _model(theta: np.ndarray, P: np.ndarray, n: np.ndarray) -> np.ndarray:
    x, y, p0 = theta
    d = np.sqrt((P[:, 0] - x) ** 2 + (P[:, 1] - y) ** 2 + (P[:, 2] - JAMMER_Z) ** 2)
    return p0 - 10 * n * np.log10(np.maximum(d, 1.0))


def _jacobian(theta: np.ndarray, P: np.ndarray, n: np.ndarray) -> np.ndarray:
    x, y, _ = theta
    dx, dy = x - P[:, 0], y - P[:, 1]
    d2 = np.maximum(dx ** 2 + dy ** 2 + (P[:, 2] - JAMMER_Z) ** 2, 1.0)
    k = -10 * n / np.log(10) / d2
    return np.column_stack([k * dx, k * dy, np.ones(len(P))])


def _fit(P: np.ndarray, r: np.ndarray, bounds, n: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # coarse grid: P0 has a closed form for each candidate (mean of r + path loss)
    gx = np.linspace(bounds[0][0], bounds[0][1], 31)
    gy = np.linspace(bounds[1][0], bounds[1][1], 27)
    X, Y = np.meshgrid(gx, gy)
    cand = np.column_stack([X.ravel(), Y.ravel()])
    d = np.sqrt((P[None, :, 0] - cand[:, None, 0]) ** 2 + (P[None, :, 1] - cand[:, None, 1]) ** 2 + (P[None, :, 2] - JAMMER_Z) ** 2)
    pl = 10 * n[None, :] * np.log10(np.maximum(d, 1.0))
    p0 = (r[None] + pl).mean(axis=1)
    sse = ((r[None] - (p0[:, None] - pl)) ** 2).sum(axis=1)
    b = int(np.argmin(sse))
    theta = np.array([cand[b, 0], cand[b, 1], p0[b]])
    for _ in range(25):                                     # Gauss-Newton with damping
        res = r - _model(theta, P, n)
        J = _jacobian(theta, P, n)
        step, *_ = np.linalg.lstsq(J.T @ J + 1e-3 * np.eye(3), J.T @ res, rcond=None)
        theta = theta + step
        if np.linalg.norm(step[:2]) < 0.5:
            break
    return theta, r - _model(theta, P, n)


def locate(positions: np.ndarray, rssi_dbm: np.ndarray, bounds, exponents: Optional[np.ndarray] = None) -> Optional[Estimate]:
    """positions: (N, 3) node positions; rssi_dbm: (N,) hostile power each node measured;
    exponents: (N,) path-loss exponent per node (default 2.6)."""
    P, r = np.asarray(positions, float), np.asarray(rssi_dbm, float)
    n = np.full(len(P), N_EXP) if exponents is None else np.asarray(exponents, float)
    if len(P) < 4:
        return None
    keep = np.ones(len(P), bool)
    theta, res = _fit(P, r, bounds, n)
    for _ in range(2):                                      # NLOS rejection: leave-one-out
        if keep.sum() <= 4 or np.max(np.abs(res)) <= NLOS_DB / 2:
            break
        idx = np.flatnonzero(keep)
        best = None
        for drop in idx:
            k2 = keep.copy()
            k2[drop] = False
            th2, res2 = _fit(P[k2], r[k2], bounds, n[k2])
            left_out = r[drop] - _model(th2, P[drop:drop + 1], n[drop:drop + 1])[0]
            score = float(res2 @ res2)
            if abs(left_out) > NLOS_DB and (best is None or score < best[0]):
                best = (score, k2, th2, res2)
        if best is None or best[0] > 0.5 * float(res @ res):
            break                                           # dropping a node does not clearly help
        _, keep, theta, res = best
    J = _jacobian(theta, P[keep], n[keep])
    dof = max(int(keep.sum()) - 3, 1)
    sigma2 = max(float(res @ res) / dof, MEAS_SIGMA2_MIN)
    try:
        cov = sigma2 * np.linalg.inv(J.T @ J)[:2, :2]
        radius = float(np.sqrt(CHI2_2DOF_95 * np.max(np.linalg.eigvalsh(cov))))
    except np.linalg.LinAlgError:
        return None
    if not np.isfinite(radius):
        return None
    return Estimate(float(theta[0]), float(theta[1]), radius, int(keep.sum()), int((~keep).sum()))
