#!/bin/bash
# Vast onstart: arm an on-host deadline that destroys THIS instance through the
# provider API with the instance-scoped CONTAINER_API_KEY. It runs on the rented
# host, so it survives loss of the workstation, its watchdog and this agent.
# It does not survive the container itself dying; the workstation watchdog and
# the credit-only account balance remain the other two layers.
#
# Allocation substitutes __DEADLINE_UTC__ (absolute epoch anchored to
# allocation). The timer fires at that wall time, or after the remaining
# seconds measured at arm time if the clock jumps, whichever comes first.
set -u
DEADLINE_UTC=${SELF_DESTROY_DEADLINE_UTC:-__DEADLINE_UTC__}
API=${SELF_DESTROY_API:-https://console.vast.ai/api/v0}
DIR=${SELF_DESTROY_DIR:-/root/self-destroy}
mkdir -p "$DIR"; chmod 700 "$DIR"
case "$DEADLINE_UTC" in ''|*[!0-9]*) echo "invalid deadline" >"$DIR/armed-error"; exit 1;; esac
if [ -z "${CONTAINER_ID:-}" ] || [ -z "${CONTAINER_API_KEY:-}" ]; then
  echo "CONTAINER_ID or CONTAINER_API_KEY missing" >"$DIR/armed-error"; exit 1
fi
# Write the timer body once; re-running onstart after a restart re-arms from
# the same absolute deadline.
cat >"$DIR/timer.sh" <<'EOF'
#!/bin/bash
set -u
remaining=$(( DEADLINE_UTC - $(date +%s) ))
[ "$remaining" -lt 0 ] && remaining=0
SECONDS=0
printf '{"armed_utc":%s,"deadline_utc":%s,"pid":%s,"container_id":"%s"}\n' \
  "$(date +%s)" "$DEADLINE_UTC" "$$" "$CONTAINER_ID" >"$DIR/armed.json"
while [ "$(date +%s)" -lt "$DEADLINE_UTC" ] && [ "$SECONDS" -lt "$remaining" ]; do
  sleep 5
done
attempt=0
while :; do
  attempt=$((attempt+1))
  code=$(curl -sS -o "$DIR/last-response.json" -w '%{http_code}' --max-time 20 \
    -X DELETE -H "Authorization: Bearer $CONTAINER_API_KEY" \
    -H 'Content-Type: application/json' -d '{}' \
    "$API/instances/$CONTAINER_ID/" 2>>"$DIR/curl-errors.log")
  printf '{"attempt":%s,"utc":%s,"http":"%s"}\n' "$attempt" "$(date +%s)" "$code" >>"$DIR/attempts.jsonl"
  sleep 20
done
EOF
chmod 700 "$DIR/timer.sh"
export DEADLINE_UTC API DIR CONTAINER_ID CONTAINER_API_KEY
setsid nohup "$DIR/timer.sh" >>"$DIR/timer.log" 2>&1 </dev/null &
echo "$!" >"$DIR/timer.pid"
# Vast containers can leave /root/.ssh with modes sshd rejects (Florida); repair
# them for the first five minutes.
( for i in $(seq 1 60); do
    chown root:root /root /root/.ssh /root/.ssh/authorized_keys 2>/dev/null
    chmod 700 /root/.ssh 2>/dev/null; chmod 600 /root/.ssh/authorized_keys 2>/dev/null
    sleep 5
  done ) >/dev/null 2>&1 &
