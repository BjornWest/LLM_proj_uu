#!/usr/bin/env python3
"""Compile/disassemble a tiny SM120 cubin on CPU; never launch a CUDA kernel."""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cuda-home", type=Path)
    p.add_argument("--arch", type=int, choices=[90, 100, 103, 120], default=120)
    p.add_argument("--output", type=Path, default=Path("research/cuda-toolchain-validation.json"))
    args = p.parse_args()
    cuda = args.cuda_home
    if cuda is None:
        cuda = Path(os.environ["CUDA_HOME"]) if "CUDA_HOME" in os.environ else Path(
            metadata.distribution("nvidia-cuda-nvcc").locate_file("nvidia/cu13"))
    cuda = cuda.resolve()
    version = subprocess.run([str(cuda / "bin/nvcc"), "--version"],
        check=True, text=True, capture_output=True, timeout=15).stdout
    if "V13.0.88" not in version:
        raise RuntimeError("This stack pins NVCC 13.0.88; select the locked RL toolkit with --cuda-home")
    report = {"cuda_home": str(cuda), "nvcc_version": version, "arch": args.arch,
        "installed_wheel_versions": {name: metadata.version(name) for name in
            ("nvidia-cuda-nvcc", "nvidia-cuda-crt", "nvidia-cuda-cccl", "nvidia-nvvm", "nvidia-cuda-nvdisasm")},
        "gpu_used": False, "kernel_executed": False,
        "scope": "compiler/header/assembler/disassembler check; not FlashAttention or runtime qualification"}
    source = """#include <cuda_runtime.h>
#include <cuda_bf16.h>
#include <cuda_fp8.h>
__global__ void cast_probe(const __nv_bfloat16* input, __nv_fp8_e4m3* output) {
    output[threadIdx.x] = __nv_fp8_e4m3(float(input[threadIdx.x]));
}
"""
    with tempfile.TemporaryDirectory(prefix="browser-cuda-compiler-") as temp:
        root = Path(temp)
        (root / "probe.cu").write_text(source)
        compiled = subprocess.run([str(cuda / "bin/nvcc"), f"-arch=sm_{args.arch}",
            "--cubin", str(root / "probe.cu"), "-o", str(root / "probe.cubin")],
            text=True, capture_output=True, timeout=60)
        report.update(returncode=compiled.returncode, compiler_stderr=compiled.stderr)
        exit_code = compiled.returncode
        if compiled.returncode == 0:
            result = subprocess.run([str(cuda / "bin/nvdisasm"), str(root / "probe.cubin")],
                check=True, text=True, capture_output=True, timeout=15)
            report["cubin_bytes"] = (root / "probe.cubin").stat().st_size
            report["target"] = [line.strip() for line in result.stdout.splitlines()
                if line.strip().startswith((".target", ".headerflags"))]
            assert any(line.split() == [".target", f"sm_{args.arch}"] or
                f"EF_CUDA_SM{args.arch}" in line for line in report["target"]), report["target"]
            linked = subprocess.run([str(cuda / "bin/nvcc"), f"-arch=sm_{args.arch}",
                "--shared", "--cudart", "shared", "-Xcompiler", "-fPIC",
                "-L", str(cuda / "lib"),
                str(root / "probe.cu"), "-o", str(root / "probe.so")],
                text=True, capture_output=True, timeout=60)
            report.update(host_link_returncode=linked.returncode, host_link_stderr=linked.stderr)
            exit_code = linked.returncode
        report["status"] = "PASS" if exit_code == 0 else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
