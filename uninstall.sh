#!/usr/bin/env bash
set -e

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

echo "[Voice Orb Uninstaller] Stopping running Voice Orb instances..."
pkill -f "floating_recorder.py" 2>/dev/null || true

echo "[Voice Orb Uninstaller] Removing binary symlinks and desktop entries..."
rm -f "$BIN_DIR/voice-orb" "$BIN_DIR/voice-orb-stop" "$BIN_DIR/voice-orb-toggle"
rm -f "$BIN_DIR/floating-recorder" "$BIN_DIR/floating-recorder-stop" "$BIN_DIR/floating-recorder-toggle"
rm -f "$APP_DIR/voice-orb.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "[Voice Orb Uninstaller] Voice Orb uninstalled successfully."
