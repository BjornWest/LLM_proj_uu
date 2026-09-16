#!/usr/bin/env python3
"""Installed package/config/PEFT checks; tiny random CPU model, no weight downloads."""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import runpy
import tempfile

# Set before importing any ML packages. GPU qualification is a separate preflight.
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["AXOLOTL_DO_NOT_TRACK"] = "1"
os.environ["VLLM_NO_USAGE_STATS"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")


def check_configs(role):
    import yaml
    if role == "sft":
        from axolotl.utils.config import prepare_plugins, validate_config
        from axolotl.utils.dict import DictDefault
        results = []
        for path in sorted(Path("configs").glob("sft*.yml")):
            cfg = DictDefault(yaml.safe_load(path.read_text()))
            prepare_plugins(cfg)
            validated = validate_config(cfg)
            assert validated.peft_autocast_adapter_dtype is False
            assert validated.bf16 is True
            results.append(str(path))
        return {"schema_validated": results, "device_normalization": "requires remote GPU"}
    from trl.experimental.async_grpo import AsyncGRPOConfig
    results = []
    for path in sorted(Path("configs").glob("rl_*.py")):
        cfg = dict(runpy.run_path(path)["CONFIG"])
        for key in ("model", "revision", "rank", "alpha", "environment", "rollout_model"):
            cfg.pop(key)
        # CPU-only schema probe; production configs keep their GPU precision.
        args = AsyncGRPOConfig(**cfg, use_cpu=True, bf16=True, dtype="bfloat16", report_to="none")
        assert args.max_inflight_tasks >= args.num_generations
        results.append(str(path))
    return {"schema_validated": results, "cpu_override_for_probe_only": True}


def check_peft(role):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from browser_training.precision import enforce_bf16_lora, inspect_dtypes, make_optimizer, inspect_optimizer
    from check_adapter_dtypes import check

    torch.set_num_threads(2)
    torch.manual_seed(42)
    cfg = Qwen3Config(vocab_size=64, hidden_size=32, intermediate_size=64,
        num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
        head_dim=16, max_position_embeddings=64)
    cfg._attn_implementation = "eager"
    base = Qwen3ForCausalLM(cfg).to(torch.bfloat16)
    adapter = LoraConfig(r=4, lora_alpha=8, lora_dropout=0, bias="none",
        target_modules=["q_proj", "v_proj"], task_type="CAUSAL_LM")
    model = get_peft_model(base, adapter, autocast_adapter_dtype=False)
    before = {str(p.dtype) for p in model.parameters() if p.requires_grad}
    enforce_bf16_lora(model)
    ids = torch.tensor([[1, 2, 3, 4, 5, 6]])
    optimizer = make_optimizer(model, 1e-3)
    losses = []
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        loss = model(input_ids=ids, labels=ids).loss
        assert torch.isfinite(loss)
        loss.backward()
        report = inspect_dtypes(model, check_grads=True)
        optimizer.step()
        moments = inspect_optimizer(optimizer)
        losses.append(loss.item())
    assert all(p.grad.abs().sum() > 0 for p in model.parameters() if p.requires_grad)
    with tempfile.TemporaryDirectory(prefix="browser-peft-cpu-") as tmp:
        model.save_pretrained(tmp)
        saved = check(Path(tmp))
        reloaded = PeftModel.from_pretrained(Qwen3ForCausalLM(cfg).to(torch.bfloat16),
            tmp, is_trainable=True, autocast_adapter_dtype=False)
        reload_report = inspect_dtypes(reloaded)
    result = {"model": "random tiny Qwen3; not Qwen3.8 hybrid qualification",
        "parameters": sum(p.numel() for p in model.parameters()), "losses": losses,
        "dtype_before_explicit_cast": sorted(before), "dtypes": report,
        "saved": saved, "reloaded": reload_report,
        "optimizer": "bitsandbytes AdamW32bit CPU; CUDA kernel remains untested",
        "fp32_moment_tensors": moments}
    if role == "rl":
        result["native_lora_publication"] = check_native_lora_publication(model)
    return result


def check_native_lora_publication(model):
    """Native TRL save/HTTP method, real BF16 files, mock vLLM receiver only."""
    import hashlib
    from browser_training.policy_sessions import PolicyRegistry
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import time
    from types import SimpleNamespace
    from urllib.parse import urlsplit
    import torch
    from accelerate import Accelerator
    from trl.experimental.async_grpo import AsyncGRPOTrainer
    from trl.experimental.async_grpo.vllm_client import VLLMClient
    from vllm.entrypoints.serve.lora.protocol import LoadLoRAAdapterRequest, UnloadLoRAAdapterRequest
    from check_adapter_dtypes import check
    events, loaded, hashes, errors = [], {}, [], []

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                path = urlsplit(self.path).path
                if path == "/v1/load_lora_adapter":
                    request = LoadLoRAAdapterRequest.model_validate_json(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    assert not request.load_inplace and request.lora_name not in loaded
                    folder = Path(request.lora_path)
                    assert folder.is_absolute() and (folder / "adapter_config.json").is_file()
                    assert not list(folder.parent.glob(".*.tmp")), "Half-written publication"
                    assert check(folder)["dtype"] == "BF16"
                    digest = hashlib.sha256((folder / "adapter_model.safetensors").read_bytes()).hexdigest()
                    loaded[request.lora_name] = folder
                    hashes.append(digest)
                    events.append(["load", request.lora_name])
                elif path == "/v1/unload_lora_adapter":
                    request = UnloadLoRAAdapterRequest.model_validate_json(
                        self.rfile.read(int(self.headers["Content-Length"])))
                    loaded.pop(request.lora_name)
                    events.append(["unload", request.lora_name])
                else:
                    assert path in ("/pause", "/resume"), path
                    events.append([path.lstrip("/")])
                self.send_response(200)
            except Exception as exc:
                errors.append(repr(exc))
                self.send_response(500)
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="browser-native-lora-") as temp:
            def published(version):
                assert f"trl-policy-v{version}" in loaded
                events.append(["publish", version])
            probe = SimpleNamespace(model=model, accelerator=Accelerator(cpu=True),
                model_version=0, _lora_dir=temp, _lora_name="trl-policy", _adapter_name="default",
                args=SimpleNamespace(max_staleness=2),
                vllm_client=VLLMClient(f"http://127.0.0.1:{server.server_port}"),
                rollout_worker=SimpleNamespace(update_model_version=published, policy_registry=PolicyRegistry(2)))
            for version in range(1, 5):
                with torch.no_grad():
                    next(p for name, p in model.named_parameters() if "lora_B" in name).flatten()[0].add_(0.05)
                AsyncGRPOTrainer._sync_weight_lora(probe, time.time())
                # Existing snapshots must stay immutable as new weights are published.
                for old_version in range(1, version + 1):
                    file = Path(temp) / f"trl-policy-v{old_version}/adapter_model.safetensors"
                    if file.exists():  # Patched eviction deletes files after all reservations drain.
                        assert hashlib.sha256(file.read_bytes()).hexdigest() == hashes[old_version - 1]
            assert not errors, errors
            assert len(set(hashes)) == 4
            assert sorted(loaded) == ["trl-policy-v2", "trl-policy-v3", "trl-policy-v4"]
            return {"events": events, "distinct_bf16_snapshots": 4, "immutable_older_files": True,
                "loaded_before_version_publication": True, "max_staleness": 2,
                "remaining_registered": sorted(loaded), "gpu_used": False,
                "scope": "installed TRL save/sync/HTTP client + real vLLM request schemas; mock receiver, no engine"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def check_hybrid_structure():
    """Allocate metadata only for the actual 27B architecture; no base tensors."""
    from collections import Counter
    import torch
    import yaml
    from accelerate import init_empty_weights
    from peft import LoraConfig, get_peft_model
    from transformers import AutoConfig, Qwen3_5ForConditionalGeneration
    from browser_training.precision import enforce_bf16_lora
    config_path = Path(".cache/qwen38-tokenizer/config.json")
    if not config_path.exists():
        return {"status": "SKIPPED", "reason": "run validate_tokenization.py to cache config assets first"}
    # Validate the exact revision's local asset before relying on its dimensions.
    import hashlib
    from validate_tokenization import ASSETS, REVISION
    assert hashlib.sha256(config_path.read_bytes()).hexdigest() == ASSETS["config.json"]
    cfg = AutoConfig.from_pretrained(config_path.parent, local_files_only=True)
    cfg._attn_implementation = "sdpa"
    targets = yaml.safe_load(Path("configs/sft_qwen38_27b_bf16_lora.yml").read_text())["lora_target_modules"]
    with init_empty_weights():
        model = Qwen3_5ForConditionalGeneration(cfg).to(dtype=torch.bfloat16)
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0,
            target_modules=targets, task_type="CAUSAL_LM"), autocast_adapter_dtype=False)
    # Meta initialization does not inherit the base dtype in PEFT's adapter move;
    # the same explicit cast used by the real plugin makes the invariant hold.
    enforce_bf16_lora(model)
    assert all(p.is_meta for p in model.parameters())
    counts = Counter()
    tensors = 0
    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue
        assert not any(part in name for part in ("visual", "vision", "mtp"))
        assert parameter.dtype == torch.bfloat16
        counts[next(target for target in targets if "." + target + "." in name)] += parameter.numel()
        tensors += 1
    assert set(counts) == set(targets) and tensors == 800
    elements = sum(counts.values())
    assert elements == 108789760
    return {"revision": REVISION, "all_parameters_meta": True, "forward_executed": False,
        "base_parameter_elements": sum(p.numel() for p in model.parameters() if not p.requires_grad),
        "rank16_adapter_elements": elements, "rank32_adapter_elements": elements * 2,
        "adapter_tensors": tensors, "rank16_elements_by_target": dict(counts),
        "vision_and_mtp_frozen": True}


