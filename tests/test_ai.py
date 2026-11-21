"""Phase 2 tests: CNN, Grad-CAM, localisation, the AEGIS defender against every jammer."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ai.cnn import CNN, WEIGHTS
from ai.dataset import capture_live
from ai.features import CLASSES, NOISE_BIN_DBM
from ai.localize import locate
from sim.experiment import run_episode

REPORT = Path(WEIGHTS).parent / "report.json"


def test_weights_and_report_exist():
    assert WEIGHTS.exists(), "run python -m ai.dataset && python -m ai.train"
    rep = json.loads(REPORT.read_text())
    assert rep["accuracy"] > 0.90                         # the deck promises > 90 % on live windows
    assert rep["live_test_windows"] >= 500
    assert rep["numpy_inference_ms_median"] < 20


def test_cnn_on_fresh_live_windows():
    """New seed, never seen in training or in the report's test set."""
    X, y = capture_live(25, seed=424242)
    cnn = CNN()
    pred = np.array([CLASSES.index(cnn.predict(x * 20 + NOISE_BIN_DBM)["class"]) for x in X])
    assert (pred == y).mean() > 0.85


def test_numpy_matches_pytorch():
    torch = pytest.importorskip("torch")
    from ai.train import Net
    d = np.load(WEIGHTS)
    net = Net()
    sd = {"c1.weight": d["c1.w"], "c1.bias": d["c1.b"], "c2.weight": d["c2.w"], "c2.bias": d["c2.b"],
          "c3.weight": d["c3.w"], "c3.bias": d["c3.b"], "fc.weight": d["fc.w"], "fc.bias": d["fc.b"]}
    net.load_state_dict({k: torch.tensor(v) for k, v in sd.items()})
    x = np.random.default_rng(0).normal(0.3, 0.5, (12, 128)).astype(np.float32)
    cnn = CNN()
    z_np = cnn.logits_from(cnn.features(x))
    z_t = net(torch.tensor(x[None, None])).detach().numpy()[0]
    assert np.allclose(z_np, z_t, atol=1e-3)


def test_gradcam_shape_and_range():
    w = np.full((12, 128), NOISE_BIN_DBM)
    w[:, 40:48] += 30                                     # a narrowband block
    r = CNN().predict(w, with_cam=True)
    assert r["cam"].shape == (12, 32) and r["cam"].min() >= 0 and r["cam"].max() <= 1


def test_localize_recovers_position_and_drops_nlos():
    rng = np.random.default_rng(1)
    P = np.column_stack([rng.uniform(-200, 1000, 7), rng.uniform(-300, 800, 7), rng.choice([2, 100], 7)])
    n = np.where(P[:, 2] > 50, 2.2, 2.9)
    truth = np.array([420.0, 260.0])
    d = np.sqrt(((P[:, :2] - truth) ** 2).sum(1) + (P[:, 2] - 2) ** 2)
    r = 30 - 10 * n * np.log10(d) - 40
    est = locate(P, r, ((-300, 1200), (-400, 900)), n)
    assert np.hypot(est.x - truth[0], est.y - truth[1]) < 5
    r_nlos = r.copy()
    r_nlos[0] -= 20                                       # one node behind a building
    est2 = locate(P, r_nlos, ((-300, 1200), (-400, 900)), n)
    assert est2.dropped >= 1 and np.hypot(est2.x - truth[0], est2.y - truth[1]) < 30


@pytest.mark.parametrize("jammer", ["barrage", "random", "sweep", "reactive", "deceptive", "accidental", "follower"])
def test_aegis_beats_fixed_hopping_and_keeps_80_percent(jammer):
    a = run_episode(jammer, "aegis", duration_s=10)
    f = run_episode(jammer, "fixed_hopping", duration_s=10)
    assert a.delivery_pct >= 80, f"{jammer}: {a.delivery_pct}%"
    assert a.delivery_pct > f.delivery_pct
    assert a.outage_ms < f.outage_ms or f.outage_ms == 0


def test_hop_latency_under_100ms():
    lat = [x for jt in ("random", "deceptive", "follower") for x in run_episode(jt, "aegis", duration_s=8).world.latencies]
    assert lat and np.median(lat) < 100


def test_per_class_responses():
    sweep = run_episode("sweep", "aegis", duration_s=6)
    assert any(d["action"] == "raise_power" for d in sweep.decisions) and sweep.hops == 0   # hold, don't thrash
    fol = run_episode("follower", "aegis", duration_s=6)
    assert any(d["action"] == "fast_hop" and "following" in d["reason"] for d in fol.decisions)
    assert fol.world.hop_mode == "keyed" and fol.world.anti_follow
    acc = run_episode("accidental", "aegis", duration_s=6)
    assert all(d["class"] in ("accidental", "clean") for d in acc.decisions)


def test_spectrum_message_carries_cnn_output():
    r = run_episode("random", "aegis", duration_s=3)
    msg = r.world.spectrum_msg()
    assert set(msg["probs"]) == set(CLASSES) and abs(sum(msg["probs"].values()) - 1) < 0.01
    assert msg["verdict"] in CLASSES
    if "gradcam" in msg:
        assert len(msg["gradcam"]) == 12 and len(msg["gradcam"][0]) == 32
