#!/bin/bash
# Start vLLM with the reviewed argv (20 GiB CPU KV offload, as originally qualified) plus LoRA adapter(s).
#   serve_vllm_lora.sh ADAPTER_DIR [NAME=qwen-sft] [RANK=16] [OFFLOAD=1] [MORE="name2=dir2 name3=dir3"]
set -u
ADAPTER=$1; NAME=${2:-qwen-sft}; RANK=${3:-16}; OFFLOAD=${4:-1}; MORE=${5:-}
NLORA=$(( 1 + $(echo $MORE | wc -w) ))
L=/root/setup; ts(){ date -u +%FT%TZ; }
nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q . && { echo "GPU busy"; exit 1; }
rm -f /dev/shm/vllm_offload_*.mmap
[ -f /root/vllm.log ] && mv /root/vllm.log /root/vllm-$(date +%s).log
REL=/opt/qwen-release; RL=/opt/qwen-runtime/rl/.venv/bin/python
SNAP=/model-cache/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a
echo "$(ts) serve with LoRA $NAME=$ADAPTER $MORE rank $RANK offload=$OFFLOAD" >> $L/phases.log
cd / && setsid nohup $RL -I -B -c "
import sys; sys.path.insert(0, '$REL/training/scripts')
import serve_qwen_suite as s
original = s.command
def command(*a, **k):
    argv = original(*a, **k)
    if not $OFFLOAD:
        i = argv.index('--kv-transfer-config'); del argv[i:i + 2]
    return argv + ['--enable-lora', '--max-lora-rank', '$RANK', '--max-loras', '$NLORA',
                   '--lora-modules', '$NAME=$ADAPTER'] + '$MORE'.split()
s.command = command
sys.argv = ['serve_qwen_suite.py', '--snapshot', '$SNAP', '--receipt', '/root/setup/serve-receipt-lora.json',
            '--cache-root', '/private/qwen-cache', '--max-num-seqs', '32']
s.main()" > /root/vllm.log 2>&1 < /dev/null &
echo $! > /root/vllm.pid