def check_vllm_cli():
    from vllm.entrypoints.openai.cli_args import make_arg_parser, validate_parsed_serve_args
    from vllm.utils.argparse_utils import FlexibleArgumentParser
    from browser_training.launch import parser, vllm_command
    serving_parser = make_arg_parser(FlexibleArgumentParser())
    results = []
    for preset in ("baseline", "lora", "lora-mtp"):
        for optional in ([], ["--tools", "--kv-dtype", "fp8", "--eager"]):
            command = vllm_command(parser().parse_args(["--preset", preset, *optional]))
            parsed = serving_parser.parse_args(command[2:])
            validate_parsed_serve_args(parsed)
            assert bool(parsed.enable_lora) == (preset != "baseline")
            assert parsed.weight_transfer_config.backend == "nccl"
            assert bool(parsed.speculative_config) == (preset == "lora-mtp")
            results.append({"preset": preset, "optional_flags": optional, "command": command})
    return {"parsed_presets": results, "engine_created": False,
        "scope": "installed CLI parsing only; MTP/LoRA execution is unqualified"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--role", choices=["sft", "rl"], required=True)
    args = p.parse_args()
    import torch
    package_names = ["torch", "transformers", "peft", "accelerate", "bitsandbytes", "flash-linear-attention"]
    package_names += ["axolotl"] if args.role == "sft" else ["trl", "vllm", "openenv", "kernels"]
    report = {"role": args.role, "gpu_used": False, "model_weights_downloaded": False,
        "torch_cuda_build": torch.version.cuda,
        "torch_compiled_architectures": torch._C._cuda_getArchFlags(),
        "packages": {name: metadata.version(name) for name in package_names}}
    report["configs"] = check_configs(args.role)
    report["peft"] = check_peft(args.role)
    report["hybrid_structure"] = check_hybrid_structure()
    if args.role == "rl":
        report["vllm_cli"] = check_vllm_cli()
    destination = Path(f"research/{args.role}-cpu-validation.json")
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
