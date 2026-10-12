#!/usr/bin/env python3
"""Guarded Qwen FP8/MTP3/20GiB CPU-KV serving entry point, also for SSH hosts.

No unknown CLI passthrough: finer prefix hashes and other speculative methods
need separate qualification. Verification runs before any vLLM worker import.
"""
import argparse
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_training.compiler_environment import compiler_environment
from apply_vllm_cpu_kv_patch import apply_patch
from cpu_kv_offload_probe import CPU_BYTES, MODEL, REVISION, server_command


def command(snapshot, *, port=8000, max_num_seqs=32, memory_fraction=.90):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid serving port')
    if type(max_num_seqs) is not int or not 1 <= max_num_seqs <= 32:
        raise ValueError('Use a sequence cap in 1..32')
    if not .50 <= memory_fraction <= .90:
        raise ValueError('GPU memory fraction must be in .50..90')
    argv = server_command(str(snapshot))
    for flag, value in (('--port', port), ('--max-num-seqs', max_num_seqs),
                        ('--gpu-memory-utilization', memory_fraction)):
        argv[argv.index(flag)+1] = str(value)
    return argv


def fingerprint(argv):
    # Read the installed source now; an image-build receipt can be stale after sync.
    return dict(model=MODEL, model_revision=REVISION, command=argv,
                vllm_cpu_kv_patch=apply_patch(verify_only=True),
                profile='qwen38-fp8-mtp3-cpu20g-block1664-prefix-null-v1',
                qualification_scope='isolated restore only; browser/parking/LRU pressure pending')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True,
                   help='Cached HF snapshot of the pinned model revision')
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--max-num-seqs', type=int, default=32)
    p.add_argument('--memory-fraction', type=float, default=.90)
    p.add_argument('--cache-root',type=Path,default=Path(__file__).resolve().parents[1]/'.cache/compiled/cpu-kv')
    p.add_argument('--cuda-home',type=Path,help='Explicit toolkit with pinned CUDA-wheel layout; default uses locked NVCC wheel')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    argv = command(args.snapshot, port=args.port, max_num_seqs=args.max_num_seqs,
                   memory_fraction=args.memory_fraction)
    if args.dry_run:
        print(json.dumps({'command': argv, 'requires_installed_backport': True}))
        return
    # This supported entry point binds a revision, rather than labeling arbitrary
    # local weights as the qualified policy. Custom checkpoint exports need review.
    snapshot = args.snapshot.resolve(strict=True)
    if snapshot.name != REVISION or snapshot.parent.name != 'snapshots' or snapshot.parent.parent.name != 'models--Qwen--Qwen3.8-27B-FP8':
        raise ValueError('Use the exact pinned Hugging Face snapshot, not arbitrary local weights')
    argv=command(snapshot,port=args.port,max_num_seqs=args.max_num_seqs,memory_fraction=args.memory_fraction)
    shm = os.statvfs('/dev/shm')
    if shm.f_bavail*shm.f_frsize < CPU_BYTES+(1 << 30):
        raise RuntimeError('At least21GiB free /dev/shm required for the CPU KV tier')
    receipt = fingerprint(argv)
    receipt['checkpoint_config_sha256']=hashlib.sha256((snapshot/'config.json').read_bytes()).hexdigest()
    receipt['revision_binding']='trusted HF cache path plus recorded configuration hash; not a full shard integrity proof'
    cuda=args.cuda_home or Path(distribution('nvidia-cuda-nvcc').locate_file('nvidia/cu13'))
    receipt['cuda_home']=str(cuda)
    env=compiler_environment(cuda,args.cache_root/'link-libs',dict(os.environ))
    env.update(VLLM_WORKER_MULTIPROC_METHOD='spawn',
               VLLM_SERVER_DEV_MODE='1', VLLM_USE_SIMPLE_KV_OFFLOAD='0',
               VLLM_COMPUTE_NANS_IN_LOGITS='1', VLLM_LOG_STATS_INTERVAL='1',
               HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
               VLLM_CACHE_ROOT=str(args.cache_root/'vllm'),TRITON_CACHE_DIR=str(args.cache_root/'triton'))
    for key in ('HF_TOKEN','HUGGING_FACE_HUB_TOKEN','WANDB_API_KEY'):env.pop(key,None)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt), flush=True)
    os.execve(sys.executable, argv, env)


if __name__ == '__main__':
    main()
