#!/bin/bash
# GPU dry run: NF4 baseline, unpacked, 2 steps per length; then throughput steps at the chosen length.
# usage: sft_dryrun.sh LENGTHS(e.g. 8192,16384,24576) STEPS GRAD_ACCUM TAG
set -uo pipefail
T=/opt/sft/training; L=/root/sft-dryrun; mkdir -p $L /opt/sft/data; cd $T
export PATH=/opt/sft/training/envs/sft/.venv/bin:$PATH HF_HOME=/model-cache/sft-hf PYTHONPATH=$T TOKENIZERS_PARALLELISM=false AXOLOTL_DO_NOT_TRACK=1 HF_HUB_OFFLINE=1
P=$T/envs/sft/.venv/bin/python
TOKDIR=$(ls -d /model-cache/sft-hf/hub/models--greghavens--Qwen3.8-27B-bnb-4bit/snapshots/*/ | head -1)
STEPS=$2; GA=$3; TAG=$4
for LEN in ${1//,/ }; do
  N=$(( STEPS * GA + 2 ))
  D=/opt/sft/data/synth-$LEN-$N.jsonl
  rm -rf /opt/sft/outputs/dryrun-$TAG-$LEN
  [ -f $D ] || $P /root/kit/make_synth_sft.py $TOKDIR $LEN $N $D 2> $L/synth-$LEN.log
  ( while true; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits; sleep 1; done ) > $L/nvsmi-$TAG-$LEN.log &
  MON=$!
  start=$(date +%s)
  bash scripts/run_sft.sh --config ${CONFIG:-configs/sft_qwen38_27b_nf4_qlora.yml} --enable-thinking \
     --dataset $D --sequence-len $LEN --grad-accum $GA --steps $STEPS --save-steps 100000 \
     --output /opt/sft/outputs/dryrun-$TAG-$LEN > $L/run-$TAG-$LEN.log 2>&1
  code=$?
  kill $MON
  peak=$(sort -n $L/nvsmi-$TAG-$LEN.log | tail -1)
  echo "{\"tag\":\"$TAG\",\"len\":$LEN,\"steps\":$STEPS,\"grad_accum\":$GA,\"exit\":$code,\"wall_s\":$(( $(date +%s) - start )),\"nvsmi_peak_MiB\":$peak}" >> $L/summary.jsonl
done
