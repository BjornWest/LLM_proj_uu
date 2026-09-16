#!/usr/bin/env python3
"""Qualify a minimal NF4 initialization fix against the actual TRL constructor.

Loads a tiny saved hybrid model with the native loader. The proposed source edit
runs in an isolated module; installed TRL is NOT modified. No rollout or GPU.
"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["VLLM_NO_USAGE_STATS"] = "1"
os.environ["USE_HUB_KERNELS"] = "NO"  # Expose upstream functions for this CPU reference probe.
os.environ.setdefault("OMP_NUM_THREADS", "2")

import hashlib
import importlib
import json
from pathlib import Path
import queue
import sys
import tempfile
from types import ModuleType, SimpleNamespace


from browser_training.qlora_compat import candidate_module


def native_loss_probe(trainer):
    import torch
    from browser_training.precision import enforce_bf16_lora, inspect_dtypes, inspect_nf4, make_optimizer, inspect_optimizer
    trainer.current_gradient_accumulation_steps = 1
    # Trainer.train() normally does this. CPU bitsandbytes eval can repack
    # weights for inference, so a manual compute_loss probe must enter train mode.
    trainer.model.train()
    enforce_bf16_lora(trainer.model)
    optimizer = make_optimizer(trainer.model, 1e-4)
    ids = torch.randint(0, 64, (1, 8))
    mask = torch.tensor([[0, 0, 0, 0, 1, 1, 1, 1]])
    positions = torch.arange(8).unsqueeze(0)
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        behavior = trainer.model(input_ids=ids, position_ids=positions, labels=ids,
            completion_mask=mask, use_cache=False)["log_probs"]
    inputs = dict(input_ids=ids, attention_mask=torch.ones_like(ids), completion_mask=mask,
        position_ids=positions, old_log_probs=torch.cat([torch.zeros(1, 1), behavior], dim=1),
        advantages=torch.ones_like(ids), global_n_tokens=torch.tensor([4]),
        global_n_forward_tokens=torch.tensor([8]), mean_seq_len=torch.tensor([8.0]))
    frozen = {n: p.detach().clone() for n, p in trainer.model.named_parameters() if not p.requires_grad}
    losses = []
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cpu", dtype=torch.bfloat16):
            loss = trainer.compute_loss(trainer.model, inputs)
        assert torch.isfinite(loss)
        loss.backward()
        gradients = inspect_dtypes(trainer.model, check_grads=True)
        optimizer.step()
        inspect_optimizer(optimizer)
        losses.append(loss.item())
    assert all(torch.equal(p, frozen[n]) for n, p in trainer.model.named_parameters() if n in frozen)
    return dict(losses=losses, gradients=gradients,
        nf4=inspect_nf4(trainer.model), frozen_base_unchanged=True,
        scope="native compute_loss + two AdamW32bit steps; synthetic tokens/advantages, no rollout engine")


def main():
    import torch
    from transformers import AutoConfig, AutoTokenizer, BitsAndBytesConfig, Qwen3_5Config, Qwen3_5ForConditionalGeneration
    from peft import LoraConfig
    from datasets import Dataset
    from browser_training.precision import inspect_nf4, inspect_dtypes, enforce_bf16_lora
    from check_adapter_dtypes import check
    torch.set_num_threads(2)
    torch.manual_seed(42)
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
    installed, candidate, evidence = candidate_module()
    tokenizer = AutoTokenizer.from_pretrained(".cache/qwen38-tokenizer", local_files_only=True)
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        llm_int8_skip_modules=["model.visual", "lm_head", "mtp"])
    import yaml
    targets = yaml.safe_load(Path("configs/sft_qwen38_27b_nf4_qlora.yml").read_text())["lora_target_modules"]
    with tempfile.TemporaryDirectory(prefix="trl-nf4-init-") as tmp:
        base = Path(tmp) / "base"
        Qwen3_5ForConditionalGeneration(cfg).to(torch.bfloat16).save_pretrained(base)

        def construct(trainer_class, name):
            args = installed.AsyncGRPOConfig(output_dir=str(Path(tmp) / name), use_cpu=True,
                bf16=True, dtype="bfloat16", report_to="none", max_steps=1,
                per_device_train_batch_size=1, num_generations=2, token_budget=0,
                gradient_checkpointing_kwargs={"use_reentrant": False},
                model_init_kwargs={"quantization_config": quantization,
                    "attn_implementation": "eager", "local_files_only": True})
            return trainer_class(model=str(base), args=args, processing_class=tokenizer,
                train_dataset=Dataset.from_dict({"prompt": [[{"role": "user", "content": "click"}]]}),
                peft_config=LoraConfig(r=4, lora_alpha=8, target_modules=targets, task_type="CAUSAL_LM"),
                rollout_worker=SimpleNamespace(rollout_buffer=queue.Queue(), metrics_queue=queue.Queue()),
                weight_transfer=object())  # Public injection; prevents server contact during init only.

        try:
            construct(installed.AsyncGRPOTrainer, "stock")
        except RuntimeError as exc:
            assert "floating point" in str(exc)
            evidence["unmodified_constructor_failure"] = str(exc)
        else:
            raise AssertionError("Pinned initialization blocker unexpectedly disappeared")
        trainer = construct(candidate.AsyncGRPOTrainer, "candidate")
        # Before our usual safety cast, prove PEFT did not promote adapters.
        evidence["dtypes_before_explicit_cast"] = inspect_dtypes(trainer.model)
        enforce_bf16_lora(trainer.model)
        evidence["nf4"] = inspect_nf4(trainer.model)
        assert trainer._is_vlm
        assert all(not p.requires_grad for n, p in trainer.model.named_parameters() if ".visual." in n)
        output = Path(tmp) / "adapter"
        trainer.model.save_pretrained(output)
        evidence["saved_adapter"] = check(output)
        evidence["training_arguments_serialize"] = bool(trainer.args.to_json_string())
        # Select upstream PyTorch reference functions explicitly for CPU only.
        # No FLA kernels, source changes, or production dispatch changes.
        import inspect
        from contextlib import ExitStack
        from unittest.mock import patch
        from transformers.models.qwen3_5 import modeling_qwen3_5 as hybrid_module
        with ExitStack() as stack:
            selected = []
            for name in ("torch_chunk_gated_delta_rule", "torch_recurrent_gated_delta_rule",
                         "causal_conv1d_fn", "causal_conv1d_update"):
                fn = inspect.unwrap(getattr(hybrid_module, name))
                assert fn.__module__ == hybrid_module.__name__
                stack.enter_context(patch.object(hybrid_module, name, fn))
                selected.append(name)
            evidence["hybrid_cpu_reference_grpo_loss"] = native_loss_probe(trainer)
            evidence["hybrid_cpu_reference_grpo_loss"]["selected_reference_functions"] = selected
        # Also exercise ordinary attention without replacing any kernel dispatch.
        from transformers import Qwen3Config, Qwen3ForCausalLM
        from browser_training.precision import make_optimizer, inspect_optimizer
        base = Path(tmp) / "ordinary-base"
        small = Qwen3Config(vocab_size=64, hidden_size=64, intermediate_size=128,
            num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2, head_dim=16)
        small._attn_implementation = "eager"
        Qwen3ForCausalLM(small).to(torch.bfloat16).save_pretrained(base)
        trainer = construct(candidate.AsyncGRPOTrainer, "ordinary")
        evidence["ordinary_qwen_native_grpo_loss"] = native_loss_probe(trainer)
    evidence.update(status="PASS", gpu_used=False, model_loader_substituted=False,
        real_trainer_constructor=True, model="tiny random hybrid Qwen3.5/3.8 architecture",
        attention_implementation="eager, explicit PyTorch reference DeltaNet functions", rollout_server="injected inactive stubs",
        hybrid_reference_backward_tested=True, hybrid_gpu_backward_tested=False, production_qlora_enabled=False,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    Path("research/qlora-trl-init-validation.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
