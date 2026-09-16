"""One audited loader-argument fix; no changes to training or rollout algorithms."""
import hashlib

ORIGINAL_SHA256 = "15951bb122c4477ba82aeeb24ad85b35dd46fd8489f244364837dc958919af99"
OLD = '            attn_implementation="kernels-community/flash-attn3",'
NEW = '            attn_implementation=model_init_kwargs.pop("attn_implementation", "kernels-community/flash-attn3"),'


def patched_source(source: str) -> str:
    """Idempotent; refuse a different upstream file or any unrelated modifications."""
    original = source.replace(NEW, OLD) if NEW in source else source
    from .policy_compat import restore_source
    normalized = restore_source("async_grpo_trainer.py", original)
    if hashlib.sha256(normalized.encode()).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Unknown TRL source. Re-audit before applying the attention patch.")
    if original.count(OLD) != 1:
        raise ValueError("Expected exactly one model-loader attention argument")
    return original.replace(OLD, NEW)


def is_patched(source: str) -> bool:
    return NEW in source and patched_source(source) == source
