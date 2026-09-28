#!/usr/bin/env python3
"""CPU: native spawned TRL + frozen full P11 browser; scripted token completions."""
import argparse
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"


async def probe(output, tokenizer_path, frozen, browser_python, slow_shutdown_seconds=0):
    from accelerate import PartialState
    from aiohttp import web
    from datasets import Dataset
    from transformers import AutoTokenizer
    from browser_training.project_harness import ProjectFactory, ProjectAdapter, project_outcome, project_tasks
    from browser_training.runtime_metrics import start_metrics
    from browser_training.monitored_harness import MonitoredSessionFactory, MonitoredHarnessAdapter
    from browser_training.trl_monitoring import MonitoredHarnessWorker
    PartialState(cpu=True)
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)
    calls = []
    delayed = asyncio.Event()

    async def completion(request):
        payload = await request.json()
        import re
        text = tokenizer.decode(payload['prompt'])
        turn = text.count('<|im_start|>assistant') - 1
        if turn == 0:
            buttons = re.findall(r"\[(\d+)\] button 'Buy now'", text)
            assert len(buttons) == 3
            name, args = 'click', {'bid': buttons[sum(c['turn'] == 0 for c in calls) % 2]}
        else:
            name, args = 'send_msg_to_user', {'text': 'Done'}
        raw = '<tool_call>\n<function=' + name + '>\n'
        for key, value in args.items():
            raw += f'<parameter={key}>\n{value}\n</parameter>\n'
        raw += '</function>\n</tool_call><|im_end|>'
        ids = tokenizer.encode(raw, add_special_tokens=False)
        calls.append(dict(model=payload['model'], turn=turn, ids=ids, prompt_tokens=len(payload['prompt'])))
        if slow_shutdown_seconds and turn == 0 and sum(c['turn'] == 0 for c in calls) > 4:
            delayed.set()
            await asyncio.sleep(slow_shutdown_seconds)
        return web.json_response(dict(choices=[dict(token_ids=ids, logprobs=dict(token_logprobs=[-0.7]*len(ids)))]))

    app = web.Application()
    app.router.add_post("/v1/completions", completion)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    manager, monitor = start_metrics(multiprocessing.get_context("spawn"), output / "metrics",
        run_id=output.name, synthetic=True, tasks=project_tasks(json.loads((frozen.parent / "frozen-sources.json").read_text())["sha256"]))
    worker = MonitoredHarnessWorker(
        harness_session_factory=MonitoredSessionFactory(ProjectFactory(frozen, browser_python, output / "browser", Path(__file__).resolve().parent / "project_browser_worker.py"), monitor, group_size=4, extractor=project_outcome),
        harness_adapter=MonitoredHarnessAdapter(ProjectAdapter(tokenizer_path)), model_name="mock", lora_name="trl-policy",
        dataset=Dataset.from_list([dict(prompt=[dict(role="user", content="ignored by synthetic session")])]),
        reward_funcs=[], processing_class=tokenizer, num_generations=4, max_inflight_tasks=4, queue_maxsize=4,
        child_ready_timeout=60, max_tokens=256, request_timeout=30, max_tool_calling_iterations=2,
        vllm_server_url=f"http://127.0.0.1:{port}",
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
    worker.enable_shutdown_drain(monitor)
    worker.policy_registry.publish(1)
    worker.update_model_version(1)
    try:
        await asyncio.to_thread(worker.start)
        child = worker._process
        rows = [await asyncio.to_thread(worker.rollout_buffer.get, True, 90) for _ in range(4)]
        if slow_shutdown_seconds:
            await asyncio.wait_for(delayed.wait(), timeout=45)
        import time
        stopping_at = time.monotonic()
        await asyncio.to_thread(worker.stop)
        shutdown_s = time.monotonic() - stopping_at
        assert child.exitcode == 0
        worker.policy_registry.assert_healthy()
        registry = worker.policy_registry.snapshot()
        assert not registry['groups'] and not registry['episodes']
        assert calls and {c["model"] for c in calls} == {"trl-policy-v1"}
        assert {r.metrics["reward"] for r in rows} == {0.0, 1.0}
        for row in rows:
            assert row.metrics.row_identity and row.model_version == 1
            assert len(row.old_log_probs) == len(row.completion_mask) == len(row.input_ids)
            # Generated spans equal the real scripted HTTP outputs, including EOS.
            spans, span = [], []
            for tid, mask in zip(row.input_ids, row.completion_mask):
                if mask:
                    span.append(tid)
                elif span:
                    spans.append(span); span = []
            if span: spans.append(span)
            assert len(spans) == 2
            assert all(span in [c['ids'] for c in calls] for span in spans)
            assert all(lp == -0.7 for lp, mask in zip(row.old_log_probs, row.completion_mask) if mask)
        snapshot = monitor.emit_snapshot()
        assert snapshot["training_rows"]["totals"]["applied"] == 0
        report = dict(status="PASS", scripted_inference=True, gpu_used=False, model_loaded=False,
            native_spawned_worker=True, two_turn_rows=len(rows), calls=len(calls), snapshot_id=snapshot["snapshot_id"], shutdown_s=shutdown_s, slow_shutdown_seconds=slow_shutdown_seconds, shutdown_discarded_rows=worker.shutdown_discarded_rows, policy_healthy=True, generated_tokens=[sum(r.completion_mask) for r in rows], request_tokens=[c["prompt_tokens"] for c in calls], tokenizer="Qwen3.8-27B", rewards=[r.metrics["reward"] for r in rows])
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
    p.add_argument('--frozen', required=True, type=Path)
    p.add_argument('--browser-python', required=True, type=Path)
    p.add_argument('--slow-shutdown-seconds', type=float, default=0)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    asyncio.run(probe(a.output.resolve(), str(Path(a.tokenizer).resolve()), a.frozen.resolve(), a.browser_python.absolute(), a.slow_shutdown_seconds))
