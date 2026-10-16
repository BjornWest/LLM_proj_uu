#!/usr/bin/env python3
"""Guarded localhost Qwen native-tool/vision serving for an SSH suite host.

The allocating controller owns the rental deadline and provider deletion. This
entry point never allocates, downloads weights, starts browsers or dispatches a
model request. --dry-run constructs argv without importing vLLM or using CUDA.
"""
import argparse
import datetime
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_training.compiler_environment import compiler_environment
from browser_training import vllm_qwen_schema_patch as schema
from apply_vllm_cpu_kv_patch import apply_patch

# Keep production construction independent of benchmark instrumentation imports.
MODEL = 'Qwen/Qwen3.8-27B-FP8'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
CPU_BYTES = 20 << 30


def command(snapshot, *, port=8000, max_num_seqs=8, memory_fraction=.90):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid serving port')
    if type(max_num_seqs) is not int or not 1 <= max_num_seqs <= 256:
        raise ValueError('Use a sequence cap in 1..256')
    if not .50 <= memory_fraction <= .90:
        raise ValueError('GPU memory fraction must be in 0.50..0.90')
    argv = [sys.executable, '-P', '-m', 'vllm.entrypoints.cli.main', 'serve', str(snapshot)]
    # Retain the qualified MTP3/1664/null-prefix/CPU20GiB recipe. Add the
    # historical native browser transport profile, with the model's full context.
    values = {
        '--host': '127.0.0.1',
        '--served-model-name': MODEL,
        '--port': str(port),
        '--revision': REVISION,
        '--tokenizer-revision': REVISION,
        '--dtype': 'bfloat16',
        '--max-model-len': '262144',
        '--max-num-seqs': str(max_num_seqs),
        '--max-num-batched-tokens': '8192',
        '--gpu-memory-utilization': str(memory_fraction),
        '--kv-cache-dtype': 'fp8_e4m3',
        '--block-size': '1664',
        '--mamba-cache-mode': 'align',
        '--mamba-cache-dtype': 'bfloat16',
        '--mamba-ssm-cache-dtype': 'float32',
        '--gdn-prefill-backend': 'triton',
        '--performance-mode': 'interactivity',
        '--speculative-config': json.dumps({'method': 'mtp', 'num_speculative_tokens': 3}),
        '--kv-transfer-config': json.dumps({
            'kv_connector': 'OffloadingConnector', 'kv_role': 'kv_both',
            'kv_connector_extra_config': {'cpu_bytes_to_use': CPU_BYTES,
                'eviction_policy': 'lru', 'offload_prompt_only': True}}),
        '--generation-config': 'vllm',
        '--reasoning-parser': 'qwen3',
        '--tool-call-parser': 'qwen3_coder',
        '--default-chat-template-kwargs': json.dumps(
            {'enable_thinking': True, 'preserve_thinking': True}),
        '--limit-mm-per-prompt': json.dumps({'image': 1562, 'video': 0}),
        '--mm-processor-kwargs': json.dumps({
            'min_pixels': 65536, 'max_pixels': 16777216, 'patch_size': 16,
            'merge_size': 2, 'temporal_patch_size': 2}),
    }
    for flag, value in values.items():
        argv.extend([flag, value])
    for flag in ('--enable-auto-tool-choice', '--enable-tokenizer-info-endpoint',
                 '--enable-prompt-tokens-details', '--enable-prefix-caching',
                 '--disable-uvicorn-access-log'):
        argv.append(flag)
    return argv


def fingerprint(argv):
    if os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
        raise ValueError('Launch serving without PYTHONPATH/PYTHONHOME overrides')
    installed_version = version('vllm')
    if installed_version != schema.VERSION:
        raise ValueError('Native parser requires pinned vLLM ' + schema.VERSION)
    receipt = {'command': argv, 'vllm_version': installed_version,
               'python_version': sys.version,
               'vllm_cpu_kv_patch': apply_patch(verify_only=True)}
    parser = Path(distribution('vllm').locate_file('vllm/tool_parsers/utils.py'))
    if schema.digest(parser.read_bytes()) != schema.PATCHED_SHA256:
        raise ValueError('Install the reviewed Qwen schema patch before serving')
    # apply_to only reads already-patched source; the check above forbids it
    # silently installing a missing patch at serving time.
    receipt['qwen_schema_patch'] = schema.apply_to(parser)
    receipt['profile'] = 'qwen38-native-262144-fp8-mtp3-cpu20g-v1'
    receipt['launch_settings'] = {
        flag.removeprefix('--').replace('-', '_'): argv[argv.index(flag) + 1]
        for flag in ('--port', '--max-num-seqs', '--gpu-memory-utilization')}
    receipt['qualification_scope'] = (
        'Installed-source checks only; fresh host readiness and combined native '
        'browser/counter/capacity qualification remain separate')
    return receipt


