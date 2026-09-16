"""Use public Axolotl plugin hooks; do not patch its trainer or quantizer."""
import json
from pathlib import Path
from pydantic import BaseModel
from axolotl.integrations.base import BasePlugin
from .precision import enforce_bf16_lora, inspect_dtypes, inspect_nf4, make_optimizer
from .callbacks import AuditCallback


class PrecisionArgs(BaseModel):
    use_cpu: bool = False


class PrecisionPlugin(BasePlugin):
    def get_input_args(self):
        return "browser_training.axolotl_plugin.PrecisionArgs"

    def get_training_args(self, cfg):
        # Axolotl 0.19 does not forward use_cpu to Transformers. Explicit CPU
        # plumbing probes need it for BF16 autocast; remote configs omit it.
        return {"use_cpu": True} if cfg.use_cpu else {}

    def post_model_load(self, cfg, model):
        enforce_bf16_lora(model)
        report = inspect_dtypes(model, require_fp8="FP8" in cfg.base_model)
        if cfg.adapter == "qlora":
            report["nf4"] = inspect_nf4(model)
        output = Path(cfg.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "parameter-dtypes.json").write_text(json.dumps(report, indent=2))

    def post_trainer_create(self, cfg, trainer):
        # This hook is called by axolotl.train. In 0.19.0 the plugin manager's
        # create_optimizer method has no caller, so defining it alone is ineffective.
        if trainer.lr_scheduler is not None:
            raise RuntimeError("Scheduler already initialized; cannot replace its optimizer")
        trainer.optimizer = make_optimizer(trainer.model, cfg.learning_rate, cfg.weight_decay or 0.0)

    def add_callbacks_pre_trainer(self, cfg, model):
        return [AuditCallback()]
