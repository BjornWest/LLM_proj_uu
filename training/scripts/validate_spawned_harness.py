#!/usr/bin/env python3
"""Installed TRL spawned worker + real BrowserGym + real tokenizer, scripted inference."""
import asyncio
import argparse
from functools import partial
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import time

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["VLLM_NO_USAGE_STATS"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")

from browser_training.harness_bridge import TaskSelectingSessionFactory, MappingArgumentsHarnessAdapter
from validate_browser import browser_service, action_for


def select_fixture(task, seed):
    """A module-level selector survives the actual spawn/pickle boundary."""
    return "mock"


async def probe(client, browser_url, metrics_output=None):
    from accelerate import PartialState
    from aiohttp import web
    from datasets import Dataset
    from openenv.core.harness import MCPHarnessAdapter
    from transformers import AutoTokenizer
    from trl.experimental.async_grpo.openenv_harness import HarnessRolloutWorker
    from browsergym_env.harness import BrowserGymSessionFactory, build_browsergym_action_tool_call

    PartialState(cpu=True)
    monitored_files = [Path(__file__), *[Path("browser_training") / name for name in
        ("runtime_metrics.py", "monitored_harness.py", "policy_sessions.py", "curriculum.py", "outcomes.py")]]
    monitoring_sources = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in monitored_files}
    tokenizer = AutoTokenizer.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
    requests = []
    initial_calls = 0

    async def completion(request):
        nonlocal initial_calls
        payload = await request.json()
        text = tokenizer.decode(payload["prompt"])
        turn = text.count("<|im_start|>assistant") - 1
        responses = re.findall(r"<tool_response>\s*(.*?)\s*</tool_response>", text, re.DOTALL)
        observation = json.loads(responses[-1])["observation_text"] if turn else text
        invalid = turn == 0 and initial_calls % 2 == 1
        if turn == 0:
            initial_calls += 1
        action = action_for([{"content": observation}], turn, invalid)
        call = build_browsergym_action_tool_call(action)
        response = "<tool_call>\n<function=" + call.name + ">\n"
        for name, value in call.args.items():
            response += f"<parameter={name}>\n{value}\n</parameter>\n"
        response += "</function>\n</tool_call><|im_end|>"
        ids = tokenizer.encode(response, add_special_tokens=False)
        requests.append({"model": payload["model"], "turn": turn, "tokens": len(ids)})
        return web.json_response({"choices": [{"token_ids": ids,
            "logprobs": {"token_logprobs": [-0.25] * len(ids)}}]})

    app = web.Application()
    app.router.add_post("/v1/completions", completion)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base_factory = BrowserGymSessionFactory(partial(client.BrowserGymEnv, base_url=browser_url), default_task="mock")
    factory = TaskSelectingSessionFactory(base_factory, select_fixture)
    adapter = MappingArgumentsHarnessAdapter(MCPHarnessAdapter())
    metrics_manager = monitor = None
    worker_class = HarnessRolloutWorker
    if metrics_output is not None:
        import multiprocessing
        from browser_training.runtime_metrics import start_metrics
        from browser_training.monitored_harness import MonitoredSessionFactory, MonitoredHarnessAdapter, plumbing_outcome
        from browser_training.trl_monitoring import MonitoredHarnessWorker
        worker_class = MonitoredHarnessWorker
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        tokenizer_hash = hashlib.sha256(Path(".cache/qwen38-tokenizer/tokenizer_config.json").read_bytes()).hexdigest()
        pool = [dict(task_id="mock", task_family="local-plumbing", task_template="no-subscription",
                     harness_revision=source_hash, verifier_revision=source_hash, environment_revision=source_hash,
                     tokenizer_revision=f"Qwen3.8:tokenizer-config-sha256:{tokenizer_hash}", split="rl_train")]
        metrics_manager, monitor = start_metrics(multiprocessing.get_context("spawn"), metrics_output,
            run_id=metrics_output.name, synthetic=True, tasks=pool,
            expected_producers=["browser", "orchestrator"])
        factory = MonitoredSessionFactory(base_factory, monitor, group_size=2, extractor=plumbing_outcome)
        adapter = MonitoredHarnessAdapter(adapter)
    worker = worker_class(harness_session_factory=factory,
        harness_adapter=adapter,
        model_name="mock", dataset=Dataset.from_list([
            {"prompt": [{"role": "user", "content": "Complete the browser task."}], "seed": 42}]),
        reward_funcs=[], processing_class=tokenizer, num_generations=2, max_inflight_tasks=2,
        queue_maxsize=2, child_ready_timeout=45, max_tokens=512, request_timeout=5,
        max_tool_calling_iterations=3, lora_name="trl-policy",
        vllm_server_url=f"http://127.0.0.1:{port}",
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
    worker.update_model_version(1)
    if getattr(worker, "policy_registry", None) is not None:
        worker.policy_registry.publish(1)
    started = time.monotonic()
    try:
        await asyncio.to_thread(worker.start)
        child = worker._process
        samples = []
        for _ in range(2):
            samples.append(await asyncio.to_thread(worker.rollout_buffer.get, True, 30))
        worker.check_health(stale_after_s=30)
        assert {sample.metrics["reward"] for sample in samples} == {0, 1}
        assert len({sample.group_id for sample in samples}) == 1
        for sample in samples:
            reward = sample.metrics["reward"]
            assert sample.metrics["tools/call_frequency"] == (2 if reward else 1)
            assert sample.model_version == 1 and abs(sample.advantage - (1 if reward else -1)) < 1e-6
            assert len(sample.input_ids) == len(sample.completion_mask) == len(sample.old_log_probs)
            assert any(sample.completion_mask) and not all(sample.completion_mask)
            assert all(lp == (-0.25 if mask else 0.0) for lp, mask in
                zip(sample.old_log_probs, sample.completion_mask, strict=True))
        stop_start = time.monotonic()
        await asyncio.to_thread(worker.stop)
        assert child.exitcode == 0, f"Child required termination or failed: {child.exitcode}"
        metrics_evidence = None
        if monitor is not None:
            from browser_training.outcomes import Ledger
            value = monitor.emit_snapshot()
            m = value["cohorts"]["rl_train"]["all"]["metrics"]
            # The worker can start another group while the parent consumes the queue.
            assert m["episodes"]["value"] >= 2
            assert m["admitted"]["value"] == 0  # Queue consumption isn't optimizer use.
            assert m["generated_tokens"]["value"] >= sum(sum(s.completion_mask) for s in samples)
            episode_events = [r["event"]["payload"] for r in Ledger(
                metrics_output / "events.sqlite", run_id=metrics_output.name, synthetic=True,
                expected_producers=["browser", "orchestrator"]).records() if r["event"]["kind"] == "episode"]
            first = [e for e in episode_events if e["group_id"].endswith(f":{samples[0].group_id}")]
            assert len(first) == 2 and {e["reward"] for e in first} == {0, 1}
            assert {e["policy_version"] for e in first} == {1}
            assert len({(e["task_instance"], e["seed"]) for e in first}) == 1
            assert sum(e["generated_tokens"] for e in first) == sum(sum(s.completion_mask) for s in samples)
            for sample in samples:
                identity = sample.metrics.row_identity
                assert identity["episode_id"] in {e["episode_id"] for e in first}
            assert value["training_rows"]["totals"]["rows"] >= 2
            assert value["training_rows"]["totals"]["applied"] == 0
            metrics_evidence = dict(snapshot_id=value["snapshot_id"], completed_group_records=first,
                native_rewards_and_policy_versions_match=True, generated_token_count_matches=True,
                output=str(metrics_output), admission="Pending: native queue rows were inspected, no optimizer ran")
        assert monitoring_sources == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in monitored_files}
        return {"status": "PASS", "metrics": metrics_evidence, "monitoring_source_sha256": monitoring_sources,
            "installed_trl_harness_sha256": hashlib.sha256(
                Path(inspect.getfile(HarnessRolloutWorker)).read_bytes()).hexdigest(),
            "start_method": "spawn", "child_exitcode": child.exitcode,
            "samples": [{"reward": s.metrics["reward"], "policy_version": s.model_version,
                "group_id": s.group_id, "advantage": s.advantage,
                "generated_tokens": sum(s.completion_mask)} for s in samples],
            "requests": requests, "seconds": time.monotonic() - started,
            "stop_seconds": time.monotonic() - stop_start,
            "tokenizer": "Qwen3.8 official", "parser": "installed TRL",
            "import_substitutions": False, "observations_masked": True,
            "logprobs_aligned": True, "gpu_used": False, "trainer_executed": False,
            "rl_ready": False,
            "note": "Fixed policy; scripted success/subscription failure; native scoring but no trainer update"}
    finally:
        await asyncio.to_thread(worker.stop)
        if metrics_manager is not None:
            metrics_manager.shutdown()
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-output", type=Path, help="New output directory for live sampled-session metrics")
    args = parser.parse_args()
    output = args.metrics_output.resolve() if args.metrics_output else None
    if output:
        output.mkdir(parents=True, exist_ok=False)
    with browser_service(Path(".cache/openenv-browser-source"),
                         python_executable=str(Path("envs/browser/.venv/bin/python").absolute())) as (client, _, url):
        report = asyncio.run(probe(client, url, output))
    target = output / "report.json" if output else Path("research/spawned-harness-validation.json")
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
