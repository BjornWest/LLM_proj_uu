"""Audited NF4 initialization/BF16 resume; executes in isolation, leaves TRL files intact."""
import hashlib
import importlib
from pathlib import Path
import sys
from types import ModuleType


def candidate_module():
    installed = importlib.import_module("trl.experimental.async_grpo.async_grpo_trainer")
    source = Path(installed.__file__).read_text()
    from browser_training.policy_compat import restore_source, HASHES
    from browser_training.attention_compat import NEW, OLD
    if NEW not in source:
        raise RuntimeError("Apply scripts/patch_trl_attention.py --apply first; the probe needs an explicit attention choice")
    original = restore_source("async_grpo_trainer.py", source).replace(NEW, OLD)
    assert hashlib.sha256(original.encode()).hexdigest() == HASHES["async_grpo_trainer.py"]
    edits = [
        ("class AsyncGRPOTrainer(_BaseTrainer):",
         "from browser_training.precision import BF16AdapterResumeMixin\n\n"
         "class AsyncGRPOTrainer(BF16AdapterResumeMixin, _BaseTrainer):"),
        ("        if self._is_vlm:\n", "        if self._is_vlm and not getattr(model, 'is_loaded_in_4bit', False):\n"),
        ("            model = get_peft_model(model, peft_config)",
         "            if getattr(model, 'is_loaded_in_4bit', False):\n"
         "                from peft import prepare_model_for_kbit_training\n"
         "                model = prepare_model_for_kbit_training(\n"
         "                    model, use_gradient_checkpointing=args.gradient_checkpointing,\n"
         "                    gradient_checkpointing_kwargs=args.gradient_checkpointing_kwargs)\n"
         "            model = get_peft_model(model, peft_config, autocast_adapter_dtype=False)"),
    ]
    candidate = source
    for before, after in edits:
        assert candidate.count(before) == 1, before
        candidate = candidate.replace(before, after)
    name = "trl.experimental.async_grpo._local_nf4_init_probe"
    module = ModuleType(name)
    module.__package__ = "trl.experimental.async_grpo"
    module.__file__ = installed.__file__
    sys.modules[name] = module
    exec(compile(candidate, "<audited-nf4-init-candidate>", "exec"), module.__dict__)
    from . import precision
    return installed, module, {"installed_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "precision_sha256": hashlib.sha256(Path(precision.__file__).read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "installed_package_modified": False, "edits": edits}
