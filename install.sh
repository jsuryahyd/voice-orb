#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$APP_DIR"

echo "[Voice Orb Installer] Setting up executable symlinks in $BIN_DIR..."
ln -sf "$SCRIPT_DIR/start.sh" "$BIN_DIR/voice-orb"
ln -sf "$SCRIPT_DIR/stop.sh" "$BIN_DIR/voice-orb-stop"
ln -sf "$SCRIPT_DIR/toggle.sh" "$BIN_DIR/voice-orb-toggle"

# Backwards compatibility symlinks
ln -sf "$SCRIPT_DIR/start.sh" "$BIN_DIR/floating-recorder"
ln -sf "$SCRIPT_DIR/stop.sh" "$BIN_DIR/floating-recorder-stop"
ln -sf "$SCRIPT_DIR/toggle.sh" "$BIN_DIR/floating-recorder-toggle"

echo "[Voice Orb Installer] Installing desktop application entry..."
sed -e "s|/home/surya/development/floating-recorder|$SCRIPT_DIR|g" \
    -e "s|/home/surya/.local/bin|$BIN_DIR|g" \
    "$SCRIPT_DIR/voice-orb.desktop" > "$APP_DIR/voice-orb.desktop"

chmod +x "$SCRIPT_DIR/start.sh" "$SCRIPT_DIR/stop.sh" "$SCRIPT_DIR/toggle.sh" "$SCRIPT_DIR/floating_recorder.py"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "[Voice Orb Installer] Setup complete!"
echo "Run 'voice-orb' to start Voice Orb."
