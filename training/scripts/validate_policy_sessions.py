#!/usr/bin/env python3
"""CPU: patched installed TRL + spawned worker + BrowserGym + native LoRA HTTP sync.

Scripted inference only. Tiny random BF16 adapters are saved, never GPU-trained.
The HTTP receiver rejects unknown adapters and eviction during active requests.
"""
import argparse
import asyncio
from functools import partial
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["VLLM_NO_USAGE_STATS"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")

from browser_training.harness_bridge import TaskSelectingSessionFactory, MappingArgumentsHarnessAdapter
from browser_training.policy_compat import HASHES, is_patched
from browser_training.policy_sessions import evict_idle
from validate_browser import browser_service, action_for
from validate_spawned_harness import select_fixture


async def scenario(client, browser_url, mode):
    import torch
    from accelerate import Accelerator
    from aiohttp import web
    from datasets import Dataset
    from openenv.core.harness import MCPHarnessAdapter
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, Qwen3Config, Qwen3ForCausalLM
    from trl.experimental.async_grpo import AsyncGRPOTrainer
    from trl.experimental.async_grpo.openenv_harness import HarnessRolloutWorker
    from trl.experimental.async_grpo.vllm_client import VLLMClient
    from vllm.entrypoints.serve.lora.protocol import LoadLoRAAdapterRequest, UnloadLoRAAdapterRequest
    from browsergym_env.harness import BrowserGymSessionFactory, build_browsergym_action_tool_call
    from check_adapter_dtypes import check

    accelerator = Accelerator(cpu=True)
    tokenizer = AutoTokenizer.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
    loaded, active, requests, transport_events, failures = {}, {}, [], [], []
    first_pair = asyncio.Event()
    updated = asyncio.Event()
    initial_calls = 0

    async def control(request):
        try:
            path = request.path
            if path == "/v1/load_lora_adapter":
                data = LoadLoRAAdapterRequest.model_validate(await request.json())
                assert not data.load_inplace and data.lora_name not in loaded
                folder = Path(data.lora_path)
                assert check(folder)["dtype"] == "BF16"
                loaded[data.lora_name] = folder
                transport_events.append(["load", data.lora_name])
            elif path == "/v1/unload_lora_adapter":
                data = UnloadLoRAAdapterRequest.model_validate(await request.json())
                assert active.get(data.lora_name, 0) == 0, "Eviction with an outstanding HTTP request"
                snapshot = worker.policy_registry.snapshot()
                version = int(data.lora_name.rsplit("v", 1)[1])
                assert all(g["version"] != version for g in snapshot["groups"].values())
                loaded.pop(data.lora_name)
                transport_events.append(["unload", data.lora_name])
            else:
                assert path in ("/pause", "/resume")
                transport_events.append([path])
            return web.json_response({})
        except Exception as exc:
            failures.append(repr(exc))
            return web.json_response({"error": repr(exc)}, status=500)

    async def completion(request):
        nonlocal initial_calls
        payload = await request.json()
        name = payload["model"]
        if name not in loaded:
            failures.append(f"Requested unloaded {name}")
            return web.json_response({"error": "adapter missing"}, status=404)
        active[name] = active.get(name, 0) + 1
        try:
            text = tokenizer.decode(payload["prompt"])
            turn = text.count("<|im_start|>assistant") - 1
            responses = re.findall(r"<tool_response>\s*(.*?)\s*</tool_response>", text, re.DOTALL)
            observation = json.loads(responses[-1])["observation_text"] if turn else text
            invalid = turn == 0 and initial_calls % 2 == 1
            if turn == 0:
                initial_calls += 1
            requests.append({"model": name, "turn": turn})
            # Hold both initial HTTP responses until real native sync has published
            # v2 (pinning case) or v4 (staleness/retention case).
            if name == "trl-policy-v1" and turn == 0:
                if initial_calls >= 2:
                    first_pair.set()
                await asyncio.wait_for(updated.wait(), timeout=20)
            action = action_for([{"content": observation}], turn, invalid)
            call = build_browsergym_action_tool_call(action)
            response = "<tool_call>\n<function=" + call.name + ">\n"
            for key, value in call.args.items():
                response += f"<parameter={key}>\n{value}\n</parameter>\n"
            response += "</function>\n</tool_call><|im_end|>"
            ids = tokenizer.encode(response, add_special_tokens=False)
            return web.json_response({"choices": [{"token_ids": ids,
                "logprobs": {"token_logprobs": [-0.25] * len(ids)}}]})
        finally:
            active[name] -= 1

    app = web.Application()
    app.router.add_post("/v1/completions", completion)
    for path in ("/pause", "/resume", "/v1/load_lora_adapter", "/v1/unload_lora_adapter"):
        app.router.add_post(path, control)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server_url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    factory = TaskSelectingSessionFactory(BrowserGymSessionFactory(
        partial(client.BrowserGymEnv, base_url=browser_url), default_task="mock"), select_fixture)
    worker = HarnessRolloutWorker(harness_session_factory=factory,
        harness_adapter=MappingArgumentsHarnessAdapter(MCPHarnessAdapter()),
        model_name="mock", dataset=Dataset.from_list([
            {"prompt": [{"role": "user", "content": "Complete the browser task."}], "seed": 42}]),
        reward_funcs=[], processing_class=tokenizer, num_generations=2, max_inflight_tasks=2,
        queue_maxsize=2, child_ready_timeout=45, max_tokens=512, request_timeout=25,
        max_tool_calling_iterations=3, lora_name="trl-policy", vllm_server_url=server_url,
        chat_template_kwargs={"enable_thinking": False, "preserve_thinking": True})
    worker.policy_registry.configure(2)
    config = Qwen3Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8)
    config._attn_implementation = "eager"
    torch.manual_seed(42)
    model = get_peft_model(Qwen3ForCausalLM(config).to(torch.bfloat16),
        LoraConfig(r=2, lora_alpha=4, target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM"),
        autocast_adapter_dtype=False)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="trl-policy-sessions-") as directory:
            trainer = SimpleNamespace(model=model, accelerator=accelerator, model_version=0,
                _lora_dir=directory, _lora_name="trl-policy", _adapter_name="default",
                args=SimpleNamespace(max_staleness=2), vllm_client=VLLMClient(server_url), rollout_worker=worker)
            async def sync():
                with torch.no_grad():
                    next(p for n, p in model.named_parameters() if "lora_B" in n).flatten()[0].add_(0.05)
                await asyncio.to_thread(AsyncGRPOTrainer._sync_weight_lora, trainer, time.time())
            await sync()
            await asyncio.to_thread(worker.start)
            child = worker._process
            await asyncio.wait_for(first_pair.wait(), timeout=25)
            for _ in range(1 if mode == "pinning" else 3):
                await sync()
            during_update = worker.policy_registry.snapshot()
            assert "trl-policy-v1" in loaded and active["trl-policy-v1"] == 2
            assert all(g["version"] == 1 for g in during_update["groups"].values())
            updated.set()
            expected = 1 if mode == "pinning" else 4
            samples = [await asyncio.to_thread(worker.rollout_buffer.get, True, 30) for _ in range(2)]
            assert {s.model_version for s in samples} == {expected}
            assert {s.metrics["reward"] for s in samples} == {0, 1}
            assert len({s.group_id for s in samples}) == 1
            for sample in samples:
                assert abs(sample.advantage - (1 if sample.metrics["reward"] else -1)) < 1e-6
                assert all(lp == (-0.25 if mask else 0.0) for lp, mask in
                    zip(sample.old_log_probs, sample.completion_mask, strict=True))
                assert any(sample.completion_mask) and not all(sample.completion_mask)
            worker.check_health(stale_after_s=30)
            await asyncio.to_thread(worker.stop)
            assert child.exitcode == 0, child.exitcode
            await asyncio.to_thread(evict_idle, trainer)
            snapshot = worker.policy_registry.snapshot()
            assert not snapshot["groups"] and not snapshot["episodes"] and snapshot["fault"] is None
            if mode == "staleness":
                assert [r["turn"] for r in requests if r["model"] == "trl-policy-v1"] == [0, 0]
                assert "trl-policy-v1" not in loaded
                assert not (Path(directory) / "trl-policy-v1").exists()
                assert any(e["event"] == "group_cancel" and e["reason"] == "staleness" for e in snapshot["events"])
            else:
                assert any(r == {"model": "trl-policy-v1", "turn": 1} for r in requests)
            assert not failures, failures
            return dict(mode=mode, status="PASS", seconds=time.monotonic() - started,
                requests=requests, samples=[dict(group_id=s.group_id, policy_version=s.model_version,
                    reward=s.metrics["reward"], advantage=s.advantage) for s in samples],
                adapter_retained_during_inference=True, child_exitcode=child.exitcode,
                transport_events=transport_events, final_registry=snapshot,
                observations_masked=True, logprobs_aligned=True, native_lora_sync=True)
    finally:
        updated.set()
        await asyncio.to_thread(worker.stop)
        worker._policy_manager.shutdown()
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("research/policy-session-validation.json"))
    args = parser.parse_args()
    import importlib.metadata
    folder = Path(importlib.metadata.distribution("trl").locate_file("trl/experimental/async_grpo"))
    for name in HASHES:
        assert is_patched(name, (folder / name).read_text()), "Apply scripts/patch_trl_policy.py --apply"
    with browser_service(Path(".cache/openenv-browser-source"),
                         python_executable=str(Path("envs/browser/.venv/bin/python").absolute())) as (client, _, url):
        results = [asyncio.run(scenario(client, url, mode)) for mode in ("pinning", "staleness")]
    report = dict(status="PASS", scenarios=results,
        installed_sources={name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in HASHES},
        implementation_sources={name: hashlib.sha256((Path("browser_training") / name).read_bytes()).hexdigest()
                                for name in ("policy_sessions.py", "policy_compat.py")},
        scope="Installed patched TRL, real spawn/IPC, native PEFT save and HTTP sync, real BrowserGym/OpenEnv, real Qwen tokenizer, scripted inference",
        gpu_used=False, model_weights_downloaded=False, gradients_executed=False, vllm_engine_executed=False,
        rl_ready=False)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "scenarios": [{"mode": r["mode"], "status": r["status"],
        "seconds": r["seconds"]} for r in results], "report": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
