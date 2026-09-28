"""Versioned metric meanings shared by snapshots, exports and future panels."""
SCHEMA_VERSION = 1


def spec(title, unit, meaning, interpretation, *, producer=None, minimum=None, maximum=None):
    return dict(title=title, unit=unit, meaning=meaning, interpretation=interpretation,
                producer=producer, minimum=minimum, maximum=maximum)


ROW_METRICS = {
    "rows": spec("Scored training rows", "rows", "Rows emitted by native scoring, with persisted episode identity.", "One episode may produce multiple rows."),
    "admitted": spec("Rows accepted by queue gate", "rows", "Passed the native staleness decision.", "May be prefetched and never reach backward."),
    "discarded": spec("Discarded rows", "rows", "Native staleness rejection or unconsumed queue dropped on checkpoint resume.", "Does not mean the browser task failed."),
    "pending": spec("Rows awaiting admission decision", "rows", "Scored rows with no queue decision recorded.", "A queue backlog is not training progress."),
    "backward": spec("Rows completing backward", "rows", "Native training_step returned successfully.", "Gradients can still be skipped or lost before an update."),
    "applied": spec("Rows included in completed optimizer steps", "rows", "Backward returned and on_step_end reports the optimizer was not skipped.", "Does not prove nonzero parameter change or persistence in a checkpoint."),
    "skipped": spec("Rows with skipped optimizer step", "rows", "Backward completed but Accelerate reports optimizer_step_was_skipped.", "Excluded from applied rows."),
    "abandoned": spec("Admitted rows abandoned on resume", "rows", "Admitted rows without an applied/skipped event at the restored checkpoint.", "Queue lookahead and gradients are not restored."),
}


METRICS = {
    "mixed_admission": spec("Partially admitted episodes", "episodes", "All row decisions known, with some admitted and some discarded.", "Do not count these episodes as wholly admitted or wholly discarded."),
    "attempts": spec("Execution attempts", "episodes", "All terminal attempts, including retries/errors.", "Cost accounting; not the pass-rate denominator."),
    "episodes": spec("Logical episode slots", "episodes", "Latest attempt per group member.", "Retries replace a slot for outcome rates, not for cost accounting."),
    "completion": spec("Verified task completion", "fraction", "Completed goals / slots with known goal outcome and completed execution.", "Compare fixed-dev cohorts; always read counts and unknown coverage."),
    "safe_completion": spec("Intent-preserving completion", "fraction", "Verified safe completion / slots where the combined result is decidable.", "Failure or a known violation is false; otherwise incomplete evidence stays unknown."),
    "unauthorized_effect": spec("Unauthorized effects", "fraction", "Slots with a verified unauthorized effect / completed slots with known effect coverage.", "Lower is better; read beside safe completion to detect abandonment."),
    "infra_error": spec("Infrastructure errors", "fraction", "Latest slots ending in infrastructure error / logical slots.", "Excluded from policy pass-rate denominators; may invalidate apparent progress."),
    "infra_error_attempts": spec("Infrastructure-failed attempts", "attempts", "All infrastructure failures, including those followed by successful retries.", "Retry success must not hide infrastructure instability."),
    "cancelled_attempts": spec("Cancelled attempts", "attempts", "All cancelled executions, including superseded attempts.", "Use alongside retry cost and latest-slot outcomes."),
    "cancelled": spec("Cancelled episodes", "fraction", "Latest cancelled slots / logical slots.", "Not automatically policy failures."),
    "unknown_goal": spec("Unknown goal outcome", "fraction", "Completed slots lacking goal verification / completed slots.", "Missing evidence is not zero reward or success."),
    "unknown_safe": spec("Unknown safe outcome", "fraction", "Completed slots with undecidable safe completion / completed slots.", "Report next to safe completion to expose coverage gaps."),
    "admitted": spec("Admitted trajectories", "episodes", "All attempts explicitly admitted to training.", "Independent of environment outcome; pending admission is not discarded."),
    "discarded": spec("Discarded trajectories", "episodes", "All attempts explicitly discarded from training.", "Break down by recorded reason; preserve observed outcomes."),
    "pending_admission": spec("Admission pending", "episodes", "RL attempts without a final admission decision.", "Not proof of lost work; admission may arrive later."),
    "policy_age": spec("Policy age at admission", "versions", "Trainer version at decision minus generating version; mean and maximum over decisions.", "Version distance, not seconds; thresholds belong to the rollout controller."),
    "groups": spec("Observed GRPO groups", "groups", "RL groups represented by at least one terminal slot.", "Includes incomplete and invalid groups."),
    "valid_groups": spec("Complete verified GRPO groups", "groups", "All expected slots completed, with known safe outcome and finite reward.", "Group members must share task, seed and generating policy."),
    "mixed_groups": spec("Groups with reward signal", "fraction", "Nonconstant reward groups / complete verified groups.", "Potential group-relative signal, not proof of learning."),
    "all_success_groups": spec("All-success groups", "groups", "Complete verified binary-reward groups with every reward 1.", "No group-relative reward advantage."),
    "all_failure_groups": spec("All-failure groups", "groups", "Complete verified binary-reward groups with every reward 0.", "No group-relative reward advantage."),
    "admitted_groups": spec("Fully admitted groups", "groups", "Complete verified groups whose latest slots are all admitted.", "Does not assert an optimizer update consumed the group."),
    "generated_tokens": spec("Generated tokens", "tokens", "Sum across all attempts with a reported generated-token count.", "Tokenizer revision is required; report missing measurements."),
    "duration_s": spec("Episode execution time", "seconds", "Sum of measured durations across attempts, including retries.", "Concurrent episode durations are not elapsed wall time."),
    "steps": spec("Browser actions", "actions", "Sum of measured action counts across all attempts.", "Includes failed/retried work."),
    "interventions": spec("User interventions", "interventions", "Sum of reported intervention counts across attempts.", "Only a measured zero means no interventions."),
}

