import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from browser_training.policy_sessions import (
    PolicyRegistry, PolicyCancelled, PolicyUnsafe, drain, generate_reserved,
    request_model, reserved_request, evict_idle,
)


def registry():
    state = PolicyRegistry(max_staleness=2)
    state.publish(1)
    return state


def test_group_reserves_policy_for_late_starting_siblings():
    state = registry()
    assert state.acquire_group(10) == 1
    assert state.start_episode(10, "first") == 1
    state.finish_episode("first")
    state.publish(2)
    assert state.start_episode(10, "later") == 1
    assert state.acquire_group(11) == 2
    assert state.start_episode(11, "new") == 2
    state.finish_episode("later")
    state.finish_episode("new")
    assert state.release_group(10) is None
    assert state.release_group(11) is None


def test_stale_episode_blocks_eviction_until_request_and_group_drain():
    state = registry()
    state.acquire_group(10)
    state.start_episode(10, "episode")
    state.begin_request("episode")
    for version in (2, 3, 4):
        state.publish(version)
    assert state.claim_evictions() == []
    with pytest.raises(PolicyCancelled, match="staleness"):
        state.begin_request("episode")
    with pytest.raises(PolicyUnsafe, match="outstanding"):
        state.finish_episode("episode")
    with pytest.raises(PolicyUnsafe, match="active episodes"):
        state.release_group(10)
    state.end_request("episode")
    state.finish_episode("episode")
    assert state.claim_evictions() == []  # group may still have unscheduled siblings
    assert state.release_group(10) == "staleness"
    assert state.claim_evictions() == [1]
    assert state.claim_evictions() == []  # only one caller can claim unloading
    state.confirm_eviction(1)


def test_publication_and_acquisition_are_atomic_under_contention():
    # Either reservation linearizes before publication (v1, retained) or after (v2).
    for _ in range(40):
        state = registry()
        barrier = threading.Barrier(2)
        def acquire():
            barrier.wait()
            return state.acquire_group(1)
        def publish():
            barrier.wait()
            state.publish(2)
        with ThreadPoolExecutor(2) as pool:
            a, p = pool.submit(acquire), pool.submit(publish)
            version = a.result()
            p.result()
        assert version in (1, 2)
        assert state.start_episode(1, "episode") == version
        state.publish(3)
        state.publish(4)
        assert version not in state.claim_evictions()


def test_unknown_inference_and_capacity_fail_closed():
    state = registry()
    state.acquire_group(1)
    for version in (2, 3, 4):
        state.publish(version)
    with pytest.raises(PolicyUnsafe, match="capacity"):
        state.check_capacity()
    state.fail("worker lost")
    for action in (state.claim_evictions, state.check_capacity, lambda: state.acquire_group(2)):
        with pytest.raises(PolicyUnsafe, match="worker lost"):
            action()


def test_harness_context_propagation_and_pinning():
    from contextvars import copy_context
    async def scenario():
        state = registry()
        state.acquire_group(1)
        models = []
        loop = SimpleNamespace(policy_registry=state, lora_name="policy", request_timeout=1)
        async def post(*args, **kwargs):
            assert kwargs["max_retries"] == 1
            return {"ok": True}
        loop._post = post
        async def generate(*args, **kwargs):
            models.append(request_model(loop))
            state.publish(2)
            def threaded_turn():
                models.append(request_model(loop))
            with ThreadPoolExecutor(1) as pool:
                await asyncio.get_running_loop().run_in_executor(pool, copy_context().run, threaded_turn)
            await reserved_request(loop, {})
            return ([], [1], ["sequence"], 0, 0, 1)
        loop._generate_one = generate
        await generate_reserved(loop, [], tool_dict={}, tools=[], group_id=1)
        assert models == ["policy-v1", "policy-v1"]
        assert state.snapshot()["episodes"] == {}
        assert state.release_group(1) is None
    asyncio.run(scenario())


def test_cancellation_waits_for_http_response_before_releasing_episode():
    async def scenario():
        state = registry()
        state.acquire_group(1)
        started, respond = asyncio.Event(), asyncio.Event()
        loop = SimpleNamespace(policy_registry=state, lora_name="policy", request_timeout=1)
        async def post(*args, **kwargs):
            started.set()
            await respond.wait()
            return {}
        loop._post = post
        async def generate(*args, **kwargs):
            await reserved_request(loop, {})
            return ([], [1], ["sequence"], 0, 0, 1)
        loop._generate_one = generate
        task = asyncio.create_task(generate_reserved(loop, [], tool_dict={}, tools=[], group_id=1))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # repeated cancellation must not bypass draining
        for version in (2, 3, 4): state.publish(version)
        assert state.claim_evictions() == []
        assert state.snapshot()["episodes"]
        respond.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not state.snapshot()["episodes"]
        assert state.release_group(1)
        assert state.claim_evictions() == [1]
    asyncio.run(scenario())


