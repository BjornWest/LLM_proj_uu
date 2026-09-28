"""Observers for the hash-audited TRL queue, collator and training-step boundary."""
from .outcomes import require


class RowMetrics(dict):
    """Native scalar metrics unchanged; a picklable attribute carries identity."""
    def __init__(self, values, identity):
        super().__init__(values)
        self.row_identity = identity


class ObservedQueue:
    def __init__(self, queue, monitor, version_fn, max_staleness):
        self.queue, self.monitor, self.version_fn, self.max_staleness = queue, monitor, version_fn, max_staleness
        self.sample = None

    def get(self, *args, **kwargs):
        self.sample = self.queue.get(*args, **kwargs)
        return self.sample

    def __getattr__(self, name):
        return getattr(self.queue, name)

    def version_for_decision(self):
        # This is the same single version read the native __iter__ uses to branch.
        version = self.version_fn()
        sample = self.sample
        require(sample is not None and isinstance(sample.metrics, RowMetrics), "Missing native row identity")
        require(version >= sample.model_version, "Trainer policy precedes generated policy")
        stale = version - sample.model_version > self.max_staleness
        self.monitor.decide_row(sample.metrics.row_identity, "discarded" if stale else "admitted",
                                "staleness" if stale else "native_queue_gate", version)
        return version


class ObservedCollator:
    def __init__(self, delegate):
        self.delegate, self.next_batch, self.batches = delegate, 0, {}

    def __call__(self, examples):
        import torch
        require(len(examples) == 1 and len(examples[0]) == 1, "Row tracking currently supports one trainer rank")
        identities = [e["metrics"].row_identity for e in examples[0][0]]
        result = self.delegate(examples)
        batch_id = self.next_batch
        self.next_batch += 1
        self.batches[batch_id] = identities
        # Numeric metadata survives Accelerate's lookahead/concatenation/scatter.
        # Removed before native training_step; never reaches the model or loss.
        result["_monitoring_batch"] = torch.tensor([[batch_id]], dtype=torch.int64)
        return result


class RowTrainingMixin:
    """Delegate all mathematical work to the native trainer via super()."""
    def enable_row_monitoring(self, monitor):
        require(self.accelerator.num_processes == 1, "Row monitoring supports one trainer process")
        self.row_monitor, self._row_accumulated = monitor, []

    def get_train_dataloader(self):
        loader = super().get_train_dataloader()
        if not hasattr(self, "row_monitor"):
            return loader
        dataset = self._rollout_dataset
        observed = ObservedQueue(dataset.queue, self.row_monitor, dataset.model_version_fn, dataset.max_staleness)
        dataset.queue, dataset.model_version_fn = observed, observed.version_for_decision
        base = getattr(loader, "base_dataloader", loader)
        self._row_collator = ObservedCollator(base.collate_fn)
        base.collate_fn = self._row_collator
        return loader

    def training_step(self, model, inputs, num_items_in_batch=None):
        if not hasattr(self, "row_monitor"):
            return super().training_step(model, inputs, num_items_in_batch)
        inputs = dict(inputs)
        marker = inputs.pop("_monitoring_batch")
        require(marker.numel() == 1, "Unexpected multi-rank monitoring batch")
        identities = self._row_collator.batches.pop(int(marker.item()))
        result = super().training_step(model, inputs, num_items_in_batch)
        self.row_monitor.use_rows(identities, "backward", self.state.global_step + 1)
        self._row_accumulated.extend(identities)
        return result

    def record_optimizer_step(self, step):
        if not hasattr(self, "row_monitor"):
            return
        stage = "skipped" if self.accelerator.optimizer_step_was_skipped else "applied"
        self.row_monitor.use_rows(self._row_accumulated, stage, step)
        self._row_accumulated.clear()

    def _save_checkpoint(self, model, trial):
        if not hasattr(self, "row_monitor"):
            return super()._save_checkpoint(model, trial)
        # Native save reads _trained_groups to compute its first-untrained cursor.
        # Its collator populates that set before backward (including lookahead).
        # Substitute only for serialization; do not change the collator/stop loop.
        collated = self._trained_groups
        self._trained_groups = set(self.row_monitor.applied_native_groups())
        try:
            return super()._save_checkpoint(model, trial)
        finally:
            self._trained_groups = collated