# Explicit allowlist. New diagnostics require a definition rather than an opaque key.
TELEMETRY = {
    "sft/train_loss": spec("SFT training loss", "nats/token", "Mean supervised-token prediction loss reported by trainer.", "Label masking and dataset revision; lower need not mean better browser behavior.", producer="trainer", minimum=0),
    "sft/validation_loss": spec("SFT validation loss", "nats/token", "Prediction loss on held-out demonstrations.", "Use with environment dev results.", producer="trainer", minimum=0),
    "rl/loss": spec("GRPO objective", "trainer loss", "Pinned trainer's reported optimization objective.", "Need not monotonically decrease.", producer="trainer"),
    "rl/entropy": spec("Policy entropy", "nats/token", "Pinned trainer's reported token-entropy diagnostic.", "Investigate collapse alongside behavioral diversity.", producer="trainer", minimum=0),
    "rl/behavior_kl": spec("Behavior-policy KL diagnostic", "trainer estimate", "Pinned trainer's behavior-policy diagnostic; source mapping must be qualified.", "Not an SFT-reference KL penalty; do not infer reference regularization.", producer="trainer"),
    "trainer/update_s": spec("Optimizer update duration", "seconds", "TRL perf/optimizer_s: timed optimizer operation, excluding forward/backward.", "Does not measure the complete training step.", producer="trainer", minimum=0),
    "trainer/step_s": spec("Trainer step wall time", "seconds", "TRL perf/step_s: wall interval between consecutive step ends.", "Includes waits; unavailable for the first step.", producer="trainer", minimum=0),
    "trainer/compute_s": spec("Forward/backward duration", "seconds", "TRL perf/fwd_bwd_s: accumulated training_step time.", "Compare with step time and rollout waits.", producer="trainer", minimum=0),
    "trainer/rollout_wait_s": spec("Trainer rollout wait", "seconds", "TRL perf/rollout_wait_s: dataset wait counter for the step.", "Large values suggest generation/environment bottlenecks.", producer="trainer", minimum=0),
    "trainer/adapter_sync_s": spec("Trainer-side weight synchronization", "seconds", "TRL perf/weight_sync_s: measured trainer synchronization operation.", "Distinct from orchestrator export-to-ready publication latency.", producer="trainer", minimum=0),
    "trainer/trained_tokens_per_s": spec("RL trained-token throughput", "tokens/second", "TRL perf/trained_tok_s_wall_clock: loss-bearing tokens / step wall time.", "Distinct from generated tokens; identify tokenizer.", producer="trainer", minimum=0),
    "trainer/forwarded_tokens_per_step": spec("Processed tokens per update", "tokens/update", "TRL batch/forwarded_tokens_per_step.", "Includes context and differs from supervised tokens.", producer="trainer", minimum=0),
    "trainer/trained_tokens_per_step": spec("Loss-bearing tokens per update", "tokens/update", "TRL batch/trained_tokens_per_step.", "Use with processed-token counts to understand masking.", producer="trainer", minimum=0),
    "trainer/learning_rate": spec("Learning rate", "optimizer learning rate", "Trainer's logged learning_rate.", "Identify schedule and optimizer in run configuration.", producer="trainer", minimum=0),
    "trainer/grad_norm": spec("Gradient norm", "L2 norm", "Trainer's logged grad_norm.", "Investigate spikes; not itself a quality measure.", producer="trainer", minimum=0),
    "trainer/peak_allocated_gib": spec("Peak PyTorch allocation", "GiB", "AuditCallback peak_vram_gib; Axolotl peak capture is preserved.", "Not total device VRAM; peak-reset scope follows the trainer.", producer="trainer", minimum=0),
    "rl/clipped_token_fraction": spec("GRPO clipping fraction", "fraction", "TRL clip_ratio/region_mean.", "Shows how often the clipping region is active.", producer="trainer", minimum=0, maximum=1),
    "policy/publication_s": spec("Adapter publication duration", "seconds", "Elapsed export-to-ready duration for one policy version.", "Declare whether export, transfer and server acknowledgement are included.", producer="orchestrator", minimum=0),
    "rollout/generated_tokens_per_s": spec("Rollout generation throughput", "tokens/second", "Generated tokens across rollout service / measurement wall interval.", "Name tokenizer, interval, and inclusion of prefill/warmup.", producer="rollout", minimum=0),
    "browser/episodes_per_min": spec("Browser throughput", "episodes/minute", "Terminal episodes across browser workers / wall interval in minutes.", "Includes errors only if declared; do not derive from summed concurrent durations.", producer="browser", minimum=0),
    "trainer/gpu_utilization_pct": spec("Trainer GPU utilization", "percent", "Device utilization sample from trainer host.", "An idle trainer may be waiting for episodes.", producer="trainer", minimum=0, maximum=100),
    "rollout/gpu_utilization_pct": spec("Rollout GPU utilization", "percent", "Device utilization sample from rollout host.", "Do not substitute the trainer device's measurement.", producer="rollout", minimum=0, maximum=100),
    "trainer/vram_gib": spec("Trainer VRAM", "GiB", "Device memory in use, sampled on trainer host.", "Not automatically a peak or PyTorch allocator measurement.", producer="trainer", minimum=0),
    "rollout/vram_gib": spec("Rollout VRAM", "GiB", "Device memory in use, sampled on rollout host.", "Separate from trainer memory.", producer="rollout", minimum=0),
    "browser/cpu_cores": spec("Browser CPU usage", "CPU cores", "Observed process-tree CPU delta; 1 = one fully used core.", "Sampled identities miss processes that exit between polls; declare the root PID.", producer="browser", minimum=0),
    "browser/ram_gib": spec("Browser memory", "GiB", "Observed process-tree proportional set size (PSS).", "Shared pages are apportioned across processes; this is not summed RSS.", producer="browser", minimum=0),
}

