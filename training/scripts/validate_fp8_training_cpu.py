#!/usr/bin/env python3
"""Reproduce native FP8/PEFT training gates and dtypes on CPU, without downloads.

This deliberately does not run an FP8 kernel or qualify Qwen/GRPO backward.
The BF16 control dequantizes the tiny base explicitly and is labelled as such.
Run from training/: PYTHONPATH=. envs/rl/.venv/bin/python scripts/validate_fp8_training_cpu.py
"""
import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")


def check_qwen_meta():
    """Native replacement and PEFT matching on the full architecture, no weights."""
    from collections import Counter
    import torch
    import yaml
    from peft import get_peft_model, LoraConfig
    from transformers import Qwen3_5Config, Qwen3_5ForConditionalGeneration, FineGrainedFP8Config
    from transformers.integrations.finegrained_fp8 import FP8Linear
    from transformers.quantizers.quantizer_finegrained_fp8 import FineGrainedFP8HfQuantizer
    from browser_training.precision import enforce_bf16_lora
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "research/fp8-config.json").read_text())
    quantizer = FineGrainedFP8HfQuantizer(FineGrainedFP8Config(**raw.pop("quantization_config")),
        pre_quantized=True)
    settings = yaml.safe_load((root / "configs/sft_qwen38_27b_fp8_lora.yml").read_text())
    with torch.device("meta"):
        model = Qwen3_5ForConditionalGeneration(Qwen3_5Config.from_dict(raw)).to(torch.bfloat16)
        quantizer._process_model_before_weight_loading(model)
        fp8_count = sum(isinstance(m, FP8Linear) for m in model.modules())
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32,
            target_modules=settings["lora_target_modules"], task_type="CAUSAL_LM"),
            autocast_adapter_dtype=False)
        report = enforce_bf16_lora(model)
    targeted = Counter()
    base_types = Counter()
    bf16_targets = []
    for name, module in model.named_modules():
        if hasattr(module, "lora_A"):
            base = module.get_base_layer()
            assert isinstance(base, torch.nn.Linear), name
            base_types[type(base).__name__] += 1
            if not isinstance(base, FP8Linear):
                bf16_targets.append(name)
            assert not any(part in name.split(".") for part in ("visual", "vision", "mtp", "lm_head")), name
            targeted[".".join(name.split(".")[-2:])] += 1
    assert set(targeted) == set(settings["lora_target_modules"]), targeted
    assert sum(targeted.values()) == 400, targeted
    assert all(p.device.type == "meta" for p in model.parameters())
    assert report["adapter_parameter_elements"] == {"torch.bfloat16": 108789760}
    return {"status": "META_STRUCTURE_ONLY", "fp8_linears": fp8_count,
        "targeted_projection_counts": dict(targeted), "dtypes": report,
        "targeted_base_types": dict(base_types), "targets_not_replaced_by_fp8": bf16_targets,
        "weights_loaded": False, "forward_or_backward_executed": False}


