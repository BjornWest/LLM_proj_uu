#!/bin/bash
# SFT run from a complete host config (datasets inside the config; no --dataset override).
#   sft_train_cfg.sh RUN CONFIG SAVE_STEPS
set -uo pipefail
RUN=$1; CFG=$2; SAVE=$3; T=/opt/sft/training; R=/opt/sft/outputs/$RUN; mkdir -p $R; cd $T
export PATH=$T/envs/sft/.venv/bin:$PATH HF_HOME=/model-cache/sft-hf PYTHONPATH=$T TOKENIZERS_PARALLELISM=false AXOLOTL_DO_NOT_TRACK=1 HF_HUB_OFFLINE=1
echo "{\"start_utc\":\"$(date -u +%FT%TZ)\",\"config\":\"$CFG\"}" > $R/run-meta.json
bash scripts/run_sft.sh --config $CFG --enable-thinking --save-steps $SAVE --output $R > $R/train.log 2>&1
code=$?
echo "{\"exit\":$code,\"end_utc\":\"$(date -u +%FT%TZ)\"}" > $R/TRAINING_DONE
