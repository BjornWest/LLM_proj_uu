"""Explicit mapping of pinned TRL/Axolotl callback logs; no inferred policy IDs.

Sources: TRL a04ffd337108285002df29d9ae73ef7e855e03f1
AsyncGRPOTrainer.compute_loss, _log_step_metrics, log, _sync_weights_to_vllm;
project AuditCallback.on_log and saved SFT/RL qualification logs.
Unknown upstream keys remain in the original logs, not silently reinterpreted.
"""
import hashlib

from .outcomes import canonical, require, validate

COMMON = {"learning_rate": "trainer/learning_rate", "grad_norm": "trainer/grad_norm",
          "peak_vram_gib": "trainer/peak_allocated_gib"}
RL = {"loss": "rl/loss", "entropy": "rl/entropy", "kl": "rl/behavior_kl",
      "clip_ratio/region_mean": "rl/clipped_token_fraction", "perf/optimizer_s": "trainer/update_s",
      "perf/step_s": "trainer/step_s", "perf/fwd_bwd_s": "trainer/compute_s",
      "perf/rollout_wait_s": "trainer/rollout_wait_s", "perf/weight_sync_s": "trainer/adapter_sync_s",
      "perf/trained_tok_s_wall_clock": "trainer/trained_tokens_per_s",
      "batch/forwarded_tokens_per_step": "trainer/forwarded_tokens_per_step",
      "batch/trained_tokens_per_step": "trainer/trained_tokens_per_step"}
SFT = {"loss": "sft/train_loss", "eval_loss": "sft/validation_loss"}


def trainer_event(row, *, kind, source_id, row_number, context, policy_version=None, checkpoint_id=None):
    """Normalize one AuditCallback row, keeping original clock and step.

    source_id should be an immutable log-file hash for offline import, or a
    producer-generation identity for a live stream. row_number must be stable on
    redelivery. Null policy/checkpoint means unknown, never global_step guessed
    as a policy version. An unrelated row yields None.
    """
    require(kind in {"sft", "rl"}, "Use sft or rl")
    require(isinstance(source_id, str) and source_id, "source_id required")
    require(type(row_number) is int and row_number >= 0, "Invalid row_number")
    mapping = {**COMMON, **(RL if kind == "rl" else SFT)}
    values = {target: row[source] for source, target in mapping.items() if row.get(source) is not None}
    if not values:
        return None
    event = dict(id="trainer-" + hashlib.sha256(canonical([source_id, row_number]).encode()).hexdigest(),
                 kind="telemetry", producer="trainer", occurred_at=row["wall_time"],
                 payload=dict(step=row["step"], axis="optimizer_step", policy_version=policy_version,
                              checkpoint_id=checkpoint_id, context=f"{context}; source={source_id}; row={row_number}; kind={kind}",
                              values=values))
    validate(event)
    return event
