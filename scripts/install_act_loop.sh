#!/usr/bin/env bash
# Install the Temple Flow Act loop launchd daemon.
# One human Terminal command on Mac Studio. Never creates LIVE_OK unless
# --live-ok is passed.
#
# Order matters and is the point of this script: the LIVE_OK state is decided
# and printed BEFORE anything is copied or loaded, so the mode it announces is
# the mode the daemon actually runs in. It reads the real plist rather than
# describing one from memory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_SRC="$REPO_ROOT/deploy/com.templetwo.temple-flow-wire.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.templetwo.temple-flow-wire.plist"
LIVE_OK="$REPO_ROOT/config/LIVE_OK"
STANDING_RULES="$REPO_ROOT/config/standing_rules.json"
EXAMPLE_RULES="$REPO_ROOT/config/standing_rules.example.json"

WANT_LIVE_OK=0
case "${1:-}" in
    "") ;;
    --live-ok) WANT_LIVE_OK=1 ;;
    *)
        echo "ERROR: unknown argument '$1'"
        echo "Usage: $0 [--live-ok]"
        exit 2
        ;;
esac

echo "=== Temple Flow Act-loop installer ==="
echo

if [[ ! -f "$PLIST_SRC" ]]; then
    echo "ERROR: $PLIST_SRC not found"
    exit 1
fi

# --- 1. read the plist we are about to load. Never describe it from memory. ---
PROGRAM_ARGS="$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments' "$PLIST_SRC")"
PLIST_ENV_LIVE="$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:TEMPLE_FLOW_LIVE' "$PLIST_SRC" 2>/dev/null || true)"
PLIST_INTERVAL="$(/usr/libexec/PlistBuddy -c 'Print :StartInterval' "$PLIST_SRC" 2>/dev/null || echo '?')"

PLIST_PASSES_LIVE=0
if grep -qE '(^|[[:space:]])--live([[:space:]]|$)' <<<"$PROGRAM_ARGS"; then
    PLIST_PASSES_LIVE=1
fi

echo "Plist source: $PLIST_SRC"
echo "ProgramArguments it will load:"
sed 's/^/    /' <<<"$PROGRAM_ARGS"
echo "    EnvironmentVariables.TEMPLE_FLOW_LIVE = ${PLIST_ENV_LIVE:-<unset>}"
echo "    StartInterval = ${PLIST_INTERVAL}s"
echo

# --- 2. decide LIVE_OK BEFORE copying or loading anything ---
if [[ $WANT_LIVE_OK -eq 1 ]]; then
    if [[ -f "$STANDING_RULES" ]]; then
        if grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$STANDING_RULES" 2>/dev/null; then
            echo "ERROR: Cannot create LIVE_OK - standing rules has enabled entries."
            echo "New risk must go through the outbox. Disable all standing entries first."
            echo "Nothing was copied or loaded."
            exit 1
        fi
    fi
    if [[ ! -f "$LIVE_OK" ]]; then
        echo "Creating LIVE_OK flag (human gate, at the Studio)..."
        touch "$LIVE_OK"
    else
        echo "LIVE_OK already present."
    fi
elif [[ -f "$LIVE_OK" ]]; then
    # The dangerous case the old script only WARNED about: it copied and loaded
    # the --live plist anyway, then printed a warning after the fact.
    echo "REFUSING TO LOAD: $LIVE_OK exists and --live-ok was not passed."
    echo
    echo "The plist above passes --live, so loading it now would arm a daemon"
    echo "that POSTs real orders to Schwab every ${PLIST_INTERVAL}s."
    echo
    echo "To install a NON-live daemon, remove the flag first:"
    echo "    rm \"$LIVE_OK\""
    echo
    echo "To install deliberately LIVE, re-run with:"
    echo "    $0 --live-ok"
    echo
    echo "Nothing was copied or loaded."
    exit 3
fi

# --- 3. resolve the mode from the state that now actually exists on disk ---
if [[ -f "$LIVE_OK" && $PLIST_PASSES_LIVE -eq 1 && "$PLIST_ENV_LIVE" == "1" ]]; then
    MODE="LIVE"
elif [[ $PLIST_PASSES_LIVE -eq 1 ]]; then
    # temple_flow_wire.main() returns 2 immediately when --live is refused. It
    # does NOT fall back to planning, so calling this "dry-run" would be a lie.
    MODE="REFUSE"
else
    MODE="DRY-RUN"
fi

case "$MODE" in
    LIVE)
        echo "MODE: LIVE — LIVE_OK present, plist passes --live, TEMPLE_FLOW_LIVE=1."
        echo "      The daemon WILL POST orders to Schwab every ${PLIST_INTERVAL}s."
        ;;
    REFUSE)
        echo "MODE: REFUSE-AND-EXIT — plist passes --live but LIVE_OK is absent."
        echo "      Each tick logs op=refuse_live and exits 2. It does NOT plan."
        echo "      For a planning dry-run, remove --live from the plist, or run"
        echo "      scripts/temple_flow_wire.py --once by hand."
        ;;
    DRY-RUN)
        echo "MODE: DRY-RUN — plist does not pass --live."
        echo "      The daemon plans and logs. It never POSTs."
        ;;
esac
echo

# --- 4. only now touch the filesystem ---
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
mkdir -p "$REPO_ROOT/config/outbox" "$REPO_ROOT/config/outbox/done" "$REPO_ROOT/config/outbox/failed"

echo "Copying plist to $PLIST_DEST"
cp "$PLIST_SRC" "$PLIST_DEST"

echo "Unloading existing daemon (if any)..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true

echo "Loading daemon..."
launchctl load "$PLIST_DEST"

if [[ ! -f "$STANDING_RULES" ]]; then
    echo
    echo "WARNING: $STANDING_RULES does not exist; the wire falls back to the example."
    echo "Copy it with: cp \"$EXAMPLE_RULES\" \"$STANDING_RULES\""
fi

echo
echo "=== Installation complete (MODE: $MODE) ==="
echo "Log file: $HOME/Library/Logs/temple-flow-wire.log"
echo "View log: tail -f \"$HOME/Library/Logs/temple-flow-wire.log\""
echo
echo "To go dry:   rm \"$LIVE_OK\" && launchctl unload \"$PLIST_DEST\""
echo "To unload:   launchctl unload \"$PLIST_DEST\""
echo "To reload:   launchctl load \"$PLIST_DEST\""