def environment(cuda_home, cache_root, inherited):
    # Use a small allowlist rather than guessing every repository credential or
    # experimental setting. In particular omit PYTHONPATH/PYTHONHOME overrides and
    # benchmark instrumentation. HOME itself retains its normal inherited value.
    allowed = {'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE',
               'TZ', 'TMPDIR', 'TMP', 'TEMP', 'LD_LIBRARY_PATH', 'LIBRARY_PATH',
               'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES',
               'NVIDIA_DRIVER_CAPABILITIES', 'HF_HOME', 'HF_HUB_CACHE'}
    env = {k: v for k, v in inherited.items() if k in allowed}
    env = compiler_environment(cuda_home, cache_root / 'link-libs', env)
    # The compiler helper preserves an empty inherited path suffix. Never let an
    # empty/relative loader or executable search entry select the working dir.
    for key in ('PATH', 'LD_LIBRARY_PATH', 'LIBRARY_PATH'):
        env[key] = os.pathsep.join(p for p in env.get(key, '').split(os.pathsep)
                                   if os.path.isabs(p))
    env.update(VLLM_WORKER_MULTIPROC_METHOD='spawn', VLLM_SERVER_DEV_MODE='0',
               VLLM_USE_SIMPLE_KV_OFFLOAD='0', VLLM_COMPUTE_NANS_IN_LOGITS='1',
               VLLM_LOG_STATS_INTERVAL='5', VLLM_NO_USAGE_STATS='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', WANDB_MODE='disabled',
               PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
               PYTHONNOUSERSITE='1', PYTHONSAFEPATH='1', OMP_NUM_THREADS='1',
               SPT_NOENV='1',  # Keep /proc environment observable after vLLM title changes.
               TOKENIZERS_PARALLELISM='false',
               VLLM_CACHE_ROOT=str(cache_root / 'vllm'),
               TRITON_CACHE_DIR=str(cache_root / 'triton'))
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--port', type=int, default=8000)
    p.add_argument('--max-num-seqs', type=int, default=8)
    p.add_argument('--memory-fraction', type=float, default=.90)
    p.add_argument('--cache-root', type=Path, required=True)
    p.add_argument('--cuda-home', type=Path)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if args.dry_run:
        argv = command(args.snapshot, port=args.port, max_num_seqs=args.max_num_seqs,
                       memory_fraction=args.memory_fraction)
        print(json.dumps({'command': argv, 'source_checks': 'not performed',
                          'model_GPU_or_dispatch': False}))
        return
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt = {'attempt_id': uuid.uuid4().hex, 'pid': os.getpid(), 'status': 'starting',
               'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    def save():
        schema.atomic_write(args.receipt, (json.dumps(receipt, indent=2,
                            allow_nan=False) + '\n').encode(), 0o600)
    save()  # Invalidate a previous attempt before any launch guard can fail.
    try:
        argv = command(args.snapshot, port=args.port, max_num_seqs=args.max_num_seqs,
                       memory_fraction=args.memory_fraction)
        snapshot = args.snapshot.resolve(strict=True)
        if (snapshot.name != REVISION or snapshot.parent.name != 'snapshots'
                or snapshot.parent.parent.name != 'models--Qwen--Qwen3.8-27B-FP8'):
            raise ValueError('Use the exact pinned Hugging Face cache snapshot')
        shm = os.statvfs('/dev/shm')
        if shm.f_bavail * shm.f_frsize < CPU_BYTES + (1 << 30):
            raise RuntimeError('At least21GiB free /dev/shm required for CPU KV')
        argv = command(snapshot, port=args.port, max_num_seqs=args.max_num_seqs,
                       memory_fraction=args.memory_fraction)
        receipt.update(fingerprint(argv))
        receipt['checkpoint_config_sha256'] = hashlib.sha256(
            (snapshot / 'config.json').read_bytes()).hexdigest()
        receipt['revision_binding'] = 'Trusted HF snapshot path/config hash; not a full shard integrity proof'
        receipt['model'] = MODEL
        cuda = (args.cuda_home or Path(distribution('nvidia-cuda-nvcc').locate_file('nvidia/cu13'))).resolve()
        env = environment(cuda, args.cache_root.resolve(), dict(os.environ))
        receipt.update(cuda_home=str(cuda), serving_environment=env,
                       status='source_checks_passed_before_exec')
        save()
        print(json.dumps(receipt), flush=True)
        os.execve(sys.executable, argv, env)
    except BaseException as exc:
        receipt.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise


if __name__ == '__main__':
    main()
