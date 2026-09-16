#!/usr/bin/env python3
"""CPU execution of upstream TRL's full OpenEnv harness-worker class.

Real BrowserGym/OpenEnv sessions and local scripted HTTP inference. Runs both
synthetic tokenization and Qwen's real tokenizer/TRL parser. Heavy imports are
substituted as in validate_rollout_worker.py; no model or trainer is instantiated.
"""
import argparse
import ast
import asyncio
from functools import partial
import hashlib
import json
import logging
from pathlib import Path
import queue
import re
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import urllib.request

from browser_training.harness_bridge import TaskSelectingSessionFactory, MappingArgumentsHarnessAdapter
from validate_browser import browser_service, action_for
from validate_rollout_worker import COMMIT, ScriptTokenizer, load_worker

SHA = "35393ad97d321143dd187f38e48a63bf614e3e2a0a42f4c4aaade960ec186550"
URL = f"https://raw.githubusercontent.com/huggingface/trl/{COMMIT}/trl/experimental/async_grpo/openenv_harness.py"


def load_harness(worker, *, policy_reservations=False):
    path = Path(".cache/upstream/openenv_harness.py")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(urllib.request.urlopen(URL, timeout=30).read())
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    if policy_reservations:
        from browser_training.policy_compat import patched_source
        raw = patched_source("openenv_harness.py", raw.decode()).encode()
    tree = ast.parse(raw)
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and
                  (n.level or n.module == "accelerate.logging"))]
    module = ModuleType("audited_harness_worker")
    sys.modules[module.__name__] = module
    module.__dict__.update({name: getattr(worker, name) for name in
        ("AsyncRolloutWorker", "TurnRecord", "_AsyncRolloutLoop", "_chain_to_sequences", "parse_response")})
    module.get_logger = logging.getLogger
    exec(compile(tree, str(path), "exec"), module.__dict__)
    return module


