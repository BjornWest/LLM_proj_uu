import importlib.util
from pathlib import Path
import sys

import pytest


def launcher():
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("runpod_launcher_test", scripts / "runpod_cloud.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offers(community=None, secure=2.09):
    return {cloud: {"gpuTypes": [{"lowestPrice": {"uninterruptablePrice": rate,
                                                "stockStatus": "Low" if rate else None}}]}
            for cloud, rate in (("COMMUNITY", community), ("SECURE", secure))}


def test_live_community_stock_preferred_and_secure_fallback():
    m = launcher()
    assert m.choose_offer(offers(1.69))["cloud"] == "COMMUNITY"
    assert m.choose_offer(offers())["cloud"] == "SECURE"
    with pytest.raises(RuntimeError):
        m.choose_offer(offers(None, 2.11))


def test_connection_excludes_credentials_and_rejects_wrong_gpu(tmp_path):
    m = launcher()
    c = m.Client("fake-key")
    c.output, c.offer = tmp_path, {}
    pod = {"id": "testpod", "costPerHr": 2.106, "publicIp": "203.0.113.1",
           "portMappings": {"22": 12345}, "machine": {"gpuTypeId": m.GPU},
           "env": {"SECRET": "not-in-receipt"}}
    c.api = lambda *args, **kwargs: pod
    assert c.request("/instances/testpod/connection") == {
        "connection": {"ssh_command": "ssh -p 12345 root@203.0.113.1"}}
    assert "not-in-receipt" not in (tmp_path / "assigned-pod.json").read_text()
    pod["machine"]["gpuTypeId"] = "NVIDIA L40S"
    with pytest.raises(RuntimeError, match="differs"):
        c.request("/instances/testpod/connection")


def test_allocation_price_check_happens_after_id_recording_and_cleanup(tmp_path, monkeypatch):
    m = launcher()
    c = m.Client("fake")
    c.create_body, c.output, c.offer = {}, tmp_path, {"hourly_usd": 2.09, "pool_id": 0}
    calls = []

    def api(base, path, method="GET", body=None):
        calls.append((method, path))
        if method == "POST":
            return {"id": "testpod"}
        if method == "DELETE":
            return {}
        if path == "/pods":
            return []
        return {"costPerHr": 10}

    c.api = api
    import argparse
    args = argparse.Namespace(minutes=30, name="test", provider="Runpod", preset="baseline")
    with pytest.raises(RuntimeError, match="rate exceeds"):
        m.run_instance(c, c.offer, args, tmp_path, "")
    assert ("DELETE", "/pods/testpod") in calls
    import json
    receipt = json.loads((tmp_path / "allocation.json").read_text())
    assert receipt["instance_id"] == "testpod"
    assert receipt["termination_confirmed"]


@pytest.mark.parametrize("finish", [True, False])
def test_manual_session_keeps_pod_until_finish_or_deadline(tmp_path, monkeypatch, finish):
    import argparse
    import json
    import packet_cloud as lifecycle
    m = launcher()
    calls = []
    clock = [0.0]

    class FakeClient:
        def request(self, path, method="GET", body=None):
            calls.append((method, path))
            if method == "POST":
                return {"instance_id": "manualpod"}
            if path.endswith("/connection"):
                return {"connection": {"ssh_command": "ssh root@203.0.113.1"}}
            return {"instances": []}

    def sleep(seconds):
        assert not any(method == "DELETE" for method, _ in calls)
        assert (tmp_path / "connection.json").exists()
        clock[0] += seconds
        if finish:
            (tmp_path / "manual-finished.json").write_text('{"exit_code":0}')

    executed = []
    def command(argv, **kwargs):
        executed.append(argv)
        return __import__('subprocess').CompletedProcess(argv, 0)

    monkeypatch.setattr(lifecycle.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(lifecycle.time, "sleep", sleep)
    monkeypatch.setattr(lifecycle.subprocess, "run", command)
    args = argparse.Namespace(minutes=5, name="manual", preset="baseline", manual=True)
    if finish:
        m.run_instance(FakeClient(), {"pool_id": 0, "hourly_usd": 2.09}, args, tmp_path, "hf-private")
    else:
        with pytest.raises(TimeoutError, match="deadline"):
            m.run_instance(FakeClient(), {"pool_id": 0, "hourly_usd": 2.09}, args, tmp_path, "hf-private")
        assert clock[0] == 210  # reserve 90 seconds of the five-minute allowance
    assert ("DELETE", "/instances/manualpod") in calls
    assert json.loads((tmp_path / "allocation.json").read_text())["termination_confirmed"]
    assert "hf-private" not in (tmp_path / "connection.json").read_text()
    assert not any("packet_vllm_worker.sh" in str(argv) for argv in executed)
