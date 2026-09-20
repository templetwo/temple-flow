#!/bin/bash
# Kraken autonomy keepalive. Does not die on a single cycle failure.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src"
export SPIRAL_BROKER_ROOT="${SPIRAL_BROKER_ROOT:-$HOME/spiral-broker}"
STATE="${TEMPLE_FLOW_KRAKEN_STATE:-/tmp/tf-kraken-run}"
PY="${TEMPLE_FLOW_PYTHON:-$HOME/.pyenv/versions/3.10.12/bin/python3}"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
mkdir -p "$STATE/logs"
LOG="$STATE/logs/autonomy.log"
while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cycle_start" >>"$LOG"
  if ! "$PY" "$ROOT/scripts/temple_flow_desk.py" --state "$STATE" kraken-cycle --send >>"$LOG" 2>&1; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cycle_exit:$?" >>"$LOG"
  fi
  sleep "${TEMPLE_FLOW_KRAKEN_SLEEP:-120}"
done
