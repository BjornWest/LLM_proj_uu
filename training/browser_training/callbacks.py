import json
import time
from pathlib import Path
from transformers import TrainerCallback
from .precision import enforce_bf16_lora, inspect_dtypes, inspect_optimizer


class AuditCallback(TrainerCallback):
    """Fail on dtype drift (including resume), save metrics without a hosted logger."""
    def on_train_begin(self, args, state, control, model=None, **kwargs):
        self.started = time.monotonic()
        # Trainer resume can reload adapters through PEFT's default promotion.
        # Parameter identities remain stable; AdamW32bit moments stay FP32.
        enforce_bf16_lora(model)
        inspect_dtypes(model)

    def on_pre_optimizer_step(self, args, state, control, model=None, **kwargs):
        # Requiring ALL gradients is useful for short text-only runs with our exact targets.
        inspect_dtypes(model, check_grads=True)

    def on_step_end(self, args, state, control, model=None, optimizer=None, **kwargs):
        inspect_dtypes(model)
        inspect_optimizer(optimizer)

    def on_log(self, args, state, control, logs=None, **kwargs):
        import torch
        if not state.is_world_process_zero:
            return
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        row = {"step": state.global_step, "wall_time": time.time(), **(logs or {})}
        if torch.cuda.is_available():
            # Axolotl captures and resets CUDA peaks before this callback runs.
            # Preserve its captured value instead of reporting only the reset interval.
            row["peak_vram_gib"] = max(torch.cuda.max_memory_allocated() / 2**30,
                float(row.get("memory/max_allocated (GiB)", 0)))
        with (output / "metrics.jsonl").open("a") as stream:
            stream.write(json.dumps(row, default=str) + "\n")
