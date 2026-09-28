"""Opt-in subclasses of the pinned TRL implementation; no upstream file edits."""
import hashlib
import inspect
from pathlib import Path

from trl.experimental.async_grpo.async_grpo_trainer import AsyncGRPOTrainer
from trl.experimental.async_grpo.openenv_harness import HarnessRolloutWorker, _HarnessRolloutLoop

from .outcomes import canonical, require
from .policy_compat import HASHES, is_patched
from .row_hooks import RowMetrics, RowTrainingMixin


def check_sources():
    folder = Path(inspect.getfile(AsyncGRPOTrainer)).parent
    for name in HASHES:
        require(is_patched(name, (folder / name).read_text()), "Row instrumentation requires audited pinned TRL + policy patch")


class MonitoredHarnessLoop(_HarnessRolloutLoop):
    async def _score_group(self, group):
        samples = await super()._score_group(group)
        sequences = [seq for episode in group.completions_sequences for seq in episode]
        by_episode = {}
        if not group.policy_cancelled:
            require(len(samples) == len(sequences), "Native scoring row cardinality changed")
            for sample, seq in zip(samples, sequences, strict=True):
                require(sample.input_ids == seq.input_ids and sample.completion_mask == seq.completion_mask
                        and sample.old_log_probs == seq.old_log_probs, "Native row order/content changed")
                rows = by_episode.setdefault(seq.rollout_id, [])
                row_id = f"{seq.rollout_id}:{len(rows)}"
                rows.append(dict(row_id=row_id, content_sha256=hashlib.sha256(canonical(
                    [seq.input_ids, seq.completion_mask, seq.old_log_probs]).encode()).hexdigest(),
                    loss_tokens=sum(seq.completion_mask[1:])))
                sample.metrics = RowMetrics(sample.metrics, dict(episode_id=seq.rollout_id, row_id=row_id))
        self._factory.monitor.register_group_rows(group.group_id, group.model_version, by_episode,
                                                 cancelled=bool(group.policy_cancelled))
        return samples


class MonitoredHarnessWorker(HarnessRolloutWorker):
    _loop_cls = MonitoredHarnessLoop

    def __init__(self, **kwargs):
        check_sources()
        super().__init__(**kwargs)

    def enable_shutdown_drain(self, monitor, *, grace_s=None):
        """Opt in when full browser rows can fill multiprocessing pipe buffers.

        Native stop joins the producer after the trainer stops consuming. Drain
        only during that final stop; unconsumed rows are explicitly discarded,
        never admitted/trained. Keep remaining native metrics for the run report.
        """
        self._shutdown_monitor = monitor
        self._shutdown_grace_s = float(grace_s if grace_s is not None else
                                       self._loop_kwargs.get('request_timeout', 120) + 15)
        require(0 < self._shutdown_grace_s <= 180, 'Shutdown grace must be bounded at 180 seconds')
        self.shutdown_metrics = []
        self.shutdown_discarded_rows = 0

    def stop(self):
        if not hasattr(self, '_shutdown_monitor') or self._process is None:
            return super().stop()
        import queue
        import time
        # Stop dispatch first, then allow existing HTTP requests to drain under
        # their original policy. Native stop's fixed 15s join is too short for
        # real browser responses; retain its terminate/unsafe fallback afterward.
        process = self._process
        self._stop_event_mp.set()
        deadline = time.monotonic() + self._shutdown_grace_s
        try:
            while True:
                for channel, is_sample in ((self.rollout_buffer, True), (self.metrics_queue, False)):
                    for _ in range(64):
                        try:
                            item = channel.get_nowait()
                        except queue.Empty:
                            break
                        if is_sample:
                            self._shutdown_monitor.decide_row(item.metrics.row_identity, 'discarded',
                                'shutdown_queue_not_consumed', self._model_version_value.value)
                            self.shutdown_discarded_rows += 1
                        else:
                            self.shutdown_metrics.append(item)
                if not process.is_alive() or time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        finally:
            super().stop()


class MonitoredAsyncGRPOTrainer(RowTrainingMixin, AsyncGRPOTrainer):
    def __init__(self, *args, **kwargs):
        check_sources()
        super().__init__(*args, **kwargs)
