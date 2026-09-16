#!/usr/bin/env python3
"""Run the pinned upstream worker on CPU with scripted HTTP inference and mock tools.

Only heavyweight import/schema helpers are substituted. The complete worker class,
generation loop, HTTP request method, scoring and token reconciler execute unchanged.
This does not test Qwen tokenization, model inference, multiprocessing or vLLM itself.
"""
import argparse
import ast
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from types import ModuleType, SimpleNamespace
import urllib.request

from browser_training.environment import BrowserToolEnv
from browser_training.attention_compat import ORIGINAL_SHA256

COMMIT = "a04ffd337108285002df29d9ae73ef7e855e03f1"
SOURCE_URL = f"https://raw.githubusercontent.com/huggingface/trl/{COMMIT}/trl/experimental/async_grpo/async_rollout_worker.py"
SOURCE_SHA256 = "70222b24533ce8cc56061cc355b0358eaea7cbda4461a7df75e75f5fbec6b5d1"


class ScriptTokenizer:
    response_template = "scripted-json"
    eos_token_id = 0
    pad_token_id = 0

    def apply_chat_template(self, messages, **kwargs):
        return encode("".join(json.dumps(m, separators=(",", ":")) + "\n" for m in messages))


def encode(text):
    return list(text.encode())


def load_worker(path, *, policy_reservations=False):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(urllib.request.urlopen(SOURCE_URL, timeout=30).read())
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Worker source hash differs from the audited commit")
    if policy_reservations:
        from browser_training.policy_compat import patched_source
        raw = patched_source("async_rollout_worker.py", raw.decode()).encode()
    tree = ast.parse(raw)
    # Keep every function/class body intact, including __init__ and real HTTP I/O.
    tree.body = [n for n in tree.body if not (
        isinstance(n, ast.ImportFrom) and (n.level or n.module.split(".")[0] in
                                         {"accelerate", "datasets", "transformers"}))]
    module = ModuleType("audited_upstream_worker")
    sys.modules[module.__name__] = module
    module.__dict__.update({"Dataset": list, "PreTrainedTokenizerBase": object,
        "get_logger": logging.getLogger, "_SUPPORTS_RESPONSE_TEMPLATE": True,
        "add_response_schema": lambda t: t, "get_training_chat_template": lambda t: None,
        "is_chat_template_prefix_preserving": lambda t: True,
        "parse_response": lambda tokenizer, ids, **kw: json.loads(bytes(ids)),
        "is_vllm_available": lambda: False, "get_callable_name": lambda f: f.__name__,
        "print_prompt_completions_sample": lambda **kw: None})
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def retention_and_staleness():
    """Execute upstream sync/queue methods with fake transport/storage, never weights."""
    path = Path(".cache/upstream/async_grpo_trainer.py")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = SOURCE_URL.replace("async_rollout_worker.py", "async_grpo_trainer.py")
        path.write_bytes(urllib.request.urlopen(url, timeout=30).read())
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == ORIGINAL_SHA256
    tree = ast.parse(source)
    selected = []
    for class_name, method_name, name in (("AsyncGRPOTrainer", "_sync_weight_lora", "SyncProbe"),
                                         ("RolloutQueueDataset", "__iter__", "QueueProbe")):
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
        selected.append(ast.ClassDef(name=name, bases=[], keywords=[], body=[method], decorator_list=[]))
    namespace = {"os": os, "time": time, "shutil": shutil, "queue": queue,
                 "logger": logging.getLogger(__name__),
                 "save_lora_adapter": lambda model, accelerator, name, path: Path(path).mkdir()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
                 "<upstream-sync-and-queue-methods>", "exec"), namespace)
    loaded, unloaded = {"trl-policy-v1"}, []
    def unload(name):
        loaded.remove(name)
        unloaded.append(name)
    with tempfile.TemporaryDirectory() as directory:
        probe = namespace["SyncProbe"]()
        probe.model_version, probe.model = 1, None
        probe._lora_dir, probe._lora_name, probe._adapter_name = directory, "trl-policy", "default"
        probe.args = SimpleNamespace(max_staleness=2)
        probe.accelerator = SimpleNamespace(is_main_process=True, unwrap_model=lambda m: m,
                                            wait_for_everyone=lambda: None)
        probe.vllm_client = SimpleNamespace(pause=lambda: None, resume=lambda: None,
            load_lora_adapter=lambda name, path: loaded.add(name), unload_lora_adapter=unload)
        probe.rollout_worker = SimpleNamespace(update_model_version=lambda version: None)
        for _ in range(3):
            probe._sync_weight_lora(time.time())
        assert probe.model_version == 4 and unloaded == ["trl-policy-v1"]
    dataset = namespace["QueueProbe"]()
    dataset.queue, dataset.wait_s = queue.Queue(), 0.0
    dataset.poll_interval_s, dataset.max_staleness = 0.1, 2
    dataset.model_version_fn = lambda: 4
    dataset.metrics = defaultdict(list)
    dataset._trace_log_interval = 8
    for version in (1, 2):
        dataset.queue.put(SimpleNamespace(model_version=version, enqueued_at=None, input_ids=[version],
            completion_mask=[1], old_log_probs=[-0.25], advantage=0.0, group_id=0, metrics={}))
    accepted = next(iter(dataset))
    assert accepted["input_ids"] == [2] and dataset.metrics["sample/dropped_stale_total"] == [1.0]
    return {"scope": "unchanged sync/queue methods; mock vLLM client; no weights/GPU",
        "max_staleness": 2, "published_version": 4, "unloaded": unloaded,
        "remaining_adapters": sorted(loaded), "queue_drops_lag_3": True,
        "queue_accepts_lag_2": True,
        "active_episode_retention": "Sync has no active-episode reference check; a future v1-pinned turn would name an unloaded adapter"}


