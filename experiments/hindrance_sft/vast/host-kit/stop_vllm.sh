#!/bin/bash
# Stop vLLM (pattern kept in this file so pkill cannot match the caller's ssh command line).
pkill -TERM -f "vllm.entrypoints.cli.main"
for i in $(seq 1 40); do pgrep -f "vllm.entrypoints.cli.main|VLLM::EngineCore" >/dev/null || break; sleep 1; done
pkill -9 -f "vllm.entrypoints.cli.main|VLLM::EngineCore"
for i in $(seq 1 30); do nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q . || break; sleep 1; done
rm -f /dev/shm/vllm_offload_*.mmap
echo "$(date -u +%FT%TZ) vLLM stopped" >> /root/setup/phases.log
nvidia-smi --query-gpu=memory.used --format=csv,noheader
