#!/usr/bin/env python3
"""Small source-only audit; downloads Python source, never weights or GPU wheels."""
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import urllib.request

COMMIT = "a04ffd337108285002df29d9ae73ef7e855e03f1"
BASE = f"https://raw.githubusercontent.com/huggingface/trl/{COMMIT}/trl/experimental/async_grpo/"


def reproduce_policy_change(source):
    tree = ast.parse(source)
    selected = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_request_model", "_generate_one_turn"}:
            selected[node.name] = node
    # Compile ONLY these two audited upstream methods, without importing TRL or CUDA.
    body = list(selected.values())
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="Probe", bases=[], keywords=[],
        body=body, decorator_list=[])], type_ignores=[])), "<upstream-methods>", "exec"), namespace)
    probe = namespace["Probe"]()
    for name, value in {"lora_name": "trl-policy", "model_version": 1, "model_name": "base", "max_tokens": 8,
        "temperature": 1.0, "top_p": 1.0, "top_k": 0, "repetition_penalty": 1.0,
        "request_timeout": 30, "min_p": None}.items():
        setattr(probe, name, value)
    names = []

    async def post(path, payload, timeout):
        names.append(payload["model"])
        return {"choices": [{"token_ids": [1], "logprobs": {"token_logprobs": [-0.5]}}]}

    async def retry(factory, **kwargs):
        return await factory()

    async def episode():
        probe._post, probe._retry = post, retry
        await probe._generate_one_turn([1])
        probe.model_version = 2
        await probe._generate_one_turn([1, 2])

    asyncio.run(episode())
    return names


def main():
    worker_url = BASE + "async_rollout_worker.py"
    worker = urllib.request.urlopen(worker_url, timeout=30).read().decode()
    trainer = urllib.request.urlopen(BASE + "async_grpo_trainer.py", timeout=30).read().decode()
    released_url = "https://raw.githubusercontent.com/huggingface/trl/v1.13.0/trl/experimental/async_grpo/async_grpo_trainer.py"
    released = urllib.request.urlopen(released_url, timeout=30).read().decode()
    def params(source):
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "AsyncGRPOTrainer")
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        return [a.arg for a in init.args.args]
    names = reproduce_policy_change(worker)
    arg_url = "https://raw.githubusercontent.com/vllm-project/vllm/v0.28.0/vllm/engine/arg_utils.py"
    arg_source = urllib.request.urlopen(arg_url, timeout=30).read().decode()
    flags = ["enable-lora", "lora-dtype", "max-lora-rank", "max-loras", "weight-transfer-config",
             "logprobs-mode", "language-model-only", "speculative-config", "max-num-seqs", "generation-config"]
    verified_flags = {flag: "--" + flag in arg_source for flag in flags}
    assert all(verified_flags.values()), verified_flags
    report = {"commit": COMMIT, "worker_source": worker_url, "worker_sha256": hashlib.sha256(worker.encode()).hexdigest(),
        "release_1_13_has_peft_config": "peft_config" in params(released),
        "pinned_commit_has_peft_config": "peft_config" in params(trainer),
        "successive_turn_model_names_during_sync": names,
        "episode_policy_is_immutable": len(set(names)) == 1,
        "trainer_hardcodes_flash_attn3": 'attn_implementation="kernels-community/flash-attn3"' in trainer,
        "vllm_argument_source": arg_url, "vllm_flags_present_in_pinned_source": verified_flags}
    dest = Path("research/audit.json")
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
