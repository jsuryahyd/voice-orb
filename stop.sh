#!/usr/bin/env bash

PID_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/floating-recorder.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID="$(cat "$PID_FILE")"
    echo "Stopping Floating Recorder (PID: $PID)..."
    kill "$PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Floating Recorder stopped."
else
    if pgrep -f "floating_recorder.py" >/dev/null; then
        echo "Terminating running floating_recorder.py processes..."
        pkill -f "floating_recorder.py"
        rm -f "$PID_FILE"
        echo "Stopped."
    else
        echo "Floating Recorder is not running."
    fi
fi
