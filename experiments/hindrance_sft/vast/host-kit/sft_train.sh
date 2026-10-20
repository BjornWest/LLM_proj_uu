#!/bin/bash
# Real SFT run: 16k primary variant, NF4 QLoRA baseline (no CCE), rank 16, 1 epoch, save every 6 steps.
set -uo pipefail
RUN=$1; T=/opt/sft/training; R=/opt/sft/outputs/$RUN; mkdir -p $R; cd $T
export PATH=$T/envs/sft/.venv/bin:$PATH HF_HOME=/model-cache/sft-hf PYTHONPATH=$T TOKENIZERS_PARALLELISM=false AXOLOTL_DO_NOT_TRACK=1 HF_HUB_OFFLINE=1
echo "{\"start_utc\":\"$(date -u +%FT%TZ)\"}" > $R/run-meta.json
bash scripts/run_sft.sh --config /opt/sft/configs/sft_qwen38_27b_nf4_qlora_hindrance16k.yml --enable-thinking \
  --dataset /opt/sft/data/train.qwen.primary16k.jsonl --save-steps 6 --output $R > $R/train.log 2>&1
code=$?
echo "{\"exit\":$code,\"end_utc\":\"$(date -u +%FT%TZ)\"}" > $R/TRAINING_DONE
