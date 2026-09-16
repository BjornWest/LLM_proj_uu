#!/usr/bin/env python3
"""Remote-only CUDA checks. Does not download or instantiate any model."""
import argparse
import datetime
import json
import os
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nccl", action="store_true")
    p.add_argument("--min-gpus", type=int, default=2)
    args = p.parse_args()
    import torch
    if args.nccl:
        import torch.distributed as dist
        rank = int(os.environ["LOCAL_RANK"])
        torch.cuda.set_device(rank)
        dist.init_process_group("nccl", timeout=datetime.timedelta(seconds=60))
        try:
            value = torch.tensor(float(rank + 1), device="cuda")
            dist.all_reduce(value)
            n = dist.get_world_size()
            assert value.item() == n * (n + 1) / 2
            print(f"NCCL rank {rank}: PASS", flush=True)
        finally:
            dist.destroy_process_group()
        return
    if torch.cuda.device_count() < args.min_gpus:
        raise RuntimeError(f"Need {args.min_gpus} visible GPUs; found {torch.cuda.device_count()}")
    results = []
    for i in range(torch.cuda.device_count()):
        with torch.cuda.device(i):
            properties = torch.cuda.get_device_properties(i)
            capability = torch.cuda.get_device_capability(i)
            if capability < (8, 9) or not torch.cuda.is_bf16_supported():
                raise RuntimeError(f"GPU {i} lacks baseline BF16/FP8 support: {capability}")
            x = torch.randn(128, 128, device=f"cuda:{i}", dtype=torch.bfloat16, requires_grad=True)
            x.square().mean().backward()
            assert torch.isfinite(x.grad).all()
            a = x.detach().to(torch.float8_e4m3fn)
            scale = torch.ones((), device=x.device)
            # Exercise a real FP8 GEMM, not just the ability to store float8 bytes.
            y = torch._scaled_mm(a, a.t(), scale_a=scale, scale_b=scale, out_dtype=torch.bfloat16)
            if isinstance(y, tuple):
                y = y[0]
            assert torch.isfinite(y).all()
            torch.cuda.synchronize()
            results.append({"gpu": i, "name": properties.name, "capability": capability,
                            "vram_gib": properties.total_memory / 2**30, "bf16_backward": True, "fp8_gemm": True})
    print(subprocess.check_output(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True).strip())
    print(json.dumps({"torch": torch.__version__, "cuda": torch.version.cuda, "gpus": results}, indent=2))


if __name__ == "__main__":
    main()
