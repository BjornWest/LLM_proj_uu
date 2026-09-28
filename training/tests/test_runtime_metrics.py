import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.monitored_harness import MonitoredSession, unavailable


TASK = dict(task_id="mock", task_family="fixture", task_template="no-subscription",
            harness_revision="h1", verifier_revision="v1", environment_revision="e1",
            tokenizer_revision="qwen-pinned", split="rl_train")
GOOD = dict(status="completed", goal_completed=True, constraints_satisfied=True,
            unauthorized_effect=False, reward=1.0)


def make(tmp_path, name="run", **kwargs):
    return RuntimeMetrics(tmp_path / name, run_id="stable", synthetic=True, tasks=[TASK], **kwargs)


def begin(monitor, episode, group=0, version=3):
    return monitor.begin(native_group_id=group, episode_id=episode, policy_version=version, group_size=2)


def checkpoint(tmp_path, monitor):
    folder = tmp_path / "checkpoint-2"
    folder.mkdir()
    (folder / "rollout_state.json").write_text(json.dumps(dict(prompt_index=0, model_version=3)))
    monitor.checkpoint(folder)
    return folder


def test_group_task_is_shared_even_when_policy_publishes_between_siblings(tmp_path):
    monitor = make(tmp_path)
    first = begin(monitor, "a")
    monitor.finish("a", GOOD, generated_tokens=7)
    # Another group sees a new policy; a sibling retains its own reserved version.
    begin(monitor, "other", group=1, version=4)
    second = begin(monitor, "b")
    assert first == second
    monitor.finish("b", GOOD, generated_tokens=9)
    value = monitor.emit_snapshot()
    assert value["curriculum"]["all"]["draws"] == 2
    assert value["cohorts"]["rl_train"]["all"]["metrics"]["episodes"]["value"] == 2
    assert first["group_id"] not in monitor.members


def test_checkpoint_restores_evidence_cancels_inflight_and_namespaces_ids(tmp_path):
    monitor = make(tmp_path)
    old = begin(monitor, "a")
    monitor.finish("a", GOOD)
    begin(monitor, "inflight")
    folder = checkpoint(tmp_path, monitor)
    # Post-checkpoint progress must not leak into the restored snapshot.
    monitor.finish("inflight", GOOD)
    restored = make(tmp_path, "resumed", resume=folder)
    events = [r["event"] for r in restored.ledger.records()]
    cancelled = next(e for e in events if e["id"] == "finish-inflight")
    assert cancelled["payload"]["status"] == "cancelled"
    assert cancelled["payload"]["reward"] is None
    new = begin(restored, "new", version=4)
    assert new["group_id"] != old["group_id"]
    assert restored.sampler.distribution["evidence"]["fixture"]["groups"] == 0
    assert not monitor.active


def test_restore_rejects_changed_native_state_and_pool(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    folder = checkpoint(tmp_path, monitor)
    with pytest.raises(ValueError, match="config/pool"):
        RuntimeMetrics(tmp_path / "bad-pool", run_id="stable", synthetic=True,
                       tasks=[{**TASK, "verifier_revision": "different"}], resume=folder)
    (folder / "rollout_state.json").write_text(json.dumps(dict(prompt_index=99, model_version=3)))
    with pytest.raises(ValueError, match="differs"):
        make(tmp_path, "bad-state", resume=folder)


def test_log_has_actual_policy_version_and_no_inferred_admission(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    monitor.finish("a", GOOD)
    monitor.log(dict(step=20, wall_time=100, loss=0.2), policy_version=3)
    value = monitor.emit_snapshot()
    assert value["telemetry"]["rl/loss"]["policy_version"] == 3
    m = value["cohorts"]["rl_train"]["all"]["metrics"]
    assert m["pending_admission"]["value"] == 1
    assert m["admitted"]["value"] == 0


def test_stop_close_does_not_record_before_inference_drains(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    closed = []
    session = MonitoredSession(SimpleNamespace(close=lambda: closed.append(True)), monitor, "a", None)
    session.running = True
    session.close()
    assert len(closed) == 1 and "a" in monitor.active
    session.tokens = 12
    session.running = False
    session.close()
    session.close()
    e = monitor.ledger.event("finish-a")["payload"]
    assert e["status"] == "cancelled" and e["generated_tokens"] == 12
    assert len(closed) == 1


def test_close_failure_remains_infrastructure_error(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    def broken():
        raise RuntimeError("close failed")
    session = MonitoredSession(SimpleNamespace(close=broken), monitor, "a", None)
    session.outcome = GOOD
    with pytest.raises(RuntimeError):
        session.close()
    assert monitor.ledger.event("finish-a")["payload"]["status"] == "infra_error"


def test_checkpoint_rejects_modified_active_episode_metadata(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    folder = checkpoint(tmp_path, monitor)
    path = folder / "monitoring/state.json"
    state = json.loads(path.read_text())
    state["active"]["a"]["member"] = 1
    path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="state checksum"):
        make(tmp_path, "broken", resume=folder)


def test_finished_native_group_id_cannot_be_reused(tmp_path):
    monitor = make(tmp_path)
    begin(monitor, "a")
    begin(monitor, "b")
    monitor.finish("a", GOOD)
    monitor.finish("b", GOOD)
    with pytest.raises(ValueError, match="reused"):
        begin(monitor, "c")


def test_persistence_failure_cannot_be_swallowed_by_native_close_handler():
    import asyncio
    from browser_training.policy_sessions import PolicyRegistry, PolicyUnsafe, generate_reserved, episode_id
    from browser_training.monitored_harness import MonitoredSessionFactory
    class BrokenMonitor:
        def begin(self, **kwargs):
            return dict(task_id="mock", seed=42)
        def finish(self, *args, **kwargs):
            raise RuntimeError("disk unavailable")
    async def scenario():
        registry = PolicyRegistry(2)
        registry.publish(1)
        registry.acquire_group(0)
        async def generate(prompt, **kwargs):
            factory = MonitoredSessionFactory(SimpleNamespace(create=lambda *a, **kw: SimpleNamespace(close=lambda: None)),
                                              BrokenMonitor(), group_size=2, extractor=None)
            session = factory.create(prompt, episode_id=episode_id())
            try:
                session.close()
            except Exception:
                pass  # Match native _run_session's close-error handler.
            return ([], [1], [object()], 0, 0, 1)
        loop = SimpleNamespace(policy_registry=registry, _generate_one=generate)
        with pytest.raises(PolicyUnsafe, match="persistence failed"):
            await generate_reserved(loop, [], tool_dict={}, tools=[], group_id=0)
        assert registry.snapshot()["fault"] and not registry.snapshot()["episodes"]
    asyncio.run(scenario())