def make_loop(harness, factory, adapter, version, url="http://127.0.0.1:1", tokenizer=None):
    loop = harness._HarnessRolloutLoop(harness_session_factory=factory, harness_adapter=adapter,
        model_name="mock", dataset=[{"prompt": [{"role": "user", "content": "mock"}]}],
        reward_funcs=[], processing_class=tokenizer or ScriptTokenizer(), rollout_buffer=queue.Queue(),
        model_version_value=version, heartbeat_value=SimpleNamespace(value=0), failed_event=None,
        exception_info_queue=queue.Queue(), metrics_queue=queue.Queue(), num_generations=2,
        max_inflight_tasks=2, lora_name="trl-policy", vllm_server_url=url,
        max_tokens=512, max_tool_calling_iterations=3, request_timeout=2,
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
    loop._loop.close()
    loop._loop = asyncio.get_running_loop()
    return loop


async def browser_scenario(harness, client_factory, *, update=False, tokenizer=None):
    import aiohttp
    from aiohttp import web
    from browsergym_env.harness import BrowserGymSessionFactory, build_browsergym_action_tool_call
    from openenv.core.harness import MCPHarnessAdapter
    from openenv.core.llm_client import LLMResponse
    requests = []
    version = SimpleNamespace(value=1)
    async def completion(request):
        payload = await request.json()
        if tokenizer is None:
            messages = [json.loads(line) for line in bytes(payload["prompt"]).decode().splitlines()]
            turn = sum(m["role"] == "assistant" for m in messages)
            observation = messages[-1]["content"]
            if messages[-1]["role"] == "tool":
                observation = json.loads(observation)["observation_text"]
        else:
            text = tokenizer.decode(payload["prompt"])
            turn = text.count("<|im_start|>assistant") - 1
            responses = re.findall(r"<tool_response>\s*(.*?)\s*</tool_response>", text, re.DOTALL)
            observation = json.loads(responses[-1])["observation_text"] if turn else text
        action = action_for([{"content": observation}], turn, False)
        message = LLMResponse(content="", tool_calls=[build_browsergym_action_tool_call(action)]).to_message_dict()
        if tokenizer is None:
            ids = list((json.dumps(message, separators=(",", ":")) + "\n").encode())
        else:
            call = build_browsergym_action_tool_call(action)
            content = "<tool_call>\n<function=" + call.name + ">\n"
            for name, value in call.args.items():
                content += f"<parameter={name}>\n{value}\n</parameter>\n"
            content += "</function>\n</tool_call><|im_end|>"
            ids = tokenizer.encode(content, add_special_tokens=False)
        requests.append({"model": payload["model"], "turn": turn, "tokens": len(ids)})
        if update:
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
    raw_factory = BrowserGymSessionFactory(client_factory, default_task="mock")
    selected = TaskSelectingSessionFactory(raw_factory, lambda prompt, seed: "mock")
    adapter = MappingArgumentsHarnessAdapter(MCPHarnessAdapter()) if tokenizer is not None else MCPHarnessAdapter()
    loop = make_loop(harness, selected, adapter, version, f"http://127.0.0.1:{port}", tokenizer)
    prompt = [{"role": "user", "content": "mock"}]
    try:
        # The direct factory receives a list as task_name and cannot create a task.
        if not update and tokenizer is None:
            loop._factory = raw_factory
            incompatible = await loop._generate_one(prompt, {}, [], group_id=0)
            assert incompatible == loop._EMPTY_ROLLOUT
            loop._factory = selected
        async with aiohttp.ClientSession() as session:
            loop.session = session
            results = await asyncio.wait_for(asyncio.gather(
                loop._generate_one(prompt, {}, [], group_id=0),
                loop._generate_one(prompt, {}, [], group_id=0)), timeout=30)
        for messages, ids, sequences, calls, failures, reward in results:
            assert reward == 1 and calls == 2 and failures == 0
            assert sum(sum(s.completion_mask) for s in sequences) == len(ids)
            assert all(lp == (-0.25 if m else 0.0) for s in sequences
                       for lp, m in zip(s.old_log_probs, s.completion_mask, strict=True))
        assert not loop._live_sessions
        names = {r["model"] for r in requests}
        assert names == ({"trl-policy-v1", "trl-policy-v2"} if update else {"trl-policy-v1"})
        return {"requests": requests, "rewards": [r[-1] for r in results],
            "tool_calls": [r[3] for r in results], "observations_masked": True,
            "all_generated_tokens_trained_once": True, "sessions_released": True,
            "policy_immutable": len(names) == 1, "task_id_mapping_required": True,
            "tokenizer": "Qwen3.8 official" if tokenizer is not None else "scripted",
            "tool_argument_mapping": tokenizer is not None}
    finally:
        loop._session_pool.shutdown(wait=True)
        await runner.cleanup()


async def shutdown_scenario(harness, *, delayed_create=False):
    """Real upstream run/stop loops; mock loop-owning sessions block until close."""
    from openenv.core.harness import VerifyResult
    sessions = []
    creating = threading.Event()
    class Session:
        def __init__(self): self.closed = threading.Event()
        def wait_for_completion(self):
            if not self.closed.wait(3): raise TimeoutError("Bounded probe timeout")
        def fetch_proxy_trace(self): return []
        def verify(self, transcript): return VerifyResult(env_reward=0, done=True)
        def close(self): self.closed.set()
    class Factory:
        def create(self, *args, **kwargs):
            creating.set()
            if delayed_create:
                time.sleep(0.5)
            session = Session()
            sessions.append(session)
            return session
    loop = make_loop(harness, Factory(), None, SimpleNamespace(value=1))
    stop = asyncio.Event()
    task = asyncio.create_task(loop._run_loops(stop))
    deadline = time.monotonic() + 2
    while not (creating.is_set() if delayed_create else len(loop._live_sessions) == 2):
        assert time.monotonic() < deadline, "Probe sessions failed to start"
        await asyncio.sleep(0.005)
    started = time.monotonic()
    stop.set()
    # Every mock session has its own finite deadline; this cannot wait indefinitely.
    await asyncio.wait_for(task, timeout=6)
    duration = time.monotonic() - started
    assert all(s.closed.is_set() for s in sessions)
    assert not loop._live_sessions
    if delayed_create:
        assert duration > 2.5  # Stop's snapshot missed the not-yet-registered sessions.
    else:
        assert duration < 2
    return {"creating_at_stop": delayed_create, "stop_seconds": duration,
            "sessions_closed": True, "waited_for_session_timeout": delayed_create}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("research/harness-validation.json"))
    args = p.parse_args()
    worker = load_worker(Path(".cache/upstream/async_rollout_worker.py"))
    harness = load_harness(worker)
    with browser_service(Path(".cache/openenv-browser-source")) as (client, _, url):
        client_factory = partial(client.BrowserGymEnv, base_url=url)
        stable = asyncio.run(browser_scenario(harness, client_factory))
        changing = asyncio.run(browser_scenario(harness, client_factory, update=True))
        from upstream_chat_probe import load_chat_utils
        from transformers import AutoTokenizer
        chat = load_chat_utils()
        tokenizer = AutoTokenizer.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
        for name in ("parse_response", "add_response_schema", "get_training_chat_template",
                     "is_chat_template_prefix_preserving"):
            setattr(worker, name, getattr(chat, name))
        harness.parse_response = chat.parse_response
        real = asyncio.run(browser_scenario(harness, client_factory, tokenizer=tokenizer))
        reasoning_message = {"role": "assistant", "content": "", "reasoning_content": "KEEP_THIS_REASONING",
            "tool_calls": [{"function": {"name": "click", "arguments": {"bid": "1"}}}]}
        serialized = harness._msg_to_llm_response(reasoning_message).to_message_dict()
        assert "KEEP_THIS_REASONING" not in json.dumps(serialized)
    report = {"source": URL, "source_sha256": SHA,
        "scope": "complete upstream harness-worker class; scripted tokenizer/HTTP inference; real browsers",
        "stable_policy": stable, "forced_update": changing, "real_qwen_tokenizer": real,
        "trl_chat_source_sha256": chat.source_hashes,
        "openenv_response_conversion_preserves_reasoning": False,
        "registered_session_shutdown": asyncio.run(shutdown_scenario(harness)),
        "creation_in_progress_shutdown": asyncio.run(shutdown_scenario(harness, delayed_create=True)),
        "gpu_used": False, "rl_ready": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
