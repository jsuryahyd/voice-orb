#!/usr/bin/env bash
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
PID_FILE="$RUNTIME_DIR/voice-orb.pid"
ALT_PID_FILE="$RUNTIME_DIR/floating-recorder.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill -USR1 "$PID"
        exit 0
    fi
fi

if [ -f "$ALT_PID_FILE" ]; then
    PID=$(cat "$ALT_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill -USR1 "$PID"
        exit 0
    fi
fi

pkill -USR1 -f "floating_recorder.py" 2>/dev/null || true
