"""Explicit opt-in live trainer logging and checkpoint sidecars."""
from pathlib import Path
import time

from transformers import TrainerCallback


class MonitoringCallback(TrainerCallback):
    def __init__(self, monitor):
        self.monitor = monitor
        self.trainer = None

    def on_train_begin(self, args, state, control, **kwargs):
        from .evaluation import validate_checkpoint_retention
        validate_checkpoint_retention(self.monitor.evaluation_enabled(), getattr(args, "save_total_limit", None))

    def on_log(self, args, state, control, logs=None, **kwargs):
        if state.is_world_process_zero:
            version = None if self.trainer is None else self.trainer.model_version
            self.monitor.log(dict(logs or {}, step=state.global_step, wall_time=time.time()), policy_version=version)
            self.monitor.emit_snapshot()

    def on_save(self, args, state, control, **kwargs):
        if state.is_world_process_zero:
            self.monitor.checkpoint(Path(args.output_dir) / f"checkpoint-{state.global_step}")

    def on_step_end(self, args, state, control, **kwargs):
        if state.is_world_process_zero and hasattr(self.trainer, "record_optimizer_step"):
            self.trainer.record_optimizer_step(state.global_step)

    def on_train_end(self, args, state, control, **kwargs):
        if state.is_world_process_zero:
            self.monitor.emit_snapshot()
