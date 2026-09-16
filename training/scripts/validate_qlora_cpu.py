#!/usr/bin/env python3
"""Bounded NF4 research probe: tiny random models, CPU only, no Hub downloads.

Checks native bitsandbytes/PEFT backward, Qwen hybrid load/init behavior, and
metadata-only 27B weight-storage estimates. Does not qualify AsyncGRPO training.
"""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["VLLM_NO_USAGE_STATS"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "2")


def quantization():
    import torch
    from transformers import BitsAndBytesConfig
    return BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
        llm_int8_skip_modules=["lm_head", "model.visual", "in_proj_a", "in_proj_b"])


def parameter_storage(model):
    result = Counter()
    for parameter in model.parameters():
        result[str(parameter.dtype)] += parameter.numel() * parameter.element_size()
    return dict(result)


def ordinary_qwen_probe():
    import torch
    import bitsandbytes as bnb
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel
    from browser_training.precision import enforce_bf16_lora, inspect_dtypes, make_optimizer, inspect_optimizer
    torch.manual_seed(42)
    config = Qwen3Config(vocab_size=64, hidden_size=64, intermediate_size=128,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16)
    config._attn_implementation = "eager"
    with tempfile.TemporaryDirectory(prefix="qwen-nf4-cpu-") as folder:
        base = Path(folder) / "base"
        Qwen3ForCausalLM(config).to(torch.bfloat16).save_pretrained(base)
        model = Qwen3ForCausalLM.from_pretrained(base, dtype=torch.bfloat16,
            device_map={"": "cpu"}, quantization_config=quantization(), attn_implementation="eager")
        modules = [m for m in model.modules() if isinstance(m, bnb.nn.Linear4bit)]
        assert modules and all(m.weight.dtype == torch.uint8 for m in modules)
        before = parameter_storage(model)
        model = prepare_model_for_kbit_training(model, gradient_checkpointing_kwargs={"use_reentrant": False})
        after = parameter_storage(model)
        model = get_peft_model(model, LoraConfig(r=4, lora_alpha=8, lora_dropout=0,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            task_type="CAUSAL_LM"), autocast_adapter_dtype=False)
        enforce_bf16_lora(model)
        optimizer = make_optimizer(model, 1e-3)
        frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
        losses = []
        ids = torch.randint(0, 64, (1, 16))
        for _ in range(2):
            with torch.autocast("cpu", dtype=torch.bfloat16):
                loss = model(input_ids=ids, labels=ids, use_cache=False).loss
            assert torch.isfinite(loss)
            loss.backward()
            inspect_dtypes(model, check_grads=True)
            assert all(p.grad.dtype == torch.bfloat16 for p in model.parameters() if p.requires_grad)
            optimizer.step()
            inspect_optimizer(optimizer)
            optimizer.zero_grad(set_to_none=True)
            losses.append(loss.item())
        assert all(torch.equal(p, frozen[n]) for n, p in model.named_parameters() if n in frozen)
        adapter = Path(folder) / "adapter"
        model.save_pretrained(adapter)
        base_model = Qwen3ForCausalLM.from_pretrained(base, dtype=torch.bfloat16,
            device_map={"": "cpu"}, quantization_config=quantization(), attn_implementation="eager")
        reloaded = PeftModel.from_pretrained(base_model, adapter, is_trainable=True, autocast_adapter_dtype=False)
        inspect_dtypes(reloaded)
        return dict(status="PASS", quantized_linears=len(modules), packed_dtype="uint8", compute_dtype="bfloat16",
            losses=losses, adapter_dtype="bfloat16", gradient_dtype="bfloat16", optimizer_moments="float32",
            frozen_base_unchanged=True, adapter_reload_verified=True,
            base_parameter_bytes_before_kbit_prepare=before, base_parameter_bytes_after_kbit_prepare=after)


