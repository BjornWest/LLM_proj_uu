#!/usr/bin/env python3
"""CPU: real spawned TRL worker/new two-turn harness, scripted HTTP completions."""
import argparse
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"


async def probe(output, tokenizer_path):
    from accelerate import PartialState
    from aiohttp import web
    from datasets import Dataset
    from transformers import AutoTokenizer
    from browser_training.acceptance_harness import ChoiceFactory, TwoTurnAdapter, choice_outcome, task_pool
    from browser_training.runtime_metrics import start_metrics
    from browser_training.monitored_harness import MonitoredSessionFactory, MonitoredHarnessAdapter
    from browser_training.trl_monitoring import MonitoredHarnessWorker
    PartialState(cpu=True)
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    calls = []

    async def completion(request):
        payload = await request.json()
        ids = tokenizer.encode(("A" if len(calls) % 2 else "B") + "<|im_end|>", add_special_tokens=False)
        calls.append(payload["model"])
        return web.json_response(dict(choices=[dict(token_ids=ids, logprobs=dict(token_logprobs=[-0.7]*len(ids)))]))

    app = web.Application()
    app.router.add_post("/v1/completions", completion)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    manager, monitor = start_metrics(multiprocessing.get_context("spawn"), output / "metrics",
        run_id=output.name, synthetic=True, tasks=task_pool())
    worker = MonitoredHarnessWorker(
        harness_session_factory=MonitoredSessionFactory(ChoiceFactory(), monitor, group_size=4, extractor=choice_outcome),
        harness_adapter=MonitoredHarnessAdapter(TwoTurnAdapter()), model_name="mock", lora_name="trl-policy",
        dataset=Dataset.from_list([dict(prompt=[dict(role="user", content="ignored by synthetic session")])]),
        reward_funcs=[], processing_class=tokenizer, num_generations=4, max_inflight_tasks=4, queue_maxsize=4,
        child_ready_timeout=60, max_tokens=8, request_timeout=5, max_tool_calling_iterations=2,
        vllm_server_url=f"http://127.0.0.1:{port}",
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
    worker.policy_registry.publish(1)
    worker.update_model_version(1)
    try:
        await asyncio.to_thread(worker.start)
        child = worker._process
        rows = [await asyncio.to_thread(worker.rollout_buffer.get, True, 30) for _ in range(4)]
        await asyncio.to_thread(worker.stop)
        assert child.exitcode == 0
        assert calls and set(calls) == {"trl-policy-v1"}
        assert {r.metrics["reward"] for r in rows} == {0.0, 1.0}
        for row in rows:
            assert row.metrics.row_identity and row.model_version == 1
            assert len(row.old_log_probs) == len(row.completion_mask) == len(row.input_ids)
            assert sum(row.completion_mask) == 4  # Two 2-token completions combined natively.
        snapshot = monitor.emit_snapshot()
        assert snapshot["training_rows"]["totals"]["applied"] == 0
        report = dict(status="PASS", scripted_inference=True, gpu_used=False, model_loaded=False,
            native_spawned_worker=True, two_turn_rows=len(rows), calls=len(calls), snapshot_id=snapshot["snapshot_id"])
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        await asyncio.to_thread(worker.stop)
        manager.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--tokenizer", default=".cache/qwen38-tokenizer")
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(probe(a.output.resolve(), a.tokenizer))