def check_exclusion_loading():
    """Load a tiny synthetic hybrid checkpoint; bypass ONLY the hardware gate.

    No FP8 arithmetic is run. Known scales distinguish correct dequantization
    from a cast of raw FP8 values when the exclusion regex skips a module.
    """
    import torch
    from safetensors.torch import save_file
    from transformers import Qwen3_5Config, Qwen3_5ForConditionalGeneration
    from transformers.quantizers.quantizer_finegrained_fp8 import FineGrainedFP8HfQuantizer
    root = Path(__file__).resolve().parents[1]
    raw = json.loads((root / "research/fp8-config.json").read_text())
    quant = raw.pop("quantization_config")
    raw["text_config"].update(vocab_size=64, hidden_size=64, intermediate_size=128,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        layer_types=["linear_attention", "full_attention"], linear_key_head_dim=16,
        linear_value_head_dim=16, linear_num_key_heads=2, linear_num_value_heads=4,
        max_position_embeddings=128, bos_token_id=1, eos_token_id=2)
    raw["vision_config"].update(depth=1, hidden_size=32, intermediate_size=64,
        num_heads=4, out_hidden_size=64, num_position_embeddings=16)
    cfg = Qwen3_5Config.from_dict(raw)
    cfg._attn_implementation = "eager"
    model = Qwen3_5ForConditionalGeneration(cfg).to(torch.bfloat16)
    gate = "model.language_model.layers.0.mlp.gate_proj"
    up = "model.language_model.layers.0.mlp.up_proj"
    # All other linears remain ordinary BF16 in this synthetic fixture.
    quant["modules_to_not_convert"] = [n for n, m in model.named_modules()
        if isinstance(m, torch.nn.Linear) and n not in (gate, up)] + [gate.removesuffix("_proj")]
    model.config.quantization_config = quant
    with tempfile.TemporaryDirectory(prefix="qwen-fp8-loading-cpu-") as tmp:
        model.config.save_pretrained(tmp)
        state = model.state_dict()
        for name in (gate, up):
            state[name + ".weight"] = torch.full_like(state[name + ".weight"], 32).to(torch.float8_e4m3fn)
            state[name + ".weight_scale_inv"] = torch.tensor([[0.03125]])
        save_file(state, str(Path(tmp) / "model.safetensors"), metadata={"format": "pt"})
        # Without this explicit diagnostic substitution CPU loading dequantizes
        # everything, which cannot exercise the persistent-FP8 replacement path.
        with patch.object(FineGrainedFP8HfQuantizer, "validate_environment", return_value=None):
            try:
                loaded, info = Qwen3_5ForConditionalGeneration.from_pretrained(tmp,
                    dtype=torch.bfloat16, device_map={"": "cpu"}, attn_implementation="eager",
                    local_files_only=True, output_loading_info=True)
            except AttributeError as exc:
                # Preserve the actual native loader failure instead of patching
                # further gates until the desired result appears.
                import traceback
                return {"status": "LOADER_BLOCKED_BEFORE_WEIGHT_LOAD",
                    "scope": "Tiny synthetic Qwen hybrid checkpoint; only hardware gate bypassed",
                    "hardware_gate_substituted": True, "error": str(exc),
                    "failure_frames": [{"file": Path(f.filename).name, "function": f.name}
                        for f in traceback.extract_tb(exc.__traceback__)],
                    "official_checkpoint_weights_loaded": False,
                    "scale_application_verified": False, "forward_executed": False}
        gate_module, up_module = loaded.get_submodule(gate), loaded.get_submodule(up)
        observed = float(gate_module.weight.detach().float()[0, 0])
        return {"scope": "Tiny synthetic checkpoint load only; hardware validation bypassed; no forward",
            "hardware_gate_substituted": True, "all_other_loader_code_native": True,
            "expected_dequantized_weight": 1.0, "stored_fp8_value": 32.0, "stored_scale": 0.03125,
            "gate_class": type(gate_module).__name__, "gate_dtype": str(gate_module.weight.dtype),
            "gate_observed_value": observed, "gate_scale_applied": observed == 1.0,
            "up_class": type(up_module).__name__, "up_dtype": str(up_module.weight.dtype),
            "up_scale_loaded": float(up_module.weight_scale_inv[0, 0]),
            "missing_keys": info["missing_keys"], "unexpected_keys": info["unexpected_keys"],
            "official_checkpoint_weights_loaded": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("research/fp8-training-cpu-validation.json"))
    args = parser.parse_args()
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import FineGrainedFP8Config
    from transformers.integrations.finegrained_fp8 import FP8Linear
    from transformers.quantizers.quantizer_finegrained_fp8 import FineGrainedFP8HfQuantizer
    from transformers.trainer_utils import validate_quantization_for_training
    from browser_training.precision import enforce_bf16_lora, inspect_dtypes

    torch.set_num_threads(2)
    torch.manual_seed(42)

    class Tiny(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.proj = FP8Linear(128, 128, block_size=(128, 128))
            self.proj.weight.data = (torch.randn(128, 128) * 0.02).to(torch.float8_e4m3fn)
            self.proj.weight_scale_inv.data.fill_(1)
            self.is_quantized = True
            self.hf_quantizer = FineGrainedFP8HfQuantizer(FineGrainedFP8Config(), pre_quantized=True)

        def forward(self, x):
            return self.proj(x)

    def dtype_set(model):
        return sorted({str(p.dtype) for p in model.parameters() if p.requires_grad})

    def guard(model):
        try:
            validate_quantization_for_training(model)
        except ValueError as exc:
            return {"accepted": False, "error": str(exc)}
        return {"accepted": True}

    cases = []
    for autocast in (True, False):
        model = get_peft_model(Tiny(), LoraConfig(r=4, lora_alpha=8, lora_dropout=0,
            target_modules=["proj"], bias="none"), autocast_adapter_dtype=autocast)
        before = dtype_set(model)
        base = model.base_model.model.proj.get_base_layer()
        frozen_before = base.weight.detach().view(torch.uint8).clone()
        native_gate = guard(model)
        report = enforce_bf16_lora(model)
        assert torch.equal(base.weight.detach().view(torch.uint8), frozen_before)
        assert not base.weight.requires_grad and not base.weight_scale_inv.requires_grad
        assert dtype_set(model) == ["torch.bfloat16"]
        assert base.weight.dtype == torch.float8_e4m3fn
        cast_gate = guard(model)
        cases.append({"autocast_adapter_dtype": autocast, "initial_adapter_dtypes": before,
            "after_explicit_bf16_cast": report, "base_bytes_unchanged": True,
            "native_training_guard": native_gate, "guard_after_bf16_cast": cast_gate})

    # Demonstrate the separate, ordinary BF16 autograd path. Scale is exactly one
    # for this synthetic example. This is not a persistent-FP8 training workaround.
    base = model.base_model.model.proj.get_base_layer()
    base.weight = torch.nn.Parameter(base.weight.to(torch.bfloat16), requires_grad=False)
    x = torch.randn(2, 128, dtype=torch.bfloat16, requires_grad=True)
    loss = model(x).float().square().mean()
    loss.backward()
    assert torch.isfinite(loss) and x.grad is not None
    assert torch.isfinite(x.grad).all() and x.grad.abs().sum() > 0
    assert model.base_model.model.proj.lora_B.default.weight.grad.abs().sum() > 0
    control = inspect_dtypes(model, check_grads=True)

    cpu_quantizer = FineGrainedFP8HfQuantizer(FineGrainedFP8Config(), pre_quantized=True)
    cpu_quantizer.validate_environment()
    # On a CPU-only host the native loader asks for BF16 decompression. Do not
    # confuse such a successful CPU load with a successful FP8 training test.
    assert cpu_quantizer.quantization_config.dequantize
    sources = {}
    for obj in (FP8Linear, FineGrainedFP8HfQuantizer, validate_quantization_for_training):
        path = Path(inspect.getfile(obj))
        sources[obj.__name__] = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    result = {"status": "CPU_AUDIT_COMPLETE",
        "native_fp8_training_guard_rejected": all(not c["native_training_guard"]["accepted"] for c in cases),
        "gpu_used": False, "model_weights_downloaded": False,
        "fp8_kernel_executed": False, "fp8_backward_qualified": False,
        "qwen_hybrid_or_async_grpo_forward_executed": False,
        "qwen_meta_structure": check_qwen_meta(),
        "synthetic_exclusion_loading": check_exclusion_loading(),
        "packages": {n: importlib.metadata.version(n) for n in ("torch", "transformers", "peft", "trl")},
        "cases": cases, "cpu_loader_requests_bf16_dequantization": True,
        "explicitly_dequantized_bf16_control": {"input_gradient_nonzero": True,
            "lora_b_gradient_nonzero": True, "loss": loss.item(), "dtypes": control},
        "source_hashes": sources, "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "native_fp8_training_guard_rejected":
        result["native_fp8_training_guard_rejected"], "initial_adapter_dtypes":
        [c["initial_adapter_dtypes"] for c in cases], "fp8_backward_qualified": False}, indent=2))


if __name__ == "__main__":
    main()
