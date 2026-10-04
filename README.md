# 🎙️ Voice Orb

> **Voice Orb** is a ultra-lightweight, high-performance native Linux floating voice frontend and HTMX web dashboard for AI speech transcription.

Designed specifically for performance on laptops and low-spec systems, Voice Orb runs on pure Python 3 + GTK3 + Cairo, consuming **<0.1% CPU at idle** and **~45MB RAM** (unlike heavy Electron apps).

---

## ✨ Key Features

- 🟢 **Floating Floating Orb Widget**: Beautiful Cairo-drawn dot-matrix animations (Breathing, Wave, Orbits) ported from `thinking-orbs`.
- 📌 **Always-On-Top & Non-Intrusive**: Anchored bottom-right with `DOCK` layer hints — stays visible across workspaces without stealing input focus.
- ⚡ **Native 16kHz Audio Pipeline**: GStreamer records directly into 16kHz WAV format required by local inference engines.
- 🎙️ **Push-to-Talk & Hotkeys**:
  - Hold **Right Ctrl** for Push-to-Talk (via raw `/dev/input/` events).
  - Press **Ctrl+Alt+R** or click the Orb for toggle recording.
- 📋 **Seamless Auto-Paste**: Auto-pastes transcribed text directly into your active window via `ydotool` / `xdotool` + copies to `CLIPBOARD` & `PRIMARY`.
- 🌐 **HTMX Web Dashboard**: Embedded `ThreadingHTTPServer` hosting a live transcription history page with search, copy, delete, and **Integrations Manager**.
- 🔌 **Extensible Integrations**: Dynamically configures local inference binaries (`whisper.cpp` `whisper-cli`), models, and CLI arguments via the UI or `~/.cache/voice-orb-config.json`.

---

## 🚀 Quick Start

### Prerequisites (Ubuntu / Debian / Fedora Arch)

```bash
# Ubuntu/Debian dependencies
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gstreamer1.0-plugins-good ydotool xdotool
```

### Installation

```bash
git clone https://github.com/jsuryahyd/voice-orb.git
cd voice-orb
chmod +x start.sh toggle.sh stop.sh
```

### Running

```bash
./start.sh
```

Open the web dashboard in your browser:
**`http://127.0.0.1:8088/`** (or right-click the orb floating on your screen).

---

## 🛠️ Configuration & Integrations

Navigate to the **Integrations** tab on the web dashboard to set your local `whisper-cli` executable path, GGML model file location (`.bin`), and extra flags.

Settings are saved in `~/.cache/voice-orb-config.json` and applied instantly to new recordings without restarting the app.

---

## 📄 License

MIT License.
