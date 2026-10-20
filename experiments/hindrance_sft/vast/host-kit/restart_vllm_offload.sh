#!/bin/bash
# Restart vLLM with the same reviewed argv but a larger CPU KV offload tier (GiB arg, default 58).
# /dev/shm is a fixed 62 GiB tmpfs (no remount permission); the connector's mmap is hard-coded there.
set -u
GIB=${1:-58}
L=/root/setup; ts(){ date -u +%FT%TZ; }
echo "$(ts) restart requested cpu=${GIB}GiB" >> $L/phases.log
OLD=$(cat /root/vllm.pid)
kill -TERM $OLD 2>/dev/null
for i in $(seq 1 45); do kill -0 $OLD 2>/dev/null || break; sleep 1; done
pkill -9 -f "vllm.entrypoints.cli.main" 2>/dev/null; pkill -9 -f "VLLM::EngineCore" 2>/dev/null
for i in $(seq 1 30); do nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q . || break; sleep 1; done
rm -f /dev/shm/vllm_offload_*.mmap
echo "$(ts) stopped; shm: $(df -h /dev/shm | tail -1)" >> $L/phases.log
mv /root/vllm.log /root/vllm-$(date +%s).log
REL=/opt/qwen-release; RL=/opt/qwen-runtime/rl/.venv/bin/python
SNAP=/model-cache/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a
cd / && setsid nohup $RL -I -B -c "
import sys; sys.path.insert(0, '$REL/training/scripts')
import serve_qwen_suite as s
s.CPU_BYTES = $GIB << 30
sys.argv = ['serve_qwen_suite.py', '--snapshot', '$SNAP', '--receipt', '/root/setup/serve-receipt-cpu${GIB}g.json',
            '--cache-root', '/private/qwen-cache', '--max-num-seqs', '32']
s.main()" > /root/vllm.log 2>&1 < /dev/null &
echo $! > /root/vllm.pid
echo "$(ts) started pid $(cat /root/vllm.pid)" >> $L/phases.log
