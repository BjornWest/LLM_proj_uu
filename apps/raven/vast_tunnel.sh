#!/bin/bash
# Self-healing SSH tunnel for the "Qwen 27B (self-hosted Vast)" preset:
# local 127.0.0.1:18000 -> Vast instance 127.0.0.1:8000 (vLLM). Reconnects forever.
# Copied from experiments/hindrance_sft/vast/tunnel.sh (submission branch); state lives
# in .local/raven-vast/ (tunnel.pid, tunnel.log, tunnel-ssh.err, known_hosts).
#   VAST_SSH_HOST=ssh5.vast.ai VAST_SSH_PORT=12345 apps/raven/vast_tunnel.sh &
# Optional proxy route: VAST_PROXY_HOST/VAST_PROXY_PORT. Or write .local/raven-vast/ssh.json
# {"host","port","proxy_host","proxy_port"}. Needs this machine's SSH key on the instance.
# Stop: kill "$(cat .local/raven-vast/tunnel.pid)"
HERE=$(cd "$(dirname "$0")/../.." && pwd)/.local/raven-vast
mkdir -p "$HERE"
echo $$ > "$HERE/tunnel.pid"
if [ -n "${VAST_SSH_HOST:-}" ]; then
  HOST=$VAST_SSH_HOST; PORT=${VAST_SSH_PORT:-22}; PHOST=${VAST_PROXY_HOST:-$HOST}; PPORT=${VAST_PROXY_PORT:-$PORT}
elif [ -f "$HERE/ssh.json" ]; then
  read HOST PORT PHOST PPORT < <(python3 -c "import json;d=json.load(open('$HERE/ssh.json'));print(d['host'],d['port'],d.get('proxy_host',d['host']),d.get('proxy_port',d['port']))")
else
  echo "Set VAST_SSH_HOST and VAST_SSH_PORT (from the Vast console's SSH command)" >&2; exit 2
fi
echo "Tunnel 127.0.0.1:18000 -> root@$HOST:$PORT 127.0.0.1:8000; log $HERE/tunnel.log" >&2
n=0
while true; do
  n=$((n+1))
  # Direct route preferred; the proxy is used only after a direct session lasted < 60 s.
  if [ "${short:-0}" -eq 1 ]; then H=$PHOST; P=$PPORT; else H=$HOST; P=$PORT; fi
  began=$(date +%s)
  echo "{\"utc\":\"$(date -u +%FT%TZ)\",\"event\":\"connect\",\"attempt\":$n,\"route\":\"$H:$P\"}" >> "$HERE/tunnel.log"
  ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
      -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$HERE/known_hosts" \
      -o BatchMode=yes -L 127.0.0.1:18000:127.0.0.1:8000 -p "$P" root@"$H" 2>> "$HERE/tunnel-ssh.err"
  code=$?
  if [ "$H" = "$HOST" ] && [ $(( $(date +%s) - began )) -lt 60 ]; then short=1; else short=0; fi
  echo "{\"utc\":\"$(date -u +%FT%TZ)\",\"event\":\"exit\",\"attempt\":$n,\"code\":$code}" >> "$HERE/tunnel.log"
  sleep 3
done
