"""Probe-only callback using Axolotl's existing public plugin interface."""
import json
from pathlib import Path
from transformers import AutoTokenizer, TrainerCallback
from .axolotl_plugin import PrecisionPlugin
from .apple_probe import evaluate


class BaselineCallback(TrainerCallback):
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def on_train_begin(self, args, state, control, model=None, **kwargs):
        assert state.global_step == 0, "This behavior probe must start from a fresh adapter"
        output = Path(args.output_dir)
        data = json.loads((output / "splits.json").read_text())
        tokenizer = AutoTokenizer.from_pretrained(self.snapshot, local_files_only=True)
        for split in ("heldout", "train_eval"):
            evaluate(model, tokenizer, data[split], output / f"before-{split}.json")


class ApplePlugin(PrecisionPlugin):
    def add_callbacks_pre_trainer(self, cfg, model):
        return super().add_callbacks_pre_trainer(cfg, model) + [BaselineCallback(cfg.base_model)]
