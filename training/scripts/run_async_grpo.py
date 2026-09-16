#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="configs/rl_smoke.py")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--steps", type=int)
    p.add_argument("--inflight", type=int)
    p.add_argument("--group-size", type=int)
    p.add_argument("--grad-accum", type=int)
    p.add_argument("--max-staleness", type=int)
    p.add_argument("--output")
    p.add_argument("--resume")
    p.add_argument("--sft-adapter")
    p.add_argument("--attention", choices=["kernels-community/flash-attn3", "flash_attention_2"],
                   default=os.environ.get("RL_ATTENTION", "kernels-community/flash-attn3"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.resume and args.sft_adapter:
        p.error("Choose --resume or --sft-adapter, not both")
    if args.resume and not (Path(args.resume) / "rollout_state.json").is_file():
        p.error("Resume requires an AsyncGRPO checkpoint with rollout_state.json")
    cfg = dict(runpy.run_path(args.config)["CONFIG"])
    for key, value in {"max_steps": args.steps, "max_inflight_tasks": args.inflight,
                       "num_generations": args.group_size, "gradient_accumulation_steps": args.grad_accum,
                       "max_staleness": args.max_staleness, "output_dir": args.output}.items():
        if value is not None:
            cfg[key] = value
    if cfg["per_device_train_batch_size"] != 1 or cfg["token_budget"] != 0:
        p.error("Hybrid baseline requires one sample per packed row: microbatch=1, token_budget=0")
    if cfg["num_generations"] < 2 or cfg["max_inflight_tasks"] < cfg["num_generations"]:
        p.error("Use group size >=2 and inflight >= group size")
    cfg["output_dir"] = str(Path(cfg["output_dir"]).resolve())
    if args.dry_run:
        print(json.dumps({**cfg, "attention": args.attention}, indent=2))
        return
    if cfg["environment"] != "one-turn-mock":
        p.error("BLOCKED: policy reservations pass local tests, but GPU/vLLM qualification and a production browser harness factory are still required. See NOTES.md.")
    import torch
    if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 10 and args.attention != "flash_attention_2":
        p.error("Blackwell requires the opt-in rl-sm120 compatibility build and --attention flash_attention_2; see NOTES.md.")
    import inspect
    from datasets import Dataset
    from peft import LoraConfig, set_peft_model_state_dict
    from peft.utils.save_and_load import load_peft_weights
    from trl.experimental.async_grpo import AsyncGRPOTrainer, AsyncGRPOConfig
    from browser_training.policy_compat import HASHES, is_patched as policy_is_patched
    trl_folder = Path(inspect.getfile(AsyncGRPOTrainer)).parent
    for name in HASHES:
        if not policy_is_patched(name, (trl_folder / name).read_text()):
            p.error("Apply scripts/patch_trl_policy.py --apply before starting RL")
    from browser_training.environment import OneTurnMockEnv
    from browser_training.callbacks import AuditCallback
    from browser_training.precision import enforce_bf16_lora, make_optimizer
    from browser_training.provenance import capture
    if "peft_config" not in inspect.signature(AsyncGRPOTrainer).parameters:
        raise RuntimeError("Wrong TRL: install the locked source commit, not the released package")
    if args.attention == "flash_attention_2":
        from browser_training.attention_compat import is_patched
        if not is_patched(Path(inspect.getfile(AsyncGRPOTrainer)).read_text()):
            p.error("FA2 requires scripts/patch_trl_attention.py --apply (or bootstrap rl-sm120)")
        import flash_attn  # fail before model loading if the compiled extension cannot import
    model, revision = cfg.pop("model"), cfg.pop("revision")
    rank, alpha = cfg.pop("rank"), cfg.pop("alpha")
    cfg.pop("environment")
    cfg.pop("rollout_model")
    if Path(cfg["output_dir"]).exists() and not args.resume:
        p.error("Choose a new output directory or --resume")
    targets = ["self_attn.q_proj", "self_attn.k_proj", "self_attn.v_proj", "self_attn.o_proj",
               "mlp.gate_proj", "mlp.up_proj", "mlp.down_proj"]
    if "3.8" in model:
        targets += ["linear_attn.in_proj_qkv", "linear_attn.in_proj_z", "linear_attn.out_proj"]
    model_kwargs = {"revision": revision}
    if args.attention == "flash_attention_2":
        model_kwargs["attn_implementation"] = args.attention
    training_args = AsyncGRPOConfig(**cfg, dtype="bfloat16", bf16=True,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        model_init_kwargs=model_kwargs, vllm_server_base_url=args.server,
        temperature=1.0, top_p=1.0, top_k=0, chat_template_kwargs={"enable_thinking": False},
        logging_steps=1, save_total_limit=3, report_to="none", log_completions=False)
    trainer = AsyncGRPOTrainer(model=model, args=training_args,
        peft_config=LoraConfig(r=rank, lora_alpha=alpha, lora_dropout=0, bias="none",
                               target_modules=targets, task_type="CAUSAL_LM"),
        train_dataset=Dataset.from_list([{"prompt": [{"role": "user", "content": ""}], "seed": i}
                                        for i in range(32)]),
        environment_factory=OneTurnMockEnv, callbacks=[AuditCallback()])
    # AsyncGRPO doesn't expose autocast_adapter_dtype. Public parameter conversion,
    # before optimizer creation/first sync, explicitly undoes PEFT's promotion.
    if args.sft_adapter:
        adapter_cfg = json.loads((Path(args.sft_adapter) / "adapter_config.json").read_text())
        if adapter_cfg["r"] != rank or set(adapter_cfg["target_modules"]) != set(targets):
            raise ValueError("SFT adapter rank/targets do not match RL config")
        result = set_peft_model_state_dict(trainer.model, load_peft_weights(args.sft_adapter), adapter_name="default")
        if result.unexpected_keys:
            raise ValueError(result.unexpected_keys)
    enforce_bf16_lora(trainer.model)
    if not trainer._lora_sync:
        raise RuntimeError("Server did not select adapter-only sync; refuse merged/full-weight transfer")
    trainer.optimizer = make_optimizer(trainer.model, cfg["learning_rate"])
    capture(cfg["output_dir"], {**cfg, "model": model, "revision": revision, "rank": rank, "alpha": alpha,
                               "sft_adapter": args.sft_adapter, "resume_from_checkpoint": args.resume,
                               "attention": args.attention,
                               "trl_policy_sources": {name: hashlib.sha256((trl_folder / name).read_bytes()).hexdigest()
                                                      for name in HASHES},
                               "trl_trainer_sha256": hashlib.sha256(
                                   Path(inspect.getfile(AsyncGRPOTrainer)).read_bytes()).hexdigest()})
    trainer.train(resume_from_checkpoint=args.resume)
    trainer.save_model(str(Path(cfg["output_dir"]) / "adapter-final"))
    checkpoints = list(Path(cfg["output_dir"]).glob("checkpoint-*/adapter_model.safetensors"))
    if not checkpoints:
        raise RuntimeError("Training returned without an adapter checkpoint")


if __name__ == "__main__":
    main()