def hybrid_probe():
    import torch
    import bitsandbytes as bnb
    from transformers import AutoConfig, Qwen3_5Config, Qwen3_5ForConditionalGeneration, Qwen3_5ForCausalLM
    from peft import prepare_model_for_kbit_training, LoraConfig, get_peft_model
    from browser_training.precision import enforce_bf16_lora
    raw = AutoConfig.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True).to_dict()
    raw["text_config"].update(vocab_size=64, hidden_size=64, intermediate_size=128,
        num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16,
        layer_types=["linear_attention", "full_attention"], linear_key_head_dim=16,
        linear_value_head_dim=16, linear_num_key_heads=2, linear_num_value_heads=4,
        max_position_embeddings=128, bos_token_id=1, eos_token_id=2)
    raw["vision_config"].update(depth=1, hidden_size=32, intermediate_size=64, num_heads=4,
        out_hidden_size=64, num_position_embeddings=16)
    cfg = Qwen3_5Config.from_dict(raw)
    cfg._attn_implementation = "eager"
    with tempfile.TemporaryDirectory(prefix="qwen-hybrid-nf4-") as folder:
        Qwen3_5ForConditionalGeneration(cfg).to(torch.bfloat16).save_pretrained(folder)
        model = Qwen3_5ForConditionalGeneration.from_pretrained(folder, dtype=torch.bfloat16,
            quantization_config=quantization(), device_map={"": "cpu"}, attn_implementation="eager")
        quantized = [n for n, m in model.named_modules() if isinstance(m, bnb.nn.Linear4bit)]
        assert quantized and not any("visual" in n or "lm_head" in n for n in quantized), quantized
        from trl.experimental.async_grpo import AsyncGRPOTrainer, AsyncGRPOConfig
        from unittest.mock import patch
        try:
            # Execute the real constructor through its VLM initialization. The
            # loader returns the already-loaded CPU model to avoid FA2/CUDA.
            with patch("trl.experimental.async_grpo.async_grpo_trainer.create_model_from_path", return_value=model):
                AsyncGRPOTrainer(model=folder, args=AsyncGRPOConfig(
                    output_dir=str(Path(folder) / "output"), use_cpu=True, report_to="none"),
                    peft_config=LoraConfig(r=4, target_modules=["q_proj"], task_type="CAUSAL_LM"))
        except RuntimeError as exc:
            assert "floating point" in str(exc)
            init_error = str(exc)
        else:
            raise AssertionError("Expected pinned TRL integer-weight unfreeze to fail")
        model = prepare_model_for_kbit_training(model, gradient_checkpointing_kwargs={"use_reentrant": False})
        targets = ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj",
            "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj", "linear_attn.in_proj_qkv",
            "linear_attn.in_proj_z", "linear_attn.out_proj"]
        model = get_peft_model(model, LoraConfig(r=4, lora_alpha=8, lora_dropout=0,
            target_modules=targets, task_type="CAUSAL_LM"), autocast_adapter_dtype=False)
        dtypes = enforce_bf16_lora(model)
        assert all(not p.requires_grad for n, p in model.named_parameters() if ".visual." in n)
        try:
            with torch.autocast("cpu", dtype=torch.bfloat16):
                model(input_ids=torch.randint(0, 64, (1, 8)), use_cache=False)
        except Exception as exc:
            forward = dict(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
        else:
            forward = dict(status="FORWARD_PASS", backward_tested=False)
        text_only, load_info = Qwen3_5ForCausalLM.from_pretrained(folder, dtype=torch.bfloat16,
            quantization_config=quantization(), device_map={"": "cpu"}, attn_implementation="eager",
            output_loading_info=True)
        assert not load_info["missing_keys"], load_info
        assert not any("visual" in name for name, _ in text_only.named_parameters())
        assert text_only.config.get_text_config() is text_only.config
        # Confirm prefix conversion copied packed text weights, not just that a
        # class instantiated successfully. PEFT wraps them under base_layer.
        wrapped = model.base_model.model.model.language_model
        for name, module in text_only.model.named_modules():
            if isinstance(module, bnb.nn.Linear4bit):
                expected = wrapped.get_submodule(name).get_base_layer()
                assert torch.equal(module.weight, expected.weight), name
        return dict(status="EXPECTED_TRL_INIT_BLOCKER_REPRODUCED", quantized_modules=quantized,
            trl_vlm_unfreeze_error=init_error, manual_kbit_prepare_and_lora_wrap="PASS",
            native_trainer_constructor_executed=True, trainer_model_loader_substituted=True,
            dtypes=dtypes, hybrid_forward=forward,
            text_only_loading=dict(status="PASS", missing_keys=sorted(load_info["missing_keys"]),
                unexpected_keys=sorted(load_info["unexpected_keys"]), vision_allocated=False,
                note="Avoids VLM branch; AsyncGRPO construction and vLLM adapter name mapping not qualified"))


def storage_estimate():
    import torch
    from accelerate import init_empty_weights
    from transformers import AutoConfig, Qwen3_5ForConditionalGeneration
    cfg = AutoConfig.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
    with init_empty_weights():
        model = Qwen3_5ForConditionalGeneration(cfg)
    total = sum(p.numel() for p in model.parameters())
    quantized = sum(m.weight.numel() for n, m in model.named_modules() if isinstance(m, torch.nn.Linear)
        and n.startswith("model.language_model.") and not n.endswith(("in_proj_a", "in_proj_b")))
    other = total - quantized
    # NF4 packed data + one uint8 first-level scale per 64 elements + nested FP32
    # scale per 256 first-level scales. Alignment/codebooks are small omitted terms.
    packed_bytes = quantized * (0.5 + 1 / 64 + 4 / (64 * 256))
    return dict(scope="metadata-only storage estimate; excludes activations, workspaces and allocator overhead",
        base_elements=total, quantized_elements=quantized, unquantized_elements=other,
        frozen_nf4_with_bf16_exceptions_gib=(packed_bytes + other * 2) / 2**30,
        frozen_nf4_after_standard_kbit_fp32_upcast_gib=(packed_bytes + other * 4) / 2**30,
        rank16_adapter_grad_fp32_moments_gib=108789760 * 12 / 2**30,
        rank32_adapter_grad_fp32_moments_gib=217579520 * 12 / 2**30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("research/qlora-cpu-validation.json"))
    args = parser.parse_args()
    report = dict(gpu_used=False, model_weights_downloaded=False, async_grpo_qualified=False,
        packages={n: importlib.metadata.version(n) for n in ("torch", "transformers", "peft", "bitsandbytes", "trl")},
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    for name, fn in (("ordinary_qwen", ordinary_qwen_probe), ("hybrid_qwen", hybrid_probe), ("storage", storage_estimate)):
        report[name] = fn()
        print(name, json.dumps(report[name]), flush=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
