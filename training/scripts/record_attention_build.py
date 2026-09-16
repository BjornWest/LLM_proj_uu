#!/usr/bin/env python3
"""Record a compiled FA2 wheel and verify it matches the importable extension."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tomllib
import zipfile

os.environ["CUDA_VISIBLE_DEVICES"] = ""


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wheel", type=Path, required=True)
    p.add_argument("--ninja-file", type=Path, required=True)
    p.add_argument("--arch", type=int, default=120)
    p.add_argument("--output", type=Path, default=Path("research/flash-attn-build.json"))
    args = p.parse_args()
    import torch
    import flash_attn
    import flash_attn_2_cuda
    assert flash_attn.__version__ == "2.8.3" and torch.__version__.startswith("2.13.0")
    binary = Path(flash_attn_2_cuda.__file__)
    binary_hash = digest(binary)
    with zipfile.ZipFile(args.wheel) as archive:
        member = next(name for name in archive.namelist() if name.startswith("flash_attn_2_cuda") and name.endswith(".so"))
        with archive.open(member) as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == binary_hash
    flags = next(line for line in args.ninja_file.read_text().splitlines() if line.startswith("cuda_post_cflags"))
    assert flags.count("-gencode") == 1 and f"arch=compute_{args.arch},code=sm_{args.arch}" in flags
    compiled = (args.ninja_file.parent / ".ninja_log").read_text().splitlines()[1:]
    assert len(compiled) == 73
    versions = subprocess.check_output(["readelf", "--version-info", str(binary)], text=True)
    required = {}
    for prefix in ("GLIBC", "GLIBCXX", "CXXABI"):
        values = set(re.findall(r"\b" + prefix + r"_([0-9.]+)", versions))
        required[prefix] = max(values, key=lambda value: tuple(map(int, value.split("."))))
    lock = tomllib.loads(Path("envs/rl/uv.lock").read_text())
    source = next(package["sdist"] for package in lock["package"] if package["name"] == "flash-attn")
    wheel_hash = digest(args.wheel)
    args.wheel.with_suffix(".whl.sha256").write_text(f"{wheel_hash}  {args.wheel.name}\n")
    report = {"status": "BUILD_AND_IMPORT_PASS", "wheel": str(args.wheel),
        "wheel_sha256": wheel_hash, "wheel_bytes": args.wheel.stat().st_size,
        "extension_sha256": binary_hash, "extension_bytes": binary.stat().st_size,
        "source": source, "python": platform.python_version(), "platform": platform.platform(),
        "torch": torch.__version__, "torch_cuda": torch.version.cuda,
        "build_packages": {name: metadata.version(name) for name in
            ("flash-attn", "ninja", "setuptools", "packaging", "nvidia-cuda-nvcc", "nvidia-nvvm")},
        "required_symbol_versions": required, "compiled_architecture": f"sm_{args.arch}",
        "compilation_units": len(compiled), "ninja_sha256": digest(args.ninja_file),
        "cuda_compile_flags": flags, "installed_binary_matches_wheel": True,
        "gpu_used": False, "kernel_execution_qualified": False}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
