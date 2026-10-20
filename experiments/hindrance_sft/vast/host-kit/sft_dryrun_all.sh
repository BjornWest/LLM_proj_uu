#!/bin/bash
# Baseline 16k (no CCE), then CCE 16k (loss sanity, same sample), 32k, 48k, 66k; 2 steps each, grad-accum 1.
rm -f /root/sft-dryrun/summary.jsonl
bash /root/kit/sft_dryrun.sh 16384 2 1 base
CONFIG=configs/sft_qwen38_27b_nf4_qlora_cce.yml bash /root/kit/sft_dryrun.sh 16384,32768,49152,66560 2 1 cce
echo ALLDONE >> /root/sft-dryrun/summary.jsonl
