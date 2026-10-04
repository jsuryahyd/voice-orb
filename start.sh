#!/usr/bin/env bash
set -e

# Detect display environment if not set
if [ -z "$XDG_RUNTIME_DIR" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi

if [ -z "$WAYLAND_DISPLAY" ] && [ -e "$XDG_RUNTIME_DIR/wayland-0" ]; then
    export WAYLAND_DISPLAY="wayland-0"
fi

if [ -z "$DISPLAY" ]; then
    export DISPLAY=":0"
fi

# Resolve canonical script directory even when invoked through a symlink
SCRIPT_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
APP_PATH="$SCRIPT_DIR/floating_recorder.py"
LOG_FILE="${XDG_CACHE_HOME:-$HOME/.cache}/voice-orb.log"
PID_FILE="${XDG_RUNTIME_DIR}/voice-orb.pid"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Voice Orb is already running (PID: $(cat "$PID_FILE"))."
    exit 0
fi

echo "Starting Voice Orb with native whisper.cpp integration..."
PYTHONUNBUFFERED=1 setsid python3 -u "$APP_PATH" </dev/null >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 1
if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "Voice Orb started successfully! (PID: $NEW_PID)"
    echo "Logs: $LOG_FILE"
else
    echo "Failed to start Voice Orb. Check $LOG_FILE for details."
    rm -f "$PID_FILE"
    exit 1
fi
