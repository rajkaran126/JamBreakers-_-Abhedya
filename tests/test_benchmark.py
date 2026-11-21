"""Phase 4 tests: seed-replayed benchmark, export, and the server's run_benchmark command."""
from __future__ import annotations

import csv
import json
import time

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from backend.app import create_app
from backend.config import Settings
from backend.protocol import load_schema
from sim.benchmark import JAMMERS, jammer_position, run_benchmark, run_one

VALIDATOR = Draft202012Validator(load_schema())


def test_same_job_same_result():
    job = ("random", "aegis", 3, 6.0, 1.0)
    a, b = run_one(job), run_one(job)
    assert a["delivery_pct"] == b["delivery_pct"] and a["latencies"] == b["latencies"]
    assert jammer_position(3, "random") == jammer_position(3, "random") != jammer_position(4, "random")


def test_benchmark_aegis_beats_fixed_on_every_jammer(tmp_path):
    res = run_benchmark(seed=7, seeds=1, duration_s=8.0, defenders=["fixed_hopping", "aegis"], workers=1, out_dir=tmp_path)
    for j in JAMMERS:
        a = next(r for r in res["rows"] if r["jammer"] == j and r["defender"] == "aegis")
        f = next(r for r in res["rows"] if r["jammer"] == j and r["defender"] == "fixed_hopping")
        if j == "accidental":                         # friendly interference: mild for everyone, a tie is fine
            assert a["delivery_pct"] >= f["delivery_pct"], j
        else:
            assert a["delivery_pct"] > f["delivery_pct"], j
        assert a["outage_ms"] <= f["outage_ms"], j
        assert a["forged_accepted"] == 0
    aegis = next(o for o in res["overall"] if o["defender"] == "aegis")
    assert aegis["wins_vs_fixed"] >= len(JAMMERS) - 1 and aegis["accuracy_pct"] > 85
    assert aegis["hop_latency_median_ms"] < 100
    # files for the slides
    latest = json.loads((tmp_path / "benchmark_latest.json").read_text())
    assert latest["rows"] == res["rows"]
    rows = list(csv.DictReader(open(tmp_path / "benchmark_latest.csv")))
    assert len(rows) == 2 * len(JAMMERS) and "hop_latency_p95_ms" in rows[0]


def test_server_runs_benchmark_in_background(monkeypatch, tmp_path):
    monkeypatch.setattr("sim.benchmark.RESULTS", tmp_path)
    monkeypatch.setenv("AEGIS_WORLD", "sim")
    with TestClient(create_app(Settings())) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "cmd", "id": "b1", "action": "run_benchmark", "quick": True, "duration_s": 4})
        seen_states, done, t0 = 0, None, time.time()
        while time.time() - t0 < 240:
            m = ws.receive_json()
            assert not list(VALIDATOR.iter_errors(m)), m.get("type")
            if m["type"] == "state":
                seen_states += 1                      # the live demo keeps ticking meanwhile
            if m["type"] == "benchmark" and m["status"] == "done":
                done = m
                break
        assert done is not None and seen_states > 20
        assert {r["defender"] for r in done["rows"]} == {"fixed_hopping", "aegis"}
        assert c.get("/api/benchmark/latest").status_code in (200, 404)
