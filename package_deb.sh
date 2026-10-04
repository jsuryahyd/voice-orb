#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build_deb"
PKG_DIR="$BUILD_DIR/voice-orb_1.0.0_all"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/voice-orb"
mkdir -p "$PKG_DIR/usr/share/applications"

cat << 'EOF' > "$PKG_DIR/DEBIAN/control"
Package: voice-orb
Version: 1.0.0
Architecture: all
Maintainer: Voice Orb Maintainers <admin@jayasurya.one>
Depends: python3, python3-gi, python3-cairo, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, libnotify-bin, xdotool | wtype | ydotool
Section: utils
Priority: optional
Description: Voice Orb - Lightweight Floating Voice Frontend & HTMX Dashboard
 Voice Orb is a floating action button and HTMX web dashboard for Linux desktops
 providing speech-to-text recording, clipboard auto-pasting, thinking-orbs animation,
 and whisper.cpp integration.
EOF

# Copy app files
cp -r "$SCRIPT_DIR/floating_recorder.py" \
      "$SCRIPT_DIR/web_server.py" \
      "$SCRIPT_DIR/icon.png" \
      "$SCRIPT_DIR/static" \
      "$PKG_DIR/usr/share/voice-orb/"

# Copy launchers
cat << 'EOF' > "$PKG_DIR/usr/bin/voice-orb"
#!/usr/bin/env bash
exec python3 /usr/share/voice-orb/floating_recorder.py "$@"
EOF

cat << 'EOF' > "$PKG_DIR/usr/bin/voice-orb-stop"
#!/usr/bin/env bash
pkill -f "/usr/share/voice-orb/floating_recorder.py" 2>/dev/null || pkill -f "floating_recorder.py" 2>/dev/null || true
EOF

cat << 'EOF' > "$PKG_DIR/usr/bin/voice-orb-toggle"
#!/usr/bin/env bash
pkill -USR1 -f "/usr/share/voice-orb/floating_recorder.py" 2>/dev/null || pkill -USR1 -f "floating_recorder.py" 2>/dev/null || true
EOF

chmod +x "$PKG_DIR/usr/bin/voice-orb" "$PKG_DIR/usr/bin/voice-orb-stop" "$PKG_DIR/usr/bin/voice-orb-toggle"

cat << 'EOF' > "$PKG_DIR/usr/share/applications/voice-orb.desktop"
[Desktop Entry]
Name=Voice Orb
Comment=Lightweight Floating Voice Frontend & HTMX Dashboard
Exec=/usr/bin/voice-orb
Icon=/usr/share/voice-orb/icon.png
Terminal=false
Type=Application
Categories=Utility;Audio;AudioVideo;
Keywords=voice;orb;recorder;whisper;transcription;speech;
StartupWMClass=voice-orb
EOF

dpkg-deb --build "$PKG_DIR" "$SCRIPT_DIR/voice-orb_1.0.0_all.deb"
echo "[DEB Packager] Created standalone package: $SCRIPT_DIR/voice-orb_1.0.0_all.deb"
