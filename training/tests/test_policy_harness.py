"""Run patched upstream harness code without CUDA imports (browser environment).

Only import/schema helpers are substituted. Spawn/native package integration is
separately exercised by scripts/validate_policy_sessions.py.
"""
import asyncio
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("openenv.core.harness")
pytest.importorskip("aiohttp")
from openenv.core.harness import VerifyResult
from browser_training.policy_sessions import PolicyRegistry, generate_reserved

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_rollout_worker import load_worker, ScriptTokenizer
from validate_harness_worker import load_harness


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.chdir(ROOT)
    worker = load_worker(Path(".cache/upstream/async_rollout_worker.py"), policy_reservations=True)
    return load_harness(worker, policy_reservations=True)


def make_loop(harness, factory, adapter, registry):
    loop = harness._HarnessRolloutLoop(harness_session_factory=factory, harness_adapter=adapter,
        model_name="mock", dataset=[{"prompt": [{"role": "user", "content": "mock"}]}],
        reward_funcs=[], processing_class=ScriptTokenizer(), rollout_buffer=queue.Queue(),
        model_version_value=SimpleNamespace(value=1), heartbeat_value=SimpleNamespace(value=0), failed_event=None,
        exception_info_queue=queue.Queue(), metrics_queue=queue.Queue(), num_generations=2,
        max_inflight_tasks=2, lora_name="policy", policy_registry=registry,
        max_tokens=16, max_tool_calling_iterations=3, request_timeout=1)
    loop._loop.close()
    loop._loop = asyncio.get_running_loop()
    return loop


def test_failed_factory_invalidates_whole_group_and_releases_reservation(harness):
    class Factory:
        def create(self, *args, **kwargs): raise RuntimeError("injected creation failure")
    async def scenario():
        registry = PolicyRegistry(2)
        registry.publish(1)
        registry.acquire_group(1)
        loop = make_loop(harness, Factory(), object(), registry)
        try:
            result = await generate_reserved(loop, [], tool_dict={}, tools=[], group_id=1)
            assert result == loop._EMPTY_ROLLOUT
            assert not registry.snapshot()["episodes"]
            assert registry.release_group(1) == "empty_or_failed_episode"
            # A group invalidated by one failed episode must never train on just
            # the successful siblings. The guard executes before reward callbacks.
            assert await loop._score_group(SimpleNamespace(policy_cancelled="failed")) == []
        finally:
            loop._session_pool.shutdown(wait=True)
    asyncio.run(scenario())


def test_stop_during_factory_creation_closes_late_session(harness):
    entered, proceed, closed = threading.Event(), threading.Event(), threading.Event()
    class Session:
        def close(self): closed.set()
    class Factory:
        def create(self, *args, **kwargs):
            entered.set()
            assert proceed.wait(2)
            return Session()
    class Adapter:
        def run_white_box(self, *args): raise AssertionError("Stopped session must not start inference")
    async def scenario():
        registry = PolicyRegistry(2)
        registry.publish(1)
        registry.acquire_group(1)
        loop = make_loop(harness, Factory(), Adapter(), registry)
        task = asyncio.create_task(generate_reserved(loop, [], tool_dict={}, tools=[], group_id=1))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            loop._stop_event.set()
            task.cancel()
            await asyncio.sleep(0)
            assert registry.snapshot()["episodes"]  # pool thread still owns its lease
            proceed.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert closed.is_set() and not loop._live_sessions
            assert not registry.snapshot()["episodes"]
            assert registry.release_group(1)
        finally:
            proceed.set()
            await asyncio.to_thread(loop._session_pool.shutdown, wait=True)
    asyncio.run(scenario())
