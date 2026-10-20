#!/bin/bash
# Self-healing SSH tunnel: workstation 127.0.0.1:18000 -> host 127.0.0.1:8000 (vLLM). Reconnects forever;
# each (re)connect/exit is logged to vast/tunnel.log. Stop: kill the PID in vast/tunnel.pid.
HERE=$(cd "$(dirname "$0")" && pwd)
echo $$ > "$HERE/tunnel.pid"
# Endpoint of the rented instance: VAST_SSH_HOST/VAST_SSH_PORT (direct) and VAST_PROXY_HOST/VAST_PROXY_PORT,
# or a local, untracked ssh.json {"host","port","proxy_host","proxy_port"} written after allocation.
if [ -n "${VAST_SSH_HOST:-}" ]; then
  HOST=$VAST_SSH_HOST; PORT=${VAST_SSH_PORT:-22}; PHOST=${VAST_PROXY_HOST:-$HOST}; PPORT=${VAST_PROXY_PORT:-$PORT}
else
  read HOST PORT PHOST PPORT < <(python3 -c "import json;d=json.load(open('$HERE/ssh.json'));print(d['host'],d['port'],d['proxy_host'],d['proxy_port'])")
fi
n=0
while true; do
  n=$((n+1))
  # Direct route preferred (the Vast proxy route showed intermittent channel refusals);
  # the proxy is used only after a direct session lasted < 60 s.
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
