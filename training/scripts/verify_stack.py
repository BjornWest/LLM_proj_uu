#!/usr/bin/env python3
import argparse
import importlib
import importlib.metadata as metadata
import inspect
import json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role", choices=["local", "sft", "rl", "browser"], default="local")
    args = p.parse_args()
    modules = {"local": ["yaml", "browser_training.environment"],
        "sft": ["torch", "transformers", "peft", "accelerate", "axolotl", "fla", "bitsandbytes"],
        "rl": ["torch", "transformers", "peft", "accelerate", "trl", "vllm", "fla", "kernels", "bitsandbytes"],
        "browser": ["openenv", "browsergym.core"]}[args.role]
    for module in modules:
        importlib.import_module(module)
    expected = {"torch": "2.13.0", "transformers": "5.16.1", "peft": "0.20.0", "accelerate": "1.13.0"}
    if args.role in {"sft", "rl"}:
        for name, version in expected.items():
            actual = metadata.version(name).split("+")[0]
            assert actual == version, (name, actual, version)
    if args.role == "sft":
        assert metadata.version("axolotl") == "0.19.0"
        from axolotl.integrations.base import BasePlugin
        assert hasattr(BasePlugin, "post_model_load")
    if args.role == "rl":
        from pathlib import Path
        from browser_training.policy_compat import HASHES, is_patched
        folder = Path(metadata.distribution("trl").locate_file("trl/experimental/async_grpo"))
        for name in HASHES:
            assert is_patched(name, (folder / name).read_text()), "Run scripts/patch_trl_policy.py --apply"
        from trl.experimental.async_grpo import AsyncGRPOTrainer, AsyncGRPOConfig
        assert "peft_config" in inspect.signature(AsyncGRPOTrainer).parameters
        for key in ("token_budget", "max_staleness", "max_inflight_tasks"):
            assert key in AsyncGRPOConfig.__dataclass_fields__
        assert metadata.version("vllm") == "0.28.0"
        from apply_vllm_cpu_kv_patch import apply_patch
        offload_patch = apply_patch(verify_only=True)
        # Report the installed artifact's immutable source URL, not just dev version.
        direct = metadata.distribution("trl").read_text("direct_url.json")
        assert direct and "a04ffd337108285002df29d9ae73ef7e855e03f1" in direct, direct
    if args.role in {"rl", "browser"}:
        assert metadata.version("openenv") == "0.4.2"
        from openenv.core.client_types import StepResult
        assert "metadata" in inspect.signature(StepResult).parameters
        from openenv.core.harness import HarnessAdapter, HarnessRunLimits, ModelStepResult, ResourceSessionFactory
        try:
            metadata.version("openenv-core")
        except metadata.PackageNotFoundError:
            pass
        else:
            raise RuntimeError("openenv and openenv-core both own the openenv namespace; remove openenv-core")
    result = {"role": args.role, "imports": modules, "status": "PASS"}
    if args.role == "rl":
        result["vllm_cpu_kv_patch"] = offload_patch
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
