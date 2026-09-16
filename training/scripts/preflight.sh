#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
stage="${1:-static}"
case "$stage" in static|tiny|model|all) ;; *) echo 'Usage: preflight.sh [static|tiny|model|all]' >&2; exit 2;; esac
mkdir -p reports
"$TRAINING_ROOT/.venv/bin/python" -m pytest -q
for script in scripts/*.sh; do bash -n "$script"; done
if [[ "$stage" == static ]]; then
  echo 'Static checks passed. No CUDA/model/optimizer/serving checks were run.'
  exit 0
fi
SFT_PY="$TRAINING_ROOT/envs/sft/.venv/bin/python"
RL_PY="$TRAINING_ROOT/envs/rl/.venv/bin/python"
"$SFT_PY" scripts/verify_stack.py --role sft
"$RL_PY" scripts/verify_stack.py --role rl
"$RL_PY" scripts/verify_gpu.py --min-gpus 2
"$TRAINING_ROOT/envs/rl/.venv/bin/torchrun" --standalone --nproc-per-node=2 scripts/verify_gpu.py --nccl
# Check RL's kernel prerequisite before loading any model. SFT/serving-only model
# stage remains available on Blackwell despite this upstream trainer blocker.
if [[ "$stage" == tiny || "$stage" == all ]]; then
  CUDA_VISIBLE_DEVICES=1 "$RL_PY" scripts/verify_attention.py --backend "${RL_ATTENTION:-kernels-community/flash-attn3}"
fi
server_pid=''
cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill -- "-$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
start_server() {
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo 'Port 8000 already serves an endpoint. Stop it or run individual checks.' >&2; exit 2
  fi
  setsid scripts/run_vllm_rl.sh "$@" > reports/preflight-vllm.log 2>&1 &
  server_pid=$!
  for ((attempt=0; attempt<180; attempt++)); do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then return; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then tail -60 reports/preflight-vllm.log; exit 1; fi
    sleep 5
  done
  echo 'Server readiness timed out; inspect reports/preflight-vllm.log' >&2; exit 1
}
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
if [[ "$stage" == tiny || "$stage" == all ]]; then
  CUDA_VISIBLE_DEVICES=0 "$SFT_PY" scripts/sft_smoke_test.py --config configs/sft_smoke.yml
  scripts/smoke_sft.sh --output "outputs/preflight-tiny-$run_id"
  start_server --model Qwen/Qwen3-0.6B --context 1024 --eager
  "$TRAINING_ROOT/.venv/bin/python" scripts/check_vllm.py \
    --adapter "outputs/preflight-tiny-$run_id/checkpoint-2" \
    --next-adapter "outputs/preflight-tiny-$run_id/checkpoint-3"
  scripts/smoke_rl.sh --output "outputs/preflight-rl-$run_id"
  test -s "outputs/preflight-rl-$run_id/checkpoint-3/rollout_state.json"
  cleanup; server_pid=''
fi
if [[ "$stage" == model || "$stage" == all ]]; then
  model_config="${SFT_CONFIG:-configs/sft_qwen38_27b_bf16_lora.yml}"
  CUDA_VISIBLE_DEVICES=0 "$SFT_PY" scripts/sft_smoke_test.py --config "$model_config"
  "$TRAINING_ROOT/.venv/bin/python" scripts/make_smoke_data.py
  scripts/run_sft.sh --config "$model_config" --steps 3 --save-steps 1 --grad-accum 1 --dataset data/smoke.jsonl --output "outputs/preflight-model-$run_id"
  start_server --model Qwen/Qwen3.8-27B-FP8 --context 4096
  "$TRAINING_ROOT/.venv/bin/python" scripts/check_vllm.py \
    --adapter "outputs/preflight-model-$run_id/checkpoint-2" \
    --next-adapter "outputs/preflight-model-$run_id/checkpoint-3"
  cleanup; server_pid=''
  echo 'Real SFT/serving checks passed; multi-turn RL still requires GPU qualification of policy reservations and a project harness factory. MTP not tested.'
  exit 2
fi
echo 'Tiny model preflight passed: SFT, runtime LoRA registration, one-turn mock AsyncGRPO and checkpoints.'