async def scenario(worker, *, update_version, invalid_action=False, environment_factory=BrowserToolEnv,
                   choose_action=None):
    import aiohttp
    from aiohttp import web
    version = SimpleNamespace(value=1)
    stop = asyncio.Event()
    requests = []
    finals = 0

    async def completion(request):
        nonlocal finals
        payload = await request.json()
        messages = [json.loads(line) for line in bytes(payload["prompt"]).decode().splitlines()]
        turn = sum(m["role"] == "assistant" for m in messages)
        requests.append({"model": payload["model"], "turn": turn})
        if turn < 2 and not (invalid_action and turn == 1):
            action = "subscribe()" if invalid_action else ("click('1')" if turn == 0 else "fill('2', 'yes')")
            if choose_action is not None:
                action = choose_action(messages, turn, invalid_action)
            message = {"role": "assistant", "content": "", "tool_calls": [{"type": "function",
                "function": {"name": "browser_action", "arguments": {"action": action}}}]}
        else:
            message = {"role": "assistant", "content": "done"}
            finals += 1
            if finals == 2:
                stop.set()
        ids = encode(json.dumps(message, separators=(",", ":")) + "\n")
        if update_version:
            version.value = 2
        return web.json_response({"choices": [{"token_ids": ids,
            "logprobs": {"token_logprobs": [-0.25] * len(ids)}}]})

    app = web.Application()
    app.router.add_post("/v1/completions", completion)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    loop = worker._AsyncRolloutLoop(model_name="mock", dataset=[{"task": "mock", "seed": 42}],
        reward_funcs=[], processing_class=ScriptTokenizer(), rollout_buffer=queue.Queue(),
        model_version_value=version, heartbeat_value=SimpleNamespace(value=0),
        failed_event=None, exception_info_queue=queue.Queue(), metrics_queue=queue.Queue(),
        environment_factory=environment_factory, num_generations=2, max_inflight_tasks=2,
        lora_name="trl-policy", vllm_server_url=f"http://127.0.0.1:{port}",
        max_tokens=512, max_tool_calling_iterations=3)
    loop._loop.close()
    loop._loop = asyncio.get_running_loop()
    try:
        async with aiohttp.ClientSession() as session:
            loop.session = session
            await asyncio.wait_for(loop._generate_loop(stop), timeout=30)
        group = loop._groups_to_score.get_nowait()
        assert group is not None and len(group.completions) == 2
        samples = await loop._score_group(group)
        assert len(samples) == 2
        expected_reward = 0.0 if invalid_action else 1.0
        assert all(s.metrics["reward"] == expected_reward for s in samples)
        for sample, generated in zip(samples, group.completions_ids, strict=True):
            assert len(sample.input_ids) == len(sample.completion_mask) == len(sample.old_log_probs)
            assert [t for t, m in zip(sample.input_ids, sample.completion_mask) if m] == generated
            assert all(lp == (-0.25 if m else 0.0) for lp, m in
                       zip(sample.old_log_probs, sample.completion_mask))
        assert all(env._backend is None for env in loop._environment_pool[None])
        return {"requests": requests, "group_version": group.model_version,
            "sample_versions": [s.model_version for s in samples],
            "reward": expected_reward, "rows": len(samples),
            "generated_tokens": sum(map(len, group.completions_ids)),
            "observation_tokens_masked": True, "logprobs_aligned": True,
            "environment_resources_closed": True,
            "policy_immutable": all(r["model"] == f"trl-policy-v{group.model_version}" for r in requests)}
    finally:
        for pool in loop._environment_pool.values():
            for env in pool:
                env._close()
        await runner.cleanup()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=Path(".cache/upstream/async_rollout_worker.py"))
    p.add_argument("--output", type=Path, default=Path("research/rollout-validation.json"))
    args = p.parse_args()
    worker = load_worker(args.source)
    stable = asyncio.run(scenario(worker, update_version=False))
    failure = asyncio.run(scenario(worker, update_version=False, invalid_action=True))
    changing = asyncio.run(scenario(worker, update_version=True))
    assert stable["policy_immutable"] and failure["policy_immutable"]
    # This assertion records a known defect, NOT a passing RL readiness check.
    assert not changing["policy_immutable"], "Upstream behavior changed; re-audit the blocker"
    report = {"source": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "scope": "unchanged full worker class; scripted tokenizer; local HTTP inference; no trainer/GPU",
        "stable_policy": stable, "failed_task": failure, "forced_policy_update": changing,
        "retention_and_staleness": retention_and_staleness(), "rl_ready": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
