#!/usr/bin/env python3
"""Audit source and test the loader patch without importing torch or loading models."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import urllib.request

from browser_training.attention_compat import patched_source

TRL = "a04ffd337108285002df29d9ae73ef7e855e03f1"
KERNELS = "555c2e89f4afb8b03c65ec619251db7b6806c287"


def loader_call(source, kwargs):
    tree = ast.parse(source)
    trainer = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AsyncGRPOTrainer")
    init = next(n for n in trainer.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    call = next(n for n in ast.walk(init) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Name) and n.func.id == "create_model_from_path")
    return eval(compile(ast.Expression(call), "<actual-upstream-loader-call>", "eval"),
                {"model": "no-model-is-loaded", "model_init_kwargs": dict(kwargs),
                 "create_model_from_path": lambda model, **kw: kw})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("research/sm120-validation.json"))
    args = p.parse_args()
    urls = {
        "trainer": f"https://raw.githubusercontent.com/huggingface/trl/{TRL}/trl/experimental/async_grpo/async_grpo_trainer.py",
        "fa3_dispatch": f"https://raw.githubusercontent.com/huggingface/kernels-community/{KERNELS}/flash-attn3/flash-attn/static_switch.h",
        "fa3_build": f"https://raw.githubusercontent.com/huggingface/kernels-community/{KERNELS}/flash-attn3/build.toml",
        "fa2_build": "https://raw.githubusercontent.com/Dao-AILab/flash-attention/v2.8.3/setup.py",
    }
    sources = {key: urllib.request.urlopen(url, timeout=30).read().decode() for key, url in urls.items()}
    original = sources["trainer"]
    patched = patched_source(original)
    assert patched_source(patched) == patched
    try:
        loader_call(original, {"attn_implementation": "flash_attention_2"})
    except TypeError as exc:
        original_error = str(exc)
    else:
        raise AssertionError("Original loader unexpectedly accepts an attention override")
    assert loader_call(patched, {})["attn_implementation"] == "kernels-community/flash-attn3"
    assert loader_call(patched, {"attn_implementation": "flash_attention_2", "revision": "pinned",
                                "dtype": "bfloat16"}) == {
        "device_map": None, "attn_implementation": "flash_attention_2", "revision": "pinned", "dtype": "bfloat16"}
    try:
        patched_source(original + "\n# unrelated change\n")
    except ValueError:
        pass
    else:
        raise AssertionError("Patch accepted unreviewed source")
    assert 'arch=compute_120,code=sm_120' in sources["fa2_build"]
    assert 'else if (ARCH < 90)' in sources["fa3_dispatch"]
    # Inspect the actual published CUDA 13 stable-ABI artifact metadata, not just its build recipe.
    hub = json.load(urllib.request.urlopen("https://huggingface.co/api/models/kernels-community/flash-attn3"))
    metadata_url = f"https://huggingface.co/kernels-community/flash-attn3/raw/{hub['sha']}/build/torch-stable-abi210-cu130-x86_64-linux/metadata.json"
    metadata = json.load(urllib.request.urlopen(metadata_url))
    report = {"sources": {key: {"url": urls[key], "sha256": hashlib.sha256(text.encode()).hexdigest()}
                           for key, text in sources.items()},
        "artifact_metadata_url": metadata_url, "artifact_metadata": metadata,
        "original_override_error": original_error,
        "patched_loader_override_preserves_other_kwargs": True, "patch_idempotent": True,
        "unknown_source_rejected": True, "patched_trainer_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        "fa3_dispatch_sm100_sm103_sm120": "ARCH >= 90 selects the Hopper Arch=90 path",
        "fa2_setup_has_native_sm120_target": True,
        "gpu_kernel_execution_tested": False, "sm120_training_qualified": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
