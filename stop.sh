#!/usr/bin/env bash

PID_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/voice-orb.pid"
ALT_PID_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/floating-recorder.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID="$(cat "$PID_FILE")"
    echo "Stopping Voice Orb (PID: $PID)..."
    kill "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Voice Orb stopped."
elif [ -f "$ALT_PID_FILE" ] && kill -0 "$(cat "$ALT_PID_FILE")" 2>/dev/null; then
    PID="$(cat "$ALT_PID_FILE")"
    echo "Stopping Voice Orb (PID: $PID)..."
    kill "$PID" 2>/dev/null || true
    rm -f "$ALT_PID_FILE"
    echo "Voice Orb stopped."
else
    if pgrep -f "floating_recorder.py" >/dev/null; then
        echo "Terminating running voice-orb processes..."
        pkill -f "floating_recorder.py"
        rm -f "$PID_FILE" "$ALT_PID_FILE"
        echo "Stopped."
    else
        echo "Voice Orb is not running."
    fi
fi
