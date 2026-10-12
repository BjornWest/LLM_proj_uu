import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from browser_training.packet_cloud import UPLOAD_FILES, bundle, choose_offer, parse_connection
from browser_training.vllm_speed import CASES, bench_command, server_command


@pytest.fixture
def options():
    return {"products": [
        {"id": "monthly", "name": "RTX PRO 6000 Blackwell Dynamic monthly", "pricePerHourCents": 0,
         "vramGb": 96, "poolIds": [1]},
        {"id": "hourly", "name": "RTX PRO 6000 Blackwell Dynamic", "pricePerHourCents": 66,
         "vramGb": 96, "poolIds": [2, 3]}],
        "pools": [{"id": "1", "available_gpus": 5, "price_per_hour": 0},
                  {"id": "2", "available_gpus": 0, "price_per_hour": 0},
                  {"id": "3", "available_gpus": 1, "price_per_hour": 0}]}


def test_hourly_offer_ignores_monthly_and_zero_pool_price(options):
    assert choose_offer(options)["hourly_usd"] == 0.66
    assert choose_offer(options)["pool_id"] == 3
    assert choose_offer(options)["product_id"] == "hourly"


@pytest.mark.parametrize("kwargs", [{"max_hourly": 0.50}, {"pool_id": 1}, {"pool_id": 2}])
def test_no_silent_price_or_pool_fallback(options, kwargs):
    with pytest.raises(RuntimeError):
        choose_offer(options, **kwargs)


@pytest.mark.parametrize("command", ["ssh -p 2222 root@gpu.example", "ssh root@gpu.example -p 2222"])
def test_parse_provider_connection(command):
    assert parse_connection(command) == ("root@gpu.example", 2222)


@pytest.mark.parametrize("command", ["ssh root@host;rm -rf /", "ssh -o ProxyCommand=evil root@host",
                                      "ssh root@host -p 0", "bash evil", "ssh root@host uname"])
def test_no_shell_execution_from_connection(command):
    with pytest.raises(ValueError):
        parse_connection(command)


def test_upload_allowlist_excludes_secrets_and_unrelated_work(tmp_path):
    assert "scripts/apply_vllm_cpu_kv_patch.py" in UPLOAD_FILES
    assert "patches/vllm028_mtp_cpu_offload.patch" in UPLOAD_FILES
    root = tmp_path / "root"
    root.mkdir()
    for relative in UPLOAD_FILES:
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("safe source")
    (root / ".env").write_text("PACKET_API_KEY=NEVER_UPLOAD_ME")
    (root / "private.txt").write_text("UNRELATED")
    dest = tmp_path / "upload.tar.gz"
    hashes = bundle(root, dest)
    with tarfile.open(dest) as archive:
        assert set(archive.getnames()) == set(UPLOAD_FILES)
        assert all(b"NEVER_UPLOAD_ME" not in archive.extractfile(member).read()
                   for member in archive.getmembers())
    assert all(len(v) == 64 for v in hashes.values())


def test_case_context_and_cache_accounting():
    cmd = server_command("vllm")
    context = int(cmd[cmd.index("--max-model-len") + 1])
    assert all(c.input_tokens + c.prefix_tokens + c.output_tokens <= context for c in CASES)
    cached = next(c for c in CASES if c.prefix_tokens)
    assert cached.input_tokens + cached.prefix_tokens == 8448
    command = bench_command("vllm", cached, output="results")
    assert "--save-detailed" in command and "/v1/completions" in command
    cold = bench_command("vllm", CASES[0], output="results")
    assert cold[cold.index("--num-warmups") + 1] == "0"
    assert cold[cold.index("--ready-check-timeout-sec") + 1] == "0"
    assert command[command.index("--num-warmups") + 1] == "1"
    assert "--enable-lora" not in cmd and "--weight-transfer-config" not in cmd


def launcher_module():
    path = Path(__file__).resolve().parents[1] / "scripts/packet_cloud.py"
    spec = importlib.util.spec_from_file_location("packet_launcher_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure", [RuntimeError("SSH failed"), KeyboardInterrupt()])
def test_allocation_cleanup_after_failure_or_interrupt(tmp_path, monkeypatch, failure):
    module = launcher_module()
    calls = []

    class FakeClient:
        def request(self, endpoint, method="GET", body=None):
            calls.append((endpoint, method, body))
            if method == "POST":
                return {"instance_id": "test-id"}
            if endpoint.endswith("/connection"):
                return {"connection": {"ssh_command": "ssh root@test.example"}}
            return {"instances": []}

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(type(failure)):
        module.run_instance(FakeClient(), {"pool_id": 3, "hourly_usd": 0.66},
                            argparse.Namespace(minutes=30, name="test", preset="baseline"), tmp_path, "hf-test")
    assert sum(method == "POST" for _, method, _ in calls) == 1
    assert ("/instances/test-id", "DELETE", None) in calls
    state = json.loads((tmp_path / "allocation.json").read_text())
    assert state["termination_confirmed"]
    assert "hf-test" not in (tmp_path / "allocation.json").read_text()


def test_ambiguous_allocation_not_retried(tmp_path):
    module = launcher_module()
    calls = []

    class FakeClient:
        def request(self, *args):
            calls.append(args)
            raise TimeoutError("reply lost")

    with pytest.raises(TimeoutError):
        module.run_instance(FakeClient(), {"pool_id": 3, "hourly_usd": 0.66},
                            argparse.Namespace(minutes=30, name="test", preset="baseline"), tmp_path, "")
    assert len(calls) == 1
    assert json.loads((tmp_path / "allocation.json").read_text())["allocation_outcome_unknown"]


def test_missing_execute_rejected_before_any_network():
    module = launcher_module()
    result = subprocess.run([str(Path(__import__('sys').executable)), str(module.__file__), "run"],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "needs --execute" in result.stderr
