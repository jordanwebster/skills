#!/bin/bash
# drive.sh — minimal relaunch loop for the unattended framework build.
# Pattern: milestone checks are the queue; a fresh codex iteration per cycle;
# the driver, not the agent, decides done by running check.sh.
set -u

REPO="/Users/jlw/source/skills"
STATE="$HOME/.local/state/agent-skills/loop-build"
BRIEF="$REPO/docs/loop/BUILD-BRIEF.md"
CHECK="$REPO/docs/loop/build/check.sh"
MAX_ITER=40
STALL_CAP=4          # consecutive iterations with no new commit
ITER_TIMEOUT=7200    # seconds per codex iteration

mkdir -p "$STATE"
LOG="$STATE/driver.log"
PIDFILE="$STATE/driver.pid"

# refuse to double-run
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "driver already running (pid $(cat "$PIDFILE"))" >&2
  exit 1
fi
echo $$ > "$PIDFILE"

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S')] $*" >> "$LOG"; }

cd "$REPO" || { log "cannot cd to repo"; exit 1; }
log "driver start pid=$$ head=$(git rev-parse --short HEAD)"

consec=0
i=0
while [ $i -lt $MAX_ITER ]; do
  i=$((i+1))
  date > "$STATE/heartbeat"

  if [ -f "$CHECK" ] && bash "$CHECK" >> "$LOG" 2>&1; then
    log "DONE: check.sh green after $((i-1)) iterations"
    echo "SUCCESS" > "$STATE/result"
    rm -f "$PIDFILE"
    exit 0
  fi

  before=$(git rev-parse HEAD)
  log "iteration $i dispatching codex (head=$(git rev-parse --short HEAD))"
  timeout "$ITER_TIMEOUT" codex exec \
      -m gpt-5.6-sol -c model_reasoning_effort=high \
      --sandbox workspace-write -C "$REPO" \
      -o "$STATE/iter-$i-last.md" - \
      < "$BRIEF" >> "$STATE/iter-$i.log" 2>&1
  rc=$?
  after=$(git rev-parse HEAD)

  if [ "$before" = "$after" ]; then
    consec=$((consec+1))
    log "iteration $i: no commit (rc=$rc, stall $consec/$STALL_CAP)"
    if [ $consec -ge $STALL_CAP ]; then
      log "STALLED: $STALL_CAP consecutive iterations without a commit"
      echo "STALLED" > "$STATE/result"
      rm -f "$PIDFILE"
      exit 2
    fi
    # back off — absorbs transient provider/quota trouble without burning cycles
    sleep $((consec * 900))
  else
    consec=0
    log "iteration $i: advanced $before -> $after (rc=$rc)"
  fi
done

log "MAX_ITER reached without green check"
echo "MAX_ITER" > "$STATE/result"
rm -f "$PIDFILE"
exit 3
