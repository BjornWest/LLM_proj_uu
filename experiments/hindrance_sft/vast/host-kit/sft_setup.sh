#!/bin/bash
# SFT baseline env (envs/sft, locked; role "sft" = SDPA, unpacked) + NF4 base download. vLLM keeps running.
set -uo pipefail
L=/root/sft-setup; mkdir -p $L /opt/sft /model-cache/sft-hf; ts(){ date -u +%FT%TZ; }
echo "$(ts) start" >> $L/phases.log
tar -xzf /root/kit/training-main-f3d3ad9.tar.gz -C /opt/sft
T=/opt/sft/training; UV=/opt/qwen-runtime/tools/bin/uv
export HF_HOME=/model-cache/sft-hf TOKENIZERS_PARALLELISM=false AXOLOTL_DO_NOT_TRACK=1 HF_HUB_ENABLE_HF_TRANSFER=1
# NF4 base download in parallel (public, no token)
( /opt/hf-download/bin/python -c 'from huggingface_hub import snapshot_download;print(snapshot_download("greghavens/Qwen3.8-27B-bnb-4bit",revision="26157380225e427827263c34df23018a1e28dff5"))' \
  && echo "$(ts) nf4 download done" >> $L/phases.log || echo "$(ts) nf4 download FAILED" >> $L/phases.log ) > $L/download.log 2>&1 &
nice -n 10 $UV sync --project $T/envs/sft --python 3.12.12 --locked > $L/uv.log 2>&1 && echo "$(ts) sft env synced" >> $L/phases.log || { echo "$(ts) sft env FAILED" >> $L/phases.log; exit 1; }
$UV pip check --python $T/envs/sft/.venv/bin/python >> $L/uv.log 2>&1 && echo "$(ts) pip check ok" >> $L/phases.log
cd $T && CUDA_VISIBLE_DEVICES='' PYTHONPATH=$T nice -n 10 envs/sft/.venv/bin/python scripts/validate_training_cpu.py --role sft > $L/validate-cpu.log 2>&1 \
  && echo "$(ts) validate_training_cpu sft ok" >> $L/phases.log || echo "$(ts) validate_training_cpu sft FAILED (see validate-cpu.log)" >> $L/phases.log
wait
echo "$(ts) done" >> $L/phases.log
