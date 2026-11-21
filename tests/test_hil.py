"""Hardware-in-the-loop kit: the bench scripts run on the simulator backend and the SDR backend refuses to pretend."""
import pytest

from hil import bench_test, compare
from hil.radio_backend import SdrBackend, SimBackend


def test_bench_dry_run_matches_model(tmp_path):
    out = tmp_path / "bench.csv"
    bench_test.main(["--backend", "sim", "--out", str(out)])
    r = compare.compare(str(out))
    assert r["rows"] == 48 and r["rms_per_error_as_is"] < 0.05


def test_hop_sync_offset_breaks_link():
    be = SimBackend()
    assert bench_test.hop_sync(be)[0]["same_channel_pct"] == 100.0
    assert bench_test.hop_sync(be, clock_offset_slots=1)[0]["same_channel_pct"] < 30


def test_sdr_backend_not_faked():
    with pytest.raises(NotImplementedError):
        SdrBackend()
