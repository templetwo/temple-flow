#!/usr/bin/env bash
# Install Temple Flow Act loop launchd daemon
# One human Terminal command on Mac Studio. Never creates LIVE_OK unless --live-ok passed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_SRC="$REPO_ROOT/deploy/com.templetwo.temple-flow-wire.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.templetwo.temple-flow-wire.plist"
LIVE_OK="$REPO_ROOT/config/LIVE_OK"
STANDING_RULES="$REPO_ROOT/config/standing_rules.json"
EXAMPLE_RULES="$REPO_ROOT/config/standing_rules.example.json"

echo "=== Temple Flow Act-loop installer ==="
echo

# Check if plist source exists
if [[ ! -f "$PLIST_SRC" ]]; then
    echo "ERROR: $PLIST_SRC not found"
    exit 1
fi

# Create LaunchAgents dir if needed
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs"

# Copy plist
echo "Copying plist to $PLIST_DEST"
cp "$PLIST_SRC" "$PLIST_DEST"

# Unload if already loaded (ignore errors)
echo "Unloading existing daemon (if any)..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Load the daemon
echo "Loading daemon..."
launchctl load "$PLIST_DEST"

# Create outbox directories
echo "Creating outbox directories..."
mkdir -p "$REPO_ROOT/config/outbox"
mkdir -p "$REPO_ROOT/config/outbox/done"
mkdir -p "$REPO_ROOT/config/outbox/failed"

# Check standing rules
if [[ ! -f "$STANDING_RULES" ]]; then
    echo "WARNING: $STANDING_RULES does not exist"
    echo "Copy from example: cp \"$EXAMPLE_RULES\" \"$STANDING_RULES\""
fi

# Handle LIVE_OK flag
if [[ "${1:-}" == "--live-ok" ]]; then
    # Check if ETHA is enabled in standing rules
    if [[ -f "$STANDING_RULES" ]]; then
        if grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$STANDING_RULES" 2>/dev/null; then
            echo
            echo "ERROR: Cannot create LIVE_OK - standing rules has enabled entries."
            echo "New risk must go through outbox. Disable all standing entries first."
            exit 1
        fi
    fi
    
    echo
    echo "Creating LIVE_OK flag..."
    touch "$LIVE_OK"
    echo "LIVE GATES OPEN: daemon will POST orders to Schwab"
else
    if [[ -f "$LIVE_OK" ]]; then
        echo
        echo "WARNING: LIVE_OK already exists - daemon will POST to Schwab"
        echo "Remove with: rm \"$LIVE_OK\""
    else
        echo
        echo "DRY-RUN MODE: daemon will plan but not POST"
        echo "To enable live: $0 --live-ok"
    fi
fi

echo
echo "=== Installation complete ==="
echo "Log file: $HOME/Library/Logs/temple-flow-wire.log"
echo "Daemon runs every 15 minutes"
echo "View log: tail -f \"$HOME/Library/Logs/temple-flow-wire.log\""
echo
echo "To unload: launchctl unload \"$PLIST_DEST\""
echo "To reload: launchctl load \"$PLIST_DEST\""
