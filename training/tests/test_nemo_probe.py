"""Local safety checks for the isolated experiment; never allocate Modal resources."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_requantization_control_handles_post_merge_range_growth():
    torch = pytest.importorskip("torch")
    spec = importlib.util.spec_from_file_location("nemo_fp8_control", ROOT / "scripts/nemo_fp8_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    base = torch.full((129, 257), 0.01)
    merged = base + torch.linspace(-0.2, 0.2, base.numel()).reshape(base.shape)
    old_scale = base.max() / 448
    # CPU builds can saturate where the tested CUDA cast returned NaN.
    # Either behavior is an invalid control when the old range is too small.
    stale = (merged / old_scale).to(torch.float8_e4m3fn).float() * old_scale
    assert not torch.isfinite(stale).all() or ((stale - merged).norm() / merged.norm()).item() > 0.5
    recovered = probe.blockwise_fp8_roundtrip(merged)
    assert recovered.shape == merged.shape
    assert torch.isfinite(recovered).all()
    assert ((recovered - merged).norm() / merged.norm()).item() < 0.04
    assert torch.equal(probe.blockwise_fp8_roundtrip(torch.zeros((128, 128))), torch.zeros((128, 128)))


def test_missing_mode_cannot_start_probe(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/nemo_fp8_probe.py"),
                             "--output", str(tmp_path / "report.json")], capture_output=True)
    assert result.returncode == 2
    assert not (tmp_path / "report.json").exists()


def test_expired_modal_probe_starts_nothing():
    pytest.importorskip("modal")
    spec = importlib.util.spec_from_file_location("modal_nemo_test", ROOT / "scripts/modal_nemo_fp8.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    with pytest.raises(TimeoutError, match="expired"):
        launcher.gpu_probe.get_raw_f()("expired", {}, 0)


def test_dry_run_is_bounded_and_needs_no_credentials():
    pytest.importorskip("modal")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/modal_nemo_fp8.py"), "--dry-run"],
                            capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    assert plan["gpu_count"] == 1
    assert plan["retries"] == 0
    assert plan["gpu_window_seconds"] == 600
    assert plan["function_timeout_seconds"] + plan["startup_timeout_seconds"] < 600
    assert plan["model_downloads"] is False
    assert "@sha256:" in plan["container"]


def test_inventory_from_different_image_is_rejected(tmp_path):
    pytest.importorskip("modal")
    (tmp_path / "plan.json").write_text(json.dumps({"container": "wrong-image"}))
    (tmp_path / "inventory.json").write_text(json.dumps({"python": "/some/python", "api_check": {"returncode": 0}}))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/modal_nemo_fp8.py"),
                             "--dry-run", "--prepared-inventory", str(tmp_path / "inventory.json")],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "exact container" in result.stderr


def test_completed_probe_evidence_survives_exit_timeout(tmp_path, monkeypatch):
    pytest.importorskip("modal")
    from browser_training import processes
    spec = importlib.util.spec_from_file_location("modal_nemo_timeout_test", ROOT / "scripts/modal_nemo_fp8.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    class LocalVolume:
        def reload(self):
            pass

        def commit(self):
            pass

    def completes_then_hangs(command, *args, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"status": "PASS", "cases": ["completed"]}))
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(launcher, "results", LocalVolume())
    monkeypatch.setattr(launcher, "Path", lambda value: tmp_path if value == "/results" else Path(value))
    monkeypatch.setattr(processes, "run_logged", completes_then_hangs)
    report = launcher.gpu_probe.get_raw_f()("test", {"python": "/unused"}, time.time() + 300, ("hybrid",), 240)
    assert report["status"] == "FAIL"
    assert report["stages"][0]["exit_code"] == -1
    assert report["stages"][0]["result"]["status"] == "PASS"
