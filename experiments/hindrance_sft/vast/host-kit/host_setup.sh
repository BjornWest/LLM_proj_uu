#!/bin/bash
# Host-side: model download (background), locked vLLM 0.28.0 env + reviewed patches, then
# vLLM on 127.0.0.1:8000 via the reviewed serve_qwen_suite.py argv. Logs in /root/setup.
set -uo pipefail
L=/root/setup; mkdir -p $L /model-cache/hub /opt/qwen-runtime/rl /private/qwen-cache /opt/qwen-release
ts(){ date -u +%FT%TZ; }
echo "$(ts) start" >> $L/phases.log
tar -xzf /root/kit/release.tar.gz -C /opt/qwen-release
REL=/opt/qwen-release
# 1. model download in the background
( python3 -m venv /opt/hf-download && /opt/hf-download/bin/pip install -q huggingface_hub hf_transfer \
  && HF_HUB_ENABLE_HF_TRANSFER=1 /opt/hf-download/bin/python -c 'import sys;from huggingface_hub import snapshot_download;print(snapshot_download("Qwen/Qwen3.8-27B-FP8",revision="017b9c7af6b5689d5dd426a76e0bc077eb5ca20a",cache_dir=sys.argv[1],token=False))' /model-cache/hub \
  && echo "$(ts) model done" >> $L/phases.log || echo "$(ts) model FAILED" >> $L/phases.log ) > $L/model-download.log 2>&1 &
DL=$!
# 2. serving environment
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update > $L/apt.log 2>&1
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends python3-venv build-essential ninja-build git libgomp1 ca-certificates curl >> $L/apt.log 2>&1
echo "$(ts) apt done" >> $L/phases.log
python3 -m venv /opt/qwen-runtime/tools
/opt/qwen-runtime/tools/bin/pip install -q uv==0.10.8
UV=/opt/qwen-runtime/tools/bin/uv
$UV python install 3.12.12 > $L/uv.log 2>&1
cp $REL/training/envs/rl/pyproject.toml $REL/training/envs/rl/uv.lock /opt/qwen-runtime/rl/
$UV sync --project /opt/qwen-runtime/rl --locked --python 3.12.12 --default-index https://pypi.org/simple >> $L/uv.log 2>&1
$UV pip check --python /opt/qwen-runtime/rl/.venv/bin/python >> $L/uv.log 2>&1
echo "$(ts) env done" >> $L/phases.log
RL=/opt/qwen-runtime/rl/.venv/bin/python
$RL -I -B $REL/training/scripts/apply_vllm_cpu_kv_patch.py --install-in-place --receipt /opt/qwen-runtime/mtp-offload-backport.json > $L/patch.log 2>&1
$RL -I -B $REL/training/scripts/apply_vllm_cpu_kv_patch.py --verify-only >> $L/patch.log 2>&1
$RL -I -B $REL/training/scripts/apply_vllm_qwen_schema_patch.py >> $L/patch.log 2>&1
echo "$(ts) patches done" >> $L/phases.log
set +e
wait $DL
SNAP=/model-cache/hub/models--Qwen--Qwen3.8-27B-FP8/snapshots/017b9c7af6b5689d5dd426a76e0bc077eb5ca20a
[ -f $SNAP/config.json ] || { echo "$(ts) no snapshot" >> $L/phases.log; exit 1; }
df -h / /dev/shm > $L/df.log; free -g >> $L/df.log; nvidia-smi >> $L/df.log
echo "$(ts) serve start" >> $L/phases.log
cd / && setsid nohup $RL -I -B $REL/training/scripts/serve_qwen_suite.py --snapshot $SNAP \
  --receipt /root/setup/serve-receipt.json --cache-root /private/qwen-cache --max-num-seqs ${MAX_NUM_SEQS:-32} \
  > /root/vllm.log 2>&1 < /dev/null &
echo $! > /root/vllm.pid
