"""Design config, gated pending GPU policy-reservation validation and a project harness.

The plain Transformers FP8 loader is inference-only. A BF16 trainer is the
supported fallback; the rollout server stays official FP8. No custom FP8 backward.
"""
CONFIG = {
    "model": "Qwen/Qwen3.8-27B",
    "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    "rollout_model": "Qwen/Qwen3.8-27B-FP8",
    "environment": "browser",
    "output_dir": "outputs/rl-qwen38",
    "rank": 16,
    "alpha": 32,
    "max_steps": 50,
    "max_completion_length": 512,
    "max_tool_calling_iterations": 8,
    "num_generations": 4,
    "max_inflight_tasks": 8,
    "max_staleness": 2,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "token_budget": 0,
    "weight_sync_steps": 1,
    "learning_rate": 1e-5,
    "save_steps": 10,
    "seed": 42,
}