# Same meanings on trainer/rollout hosts; never infer one host from another.
for _role in ("trainer", "rollout"):
    for _metric in ("cpu_cores", "ram_gib"):
        TELEMETRY[f"{_role}/{_metric}"] = {**TELEMETRY[f"browser/{_metric}"],
            "producer": _role, "title": f"{_role.title()} process {_metric}",
            "meaning": ("Observed process-tree CPU delta in cores." if _metric == "cpu_cores" else
                        "Observed process-tree proportional set size (PSS) in GiB.")}

CURRICULUM = {
    "draws": spec("GRPO task draws", "groups", "Committed group-level task selections in the named window.", "Includes groups not yet started or completed; not episode throughput."),
    "requested_probability": spec("Requested family probability", "fraction", "Family probability at the latest committed draw in this window.", "Current sampling intent; not an average over historical draws."),
    "realized_fraction": spec("Realized family allocation", "fraction", "Committed draws for this family / all committed draws in the window.", "Can differ from requested probability through randomness and policy changes."),
    "evidence_groups": spec("Curriculum evidence groups", "groups", "Complete verified recent RL-train groups within the allowed policy age.", "Dev/test, unknown verification and infrastructure failures cannot increase difficulty."),
    "smoothed_pass_rate": spec("Smoothed safe-completion rate", "fraction", "(Verified safe completions + 1) / (eligible episodes + 2).", "Sampler heuristic; not a benchmark estimate or confidence bound."),
}


EVALUATION = {
    **{key: METRICS[key] for key in ("completion", "safe_completion", "unauthorized_effect", "infra_error", "unknown_safe")},
    "valid_for_comparison": spec("Fixed-suite comparison eligibility", "boolean", "Every planned case finished without infrastructure errors and has a decidable safe outcome.", "A complete file can still be ineligible; never rank a partial/unknown suite.", producer="evaluator", minimum=0, maximum=1),
    "policy_version": spec("Evaluated policy version", "version", "One requested policy version for the complete fixed suite.", "The worker must verify actual checkpoint loading; metadata matching is not a weight check.", producer="evaluator", minimum=0),
    "occurred_at": spec("Evaluation completion timestamp", "Unix seconds", "When the complete fixed-suite report was committed.", "Evaluate freshness separately from training telemetry.", producer="evaluator", minimum=0),
    "inherited": spec("Evaluation inherited on resume", "boolean", "This report belongs to an ancestor publication run.", "Useful historical evidence, not an evaluation of the newly resumed policy.", producer="evaluator", minimum=0, maximum=1),
}