def test_timeout_retains_adapter_even_after_local_episode_cleanup():
    async def scenario():
        state = registry()
        state.acquire_group(1)
        loop = SimpleNamespace(policy_registry=state, lora_name="policy", request_timeout=1)
        async def post(*args, **kwargs): raise TimeoutError("injected")
        loop._post = post
        async def generate(*args, **kwargs): return await reserved_request(loop, {})
        loop._generate_one = generate
        with pytest.raises(PolicyUnsafe):
            await generate_reserved(loop, [], tool_dict={}, tools=[], group_id=1)
        state.release_group(1)
        with pytest.raises(PolicyUnsafe, match="uncertain"):
            state.claim_evictions()
        assert 1 in state.snapshot()["versions"]
    asyncio.run(scenario())


def test_native_eviction_keeps_files_until_reservations_release(tmp_path):
    state = registry()
    state.acquire_group(1)
    folder = tmp_path / "policy-v1"
    folder.mkdir()
    unloaded = []
    trainer = SimpleNamespace(rollout_worker=SimpleNamespace(policy_registry=state),
        vllm_client=SimpleNamespace(unload_lora_adapter=unloaded.append), _lora_name="policy", _lora_dir=tmp_path)
    for version in (2, 3, 4): state.publish(version)
    evict_idle(trainer)
    assert folder.exists() and unloaded == []
    state.release_group(1)
    evict_idle(trainer)
    assert not folder.exists() and unloaded == ["policy-v1"]


def test_source_patch_hash_guards_and_attention_composition():
    from browser_training import attention_compat, policy_compat
    root = Path(__file__).resolve().parents[1] / ".cache/upstream"
    if not root.exists():
        pytest.skip("Cached upstream sources absent; run source audit first")
    for name in policy_compat.HASHES:
        source = (root / name).read_text()
        patched = policy_compat.patched_source(name, source)
        compile(patched, name, "exec")
        assert policy_compat.patched_source(name, patched) == patched
        assert policy_compat.restore_source(name, patched) == source
        with pytest.raises(ValueError, match="Unknown"):
            policy_compat.patched_source(name, patched + "\n# drift\n")
        before, after = policy_compat.EDITS[name][0]
        with pytest.raises(ValueError, match="Partial"):
            policy_compat.patched_source(name, patched.replace(after, before))
        if name == "async_grpo_trainer.py":
            both = attention_compat.patched_source(patched)
            assert both == policy_compat.patched_source(name, attention_compat.patched_source(source))
            assert attention_compat.is_patched(both)


def test_policy_events_are_durable_and_identify_episode_version(tmp_path):
    import json
    state = PolicyRegistry()
    path = tmp_path / "run/policy-events.jsonl"
    state.configure(2, str(path))
    state.publish(1)
    state.acquire_group(3)
    state.start_episode(3, "session-123")
    state.begin_request("session-123")
    state.end_request("session-123")
    state.finish_episode("session-123")
    state.release_group(3)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["seq"] for r in rows] == list(range(1, 8))
    assert rows[2]["episode_id"] == "session-123" and rows[2]["version"] == 1


def test_crashed_worker_prevents_further_publication():
    from browser_training.policy_sessions import prepare_sync
    state = registry()
    trainer = SimpleNamespace(accelerator=SimpleNamespace(is_main_process=True, num_processes=1),
        rollout_worker=SimpleNamespace(policy_registry=state, _process=SimpleNamespace(exitcode=-9)))
    with pytest.raises(PolicyUnsafe, match="exited"):
        prepare_sync(trainer)
    with pytest.raises(PolicyUnsafe, match="exited"):
        state.publish(2)


def test_unload_failure_quarantines_adapter_without_deleting_files(tmp_path):
    state = registry()
    for version in (2, 3, 4): state.publish(version)
    folder = tmp_path / "policy-v1"
    folder.mkdir()
    def failed_unload(name): raise TimeoutError("injected unload failure")
    trainer = SimpleNamespace(rollout_worker=SimpleNamespace(policy_registry=state),
        vllm_client=SimpleNamespace(unload_lora_adapter=failed_unload), _lora_name="policy", _lora_dir=tmp_path)
    with pytest.raises(TimeoutError): evict_idle(trainer)
    assert folder.exists()
    with pytest.raises(PolicyUnsafe, match="eviction failed"):
        state.claim_evictions()
