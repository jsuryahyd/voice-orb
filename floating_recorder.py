#!/usr/bin/env python3
"""
Floating Recorder - Native Linux Floating Voice Recorder with Thinking Orbs
Integrated with whisper.cpp and GStreamer on GNOME / Wayland / X11.
Zero focus-stealing, click-through background, fixed anchoring, and multi-tier global hotkeys.
"""

import sys
import os
import time
import math
import subprocess
import threading
import signal
import struct
import select
import glob
import ast
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gdk, GLib, Gst
import cairo

from web_server import add_transcription, build_transcription_cmd, EmbeddedWebServer

# Initialize GStreamer and GTK
Gst.init(None)
Gtk.init(None)

# Paths & Environment
HOME = os.path.expanduser('~')
CACHE_DIR = os.environ.get('XDG_CACHE_HOME', os.path.join(HOME, '.cache'))
RUNTIME_DIR = os.environ.get('XDG_RUNTIME_DIR', f"/run/user/{os.getuid()}")
os.makedirs(CACHE_DIR, exist_ok=True)

AUDIO_FILE = os.path.join(CACHE_DIR, 'whisper_recording.wav')
PID_FILE = os.path.join(RUNTIME_DIR, 'floating-recorder.pid')
ICON_FILE = os.path.join(HOME, 'development', 'floating-recorder', 'icon.png')

# Whisper CLI Configuration
WHISPER_CLI_CANDIDATES = [
    os.path.join(HOME, '.local', 'bin', 'whisper-cli'),
    os.path.join(HOME, 'development', 'whisper.cpp', 'build', 'bin', 'whisper-cli'),
    'whisper-cli'
]
MODEL_CANDIDATES = [
    os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en-q5_1.bin'),
    os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en.bin'),
    os.path.join(HOME, '.cache', 'openwhispr', 'whisper-models', 'ggml-base.bin'),
    os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-tiny.en.bin')
]

def find_first_existing(candidates):
    for c in candidates:
        if os.path.isfile(c): return c
    return candidates[0]

WHISPER_BIN = find_first_existing(WHISPER_CLI_CANDIDATES)
WHISPER_MODEL = find_first_existing(MODEL_CANDIDATES)

print(f"[Floating Recorder] Whisper binary: {WHISPER_BIN}")
print(f"[Floating Recorder] Whisper model:  {WHISPER_MODEL}")

# --- Auto Paste Automation ---
def paste_text(text):
    if not text:
        return
    time.sleep(0.18)  # Let clipboard events settle and input focus stabilize
    
    env = os.environ.copy()
    socket_path = os.path.join(RUNTIME_DIR, "ydotoold.socket")
    if os.path.exists(socket_path):
        env["YDOTOOL_SOCKET"] = socket_path

    # Method 1: ydotool key ctrl+v
    try:
        res = subprocess.run(
            ['ydotool', 'key', 'ctrl+v'],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )
        if res.returncode == 0:
            print("[Floating Recorder] Auto-pasted via ydotool Ctrl+V")
            return
    except Exception:
        pass

    # Method 2: ydotool type
    try:
        res = subprocess.run(
            ['ydotool', 'type', text],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3
        )
        if res.returncode == 0:
            print("[Floating Recorder] Auto-pasted via ydotool type")
            return
    except Exception:
        pass

    # Method 3: xdotool key
    try:
        res = subprocess.run(
            ['xdotool', 'key', 'ctrl+v'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )
        if res.returncode == 0:
            print("[Floating Recorder] Auto-pasted via xdotool")
            return
    except Exception:
        pass

# --- GNOME Settings-Daemon Global Shortcut Registration ---
def setup_gnome_shortcut():
    schema = 'org.gnome.settings-daemon.plugins.media-keys'
    custom_schema = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
    rel_path = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/floating-recorder/'
    toggle_bin = os.path.join(HOME, '.local', 'bin', 'floating-recorder-toggle')

    try:
        out = subprocess.check_output(['gsettings', 'get', schema, 'custom-keybindings'], text=True).strip()
        if out.startswith('@as '):
            out = out[4:]
        try:
            bindings = ast.literal_eval(out)
        except Exception:
            bindings = []
        if not isinstance(bindings, list):
            bindings = []
            
        subprocess.run(['gsettings', 'set', f"{custom_schema}:{rel_path}", 'name', 'Floating Recorder Toggle'], check=True)
        subprocess.run(['gsettings', 'set', f"{custom_schema}:{rel_path}", 'command', toggle_bin], check=True)
        subprocess.run(['gsettings', 'set', f"{custom_schema}:{rel_path}", 'binding', '<Control><Alt>r'], check=True)
        
        if rel_path not in bindings:
            bindings.append(rel_path)
            subprocess.run(['gsettings', 'set', schema, 'custom-keybindings', str(bindings)], check=True)
        print("[Floating Recorder] Registered GNOME global shortcut: <Control><Alt>r")
    except Exception as e:
        print("[Floating Recorder] GNOME shortcut registration note:", e)

# --- Thinking Orbs Geometry & Algorithms (from thinking-orbs library) ---
def makeProj(yaw, tilt, cx, cy, scale):
    st = math.sin(tilt)
    ct = math.cos(tilt)
    sy = math.sin(yaw)
    cyw = math.cos(yaw)
    def proj(x, y, z):
        x1 = x * cyw + z * sy
        z1 = -x * sy + z * cyw
        y1 = y * ct - z1 * st
        z2 = y * st + z1 * ct
        return (cx + x1 * scale, cy - y1 * scale, z2)
    return proj

def hashD(a, b):
    h = math.sin(a * 12.9898 + b * 78.233) * 43758.5453
    return h - math.floor(h)

def radiusScale(size, pow_val):
    return (size / 300.0) ** pow_val

def frameRing(size, t):
    opts = {'lanes': 11, 'segs': 44, 'rBase': 1.05, 'rDepth': 1.62, 'rsPow': 0.6, 'spin': 0, 'wobMul': 0.368, 'rMin': 0.3}
    cx, cy = size / 2, size / 2
    R = size / 2 * 0.78
    camTilt = 0.3
    speed_t = t * 3.24
    pt = makeProj(speed_t * 0.1 * opts['spin'], camTilt, cx, cy, 1)
    rs = radiusScale(size, opts['rsPow'])
    dots = []
    ya = speed_t * 0.24 * opts['spin']
    ta = -camTilt
    ux, uy, uz = math.cos(ya), 0, math.sin(ya)
    vx = -uz * math.sin(ta)
    vy = math.cos(ta)
    vz = ux * math.sin(ta)
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    wobAmp = 0.23 * opts['wobMul']
    baseR = R / (1 + 0.85 * wobAmp)
    
    for w in range(opts['lanes']):
        laneOff = (w - (opts['lanes'] - 1) / 2.0) * 0.075
        edge = abs(w - (opts['lanes'] - 1) / 2.0) / max(1, (opts['lanes'] - 1) / 2.0)
        for k in range(opts['segs']):
            a = k / opts['segs'] * 2 * math.pi
            wob = (0.16 * math.sin(a * 3 - speed_t * 1.7 + w * 0.22) + 0.07 * math.sin(a * 5 + speed_t * 1.1)) * opts['wobMul']
            radial = 1 + wob
            x = ux * math.cos(a) + vx * math.sin(a) + nx * laneOff
            y = uy * math.cos(a) + vy * math.sin(a) + ny * laneOff
            z = uz * math.cos(a) + vz * math.sin(a) + nz * laneOff
            l = math.hypot(x, math.hypot(y, z))
            if l == 0: l = 1e-6
            rr = baseR * radial
            px, py, zr = pt(x / l * rr, y / l * rr, z / l * rr)
            depth = (zr / R + 1) / 2
            
            r_dot = (opts['rBase'] + opts['rDepth'] * depth) * (1 - 0.25 * edge) * rs
            if r_dot < opts['rMin']: r_dot = opts['rMin']
            white = 0.52 - 0.44 * depth + 0.18 * edge
            dots.append({'x': px, 'y': py, 'z': zr, 'r': r_dot, 'w': white, 'a': 0.4 + 0.6 * depth})
    return dots

def frameWave(size, t):
    opts = {'rings': 9, 'lonDensity': 23, 'rBase': 0.6, 'rDepth': 1.7, 'rsPow': 0.6, 'rMin': 0.3}
    cx, cy = size / 2, size / 2
    R = size / 2 * 0.874
    speed_t = t * 4.388
    pt = makeProj(speed_t * 0.18, 0.38, cx, cy, 1)
    rs = radiusScale(size, opts['rsPow'])
    dots = []
    for ri in range(opts['rings'] + 1):
        lat = -math.pi / 2 + (ri / opts['rings']) * math.pi
        cosLat, sinLat = math.cos(lat), math.sin(lat)
        w = 0.62 * math.sin(speed_t * 2.1 - ri * 0.52) + 0.38 * math.sin(speed_t * 1.27 + ri * 0.83)
        rr = R * (0.88 + 0.105 * w)
        lonCount = max(1, round(abs(cosLat) * opts['lonDensity']))
        for lj in range(lonCount):
            lon = (lj / lonCount) * 2 * math.pi
            px, py, z = pt(cosLat * math.cos(lon) * rr, sinLat * rr, cosLat * math.sin(lon) * rr)
            depth = (z / R + 1) / 2
            crest = max(0, w)
            r_dot = (opts['rBase'] + opts['rDepth'] * depth) * (1 + 0.4 * crest) * rs
            if r_dot < opts['rMin']: r_dot = opts['rMin']
            white = 0.66 - 0.56 * depth - 0.1 * crest
            dots.append({'x': px, 'y': py, 'z': z, 'r': r_dot, 'w': white, 'a': 1.0})
    return dots

def frameOrbits(size, t):
    opts = {'orbitN': 12, 'ghostN': 40, 'ghostR': 0.9, 'ghostA': 0.5, 'particles': 3, 'partR': 1.2, 'partRDepth': 1.6, 'rsPow': 0.6, 'rMin': 0.3}
    cx, cy = size / 2, size / 2
    R = size / 2 * 0.82
    speed_t = t * 1.885
    pt = makeProj(speed_t * 0.12, 0.3, cx, cy, 1)
    rs = radiusScale(size, opts['rsPow'])
    dots = []
    for orb in range(opts['orbitN']):
        h1, h2, h3 = hashD(orb, 1.7), hashD(orb, 5.2), hashD(orb, 8.9)
        ro = R * (0.45 + 0.52 * h1)
        th = h1 * 2 * math.pi
        phi = math.acos(2 * h2 - 1)
        nx, ny, nz = math.sin(phi) * math.cos(th), math.cos(phi), math.sin(phi) * math.sin(th)
        ux, uy, uz = -ny, nx, 0
        ul = max(1e-6, math.hypot(ux, uy))
        ux, uy = ux / ul, uy / ul
        vx = ny * uz - nz * uy
        vy = nz * ux - nx * uz
        vz = nx * uy - ny * ux
        speed = (0.25 + 0.55 * h3) * (1 if h3 > 0.5 else -1)
        
        for k in range(opts['ghostN']):
            a = k / opts['ghostN'] * 2 * math.pi
            px, py, z = pt((ux * math.cos(a) + vx * math.sin(a)) * ro, (uy * math.cos(a) + vy * math.sin(a)) * ro, (uz * math.cos(a) + vz * math.sin(a)) * ro)
            depth = (z / ro + 1) / 2
            r_dot = opts['ghostR'] * rs
            if r_dot < opts['rMin']: r_dot = opts['rMin']
            dots.append({'x': px, 'y': py, 'z': z, 'r': r_dot, 'w': 0.72, 'a': opts['ghostA'] * (0.4 + 0.6 * depth)})
            
        for m in range(opts['particles']):
            a = speed_t * speed + (m / opts['particles']) * 2 * math.pi + h2 * 6
            px, py, z = pt((ux * math.cos(a) + vx * math.sin(a)) * ro, (uy * math.cos(a) + vy * math.sin(a)) * ro, (uz * math.cos(a) + vz * math.sin(a)) * ro)
            depth = (z / ro + 1) / 2
            r_dot = (opts['partR'] + opts['partRDepth'] * depth) * rs
            if r_dot < opts['rMin']: r_dot = opts['rMin']
            dots.append({'x': px, 'y': py, 'z': z, 'r': r_dot, 'w': 0.3 - 0.22 * depth, 'a': 1.0})
    return dots


class FloatingRecorderWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        GLib.set_prgname('floating-recorder')
        GLib.set_application_name('Floating Recorder')
        self.set_title('Floating Recorder')
        
        if os.path.isfile(ICON_FILE):
            try: self.set_icon_from_file(ICON_FILE)
            except Exception: pass

        # --- Window Rules & Behavior ---
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_resizable(False)

        # 1. CRITICAL: Never steal focus from active windows / inputs!
        self.set_accept_focus(False)
        self.set_focus_on_map(False)

        # 2. CRITICAL: Always stay on top of other applications across all workspaces
        self.set_keep_above(True)
        self.stick()

        # 3. Transparency support
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Fixed dimensions to eliminate coordinate shifting
        self.fixed_width = 380
        self.fixed_height = 180
        self.set_default_size(self.fixed_width, self.fixed_height)

        # Mathematically fixed center coordinates
        self.cx = self.fixed_width - 70.0  # 310.0
        self.cy = 80.0
        self.orb_radius = 50.0

        # State management
        self.state = 'breathing'
        self.anim_time = 0.0
        self.press_start_time = None
        self.is_held = False
        self.is_recording = False
        self.recording_start_time = None
        
        self.gst_pipeline = None
        self.transcript = ''
        self.transcript_dismiss_timer = None

        # Event mask
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )

        self.connect('draw', self.on_draw)
        self.connect('button-press-event', self.on_button_press)
        self.connect('button-release-event', self.on_button_release)
        self.connect('map-event', self.on_map_event)
        self.connect('window-state-event', self.on_window_state_event)
        self.connect('destroy', Gtk.main_quit)

        # Animation timer (30 FPS)
        self.timer_id = GLib.timeout_add(33, self.on_animation_tick)

        # Watchdog to enforce always-on-top
        self.keep_above_watchdog = GLib.timeout_add_seconds(3, self.enforce_always_on_top)

        # Start raw /dev/input thread for Right Ctrl push-to-talk
        threading.Thread(target=self.raw_input_listener_thread, daemon=True).start()

    def enforce_always_on_top(self):
        self.set_keep_above(True)
        self.stick()
        return True

    def on_map_event(self, widget, event):
        self.enforce_always_on_top()
        self.update_input_shape()
        return False

    def on_window_state_event(self, widget, event):
        if not (event.new_window_state & Gdk.WindowState.ABOVE):
            self.set_keep_above(True)
        return False

    def update_input_shape(self):
        """Combines an input shape mask so transparent areas are 100% click-through."""
        gdk_win = self.get_window()
        if not gdk_win:
            return

        # 1. Bounding box around circular orb and top drag handle
        orb_x = int(self.cx - self.orb_radius - 6)
        orb_y = int(self.cy - self.orb_radius - 24)
        orb_w = int((self.orb_radius + 6) * 2)
        orb_h = int((self.orb_radius + 6) * 2 + 24)
        region = cairo.Region(cairo.RectangleInt(orb_x, orb_y, orb_w, orb_h))

        # 2. Add pill area if active (recording, working, or showing transcript)
        if self.state in ('listening', 'working') or self.transcript:
            pill_rect = cairo.RectangleInt(
                int(self.cx - 290),
                int(self.cy + 42),
                310,
                42
            )
            region.union(pill_rect)

        gdk_win.input_shape_combine_region(region, 0, 0)

    def on_animation_tick(self):
        self.anim_time += 0.033
        if self.anim_time > 10000.0:
            self.anim_time = 0.0
        self.queue_draw()
        return True

    def on_draw(self, widget, cr):
        # 1. Clear with true transparent RGBA
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        cx = self.cx
        cy = self.cy
        orb_radius = self.orb_radius

        # Top Drag Handle Grip
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.35)
        cr.set_line_width(3.0)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(cx - 16, cy - 60)
        cr.line_to(cx + 16, cy - 60)
        cr.stroke()

        # Glass Background Circle
        cr.arc(cx, cy, orb_radius, 0, 2 * math.pi)
        bg_pat = cairo.RadialGradient(cx, cy - 16, 6, cx, cy, orb_radius)
        if self.state == 'listening':
            bg_pat.add_color_stop_rgba(0.0, 0.28, 0.06, 0.06, 0.94)
            bg_pat.add_color_stop_rgba(1.0, 0.12, 0.02, 0.02, 0.90)
        elif self.state == 'working':
            bg_pat.add_color_stop_rgba(0.0, 0.05, 0.14, 0.28, 0.94)
            bg_pat.add_color_stop_rgba(1.0, 0.02, 0.04, 0.12, 0.90)
        else:
            bg_pat.add_color_stop_rgba(0.0, 0.14, 0.15, 0.22, 0.92)
            bg_pat.add_color_stop_rgba(1.0, 0.06, 0.06, 0.10, 0.88)
        cr.set_source(bg_pat)
        cr.fill_preserve()

        # Border outline
        if self.state == 'listening':
            cr.set_source_rgba(0.94, 0.27, 0.27, 0.7)
            cr.set_line_width(2.0)
        elif self.state == 'working':
            cr.set_source_rgba(0.23, 0.51, 0.96, 0.7)
            cr.set_line_width(2.0)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
            cr.set_line_width(1.5)
        cr.stroke()

        # Dotted Particle Thinking Orbs Engine
        t = self.anim_time
        size = 64
        if self.state == 'breathing':
            dots = frameRing(size, t)
        elif self.state == 'listening':
            dots = frameWave(size, t)
        elif self.state == 'working':
            dots = frameOrbits(size, t)
        else:
            dots = []

        dots.sort(key=lambda d: d.get('z', 0))
        for d in dots:
            alpha = d.get('a', 1.0)
            if alpha < 0.02: continue
            w = max(0, min(1, d.get('w', 1.0)))
            g = 1 - w  # Dark palette ramp
            cr.set_source_rgba(g, g, g, alpha)
            cr.arc(cx - size/2 + d['x'], cy - size/2 + d['y'], d['r'], 0, 2 * math.pi)
            cr.fill()

        # Center Microphone Icon
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.arc(cx, cy - 4, 7, math.pi, 2 * math.pi)
        cr.line_to(cx + 7, cy + 4)
        cr.arc(cx, cy + 4, 7, 0, math.pi)
        cr.close_path()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.95)
        cr.fill()
        
        cr.arc(cx, cy + 3, 11, 0, math.pi)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.9)
        cr.set_line_width(2.0)
        cr.stroke()
        
        cr.move_to(cx, cy + 14)
        cr.line_to(cx, cy + 20)
        cr.move_to(cx - 6, cy + 20)
        cr.line_to(cx + 6, cy + 20)
        cr.stroke()

        # Status Pill / Transcript
        if self.transcript:
            pill_text = self.transcript
            if len(pill_text) > 38: pill_text = pill_text[:38] + "…"
            self.draw_pill(cr, cx, cy + 62, f"✓ {pill_text}", success=True)
        else:
            if self.state == 'listening':
                elapsed = int(time.time() - (self.recording_start_time or time.time()))
                mins, secs = elapsed // 60, elapsed % 60
                self.draw_pill(cr, cx, cy + 58, f"● REC {mins:02d}:{secs:02d} (Release to stop)", recording=True)
            elif self.state == 'working':
                self.draw_pill(cr, cx, cy + 58, "⟳ Transcribing with whisper...", working=True)

        return False

    def draw_pill(self, cr, px, py, text, success=False, recording=False, working=False):
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if success else cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10.5)
        extents = cr.text_extents(text)
        pw = max(120.0, extents.width + 24.0)
        ph = 24.0
        # Anchored to expand to the left so it stays nicely inside screen bounds
        x0 = px - pw + 35
        y0 = py - (ph / 2.0)
        r = 12.0

        cr.new_sub_path()
        cr.arc(x0 + pw - r, y0 + r, r, -math.pi / 2, 0)
        cr.arc(x0 + pw - r, y0 + ph - r, r, 0, math.pi / 2)
        cr.arc(x0 + r, y0 + ph - r, r, math.pi / 2, math.pi)
        cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        if success:
            cr.set_source_rgba(0.08, 0.18, 0.12, 0.94)
            cr.fill_preserve()
            cr.set_source_rgba(0.2, 0.85, 0.45, 0.6)
        elif recording:
            cr.set_source_rgba(0.24, 0.05, 0.05, 0.94)
            cr.fill_preserve()
            cr.set_source_rgba(0.94, 0.27, 0.27, 0.7)
        elif working:
            cr.set_source_rgba(0.05, 0.14, 0.24, 0.94)
            cr.fill_preserve()
            cr.set_source_rgba(0.23, 0.51, 0.96, 0.7)
        else:
            cr.set_source_rgba(0.08, 0.09, 0.14, 0.88)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
            
        cr.set_line_width(1.4)
        cr.stroke()

        tx = x0 + (pw - extents.width) / 2.0 - extents.x_bearing
        ty = y0 + (ph - extents.height) / 2.0 - extents.y_bearing
        if success: cr.set_source_rgba(0.4, 1.0, 0.6, 0.98)
        elif recording: cr.set_source_rgba(1.0, 0.65, 0.65, 0.98)
        elif working: cr.set_source_rgba(0.65, 0.88, 1.0, 0.98)
        else: cr.set_source_rgba(0.9, 0.9, 0.9, 0.9)
        cr.move_to(tx, ty)
        cr.show_text(text)

    # --- Mouse & Interaction Handlers ---
    def on_button_press(self, widget, event):
        dist = math.hypot(event.x - self.cx, event.y - self.cy)

        # Drag window via handle or shift-click
        if (event.state & Gdk.ModifierType.SHIFT_MASK) or (event.button == 2) or (event.y < self.cy - 50):
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
            return True

        # Click inside the Orb
        if dist <= self.orb_radius + 4 and event.button == 1:
            if not self.is_recording:
                self.is_held = True
                self.press_start_time = time.time()
                self.start_recording()
            else:
                self.is_held = False
                self.stop_recording()
            return True

        # Right-click inside the Orb: Open context menu / Web Dashboard
        if dist <= self.orb_radius + 4 and event.button == 3:
            self.show_context_menu(event)
            return True

        # Click on transcript pill: Dismiss it early
        if self.transcript and event.y > self.cy + 40:
            self.clear_transcript()
            return True

        return False

    def show_context_menu(self, event):
        menu = Gtk.Menu()

        item_web = Gtk.MenuItem(label="Open Web Dashboard (HTMX)")
        item_web.connect("activate", lambda _: subprocess.Popen(['xdg-open', f"http://127.0.0.1:{getattr(self, 'web_port', 8088)}/"]))
        menu.append(item_web)

        if self.transcript:
            item_copy = Gtk.MenuItem(label="Copy Last Transcript")
            item_copy.connect("activate", lambda _: self.copy_to_clipboard(self.transcript))
            menu.append(item_copy)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit Floating Recorder")
        item_quit.connect("activate", lambda _: Gtk.main_quit())
        menu.append(item_quit)

        menu.show_all()
        menu.popup_at_pointer(event)

    def on_button_release(self, widget, event):
        if event.button == 1 and self.is_held:
            self.is_held = False
            duration = time.time() - (self.press_start_time or time.time())
            if duration >= 0.35:
                # Hold mode: stop on release
                self.stop_recording()
            return True
        return False

    def toggle_recording(self):
        """Toggle recording state via global hotkey / CLI signal."""
        if not self.is_recording:
            self.is_held = False
            self.start_recording()
        else:
            self.is_held = False
            self.stop_recording()

    # --- Audio Recording via GStreamer ---
    def start_recording(self):
        if self.is_recording: return
        self.clear_transcript()
        self.state = 'listening'
        self.is_recording = True
        self.recording_start_time = time.time()
        self.update_input_shape()
        print(f"[Floating Recorder] Recording started -> {AUDIO_FILE}")

        if self.gst_pipeline:
            self.gst_pipeline.set_state(Gst.State.NULL)
            self.gst_pipeline = None

        if os.path.exists(AUDIO_FILE):
            try: os.remove(AUDIO_FILE)
            except OSError: pass

        try:
            desc = f"autoaudiosrc ! audioconvert ! audioresample ! audio/x-raw,rate=16000,channels=1,format=S16LE ! wavenc ! filesink location={AUDIO_FILE}"
            self.gst_pipeline = Gst.parse_launch(desc)
            self.gst_pipeline.set_state(Gst.State.PLAYING)
        except Exception as e:
            print(f"[Floating Recorder] GStreamer error: {e}", file=sys.stderr)
            self.state = 'breathing'
            self.is_recording = False
            self.update_input_shape()

    def stop_recording(self):
        if not self.is_recording: return
        self.is_recording = False
        self.state = 'working'
        self.last_recording_duration = max(0.1, time.time() - (self.recording_start_time or time.time()))
        self.update_input_shape()
        print("[Floating Recorder] Recording stopped, finalizing audio...")

        if self.gst_pipeline:
            self.gst_pipeline.send_event(Gst.Event.new_eos())

            def finalize_and_transcribe():
                if self.gst_pipeline:
                    self.gst_pipeline.set_state(Gst.State.NULL)
                    self.gst_pipeline = None
                if os.path.exists(AUDIO_FILE) and os.path.getsize(AUDIO_FILE) > 44:
                    print(f"[Floating Recorder] Audio ready ({os.path.getsize(AUDIO_FILE)} bytes), transcribing...")
                    threading.Thread(target=self.run_whisper_transcription, daemon=True).start()
                else:
                    GLib.idle_add(self.on_transcription_finished, "")
                return False

            GLib.timeout_add(250, finalize_and_transcribe)

    def run_whisper_transcription(self):
        cmd = build_transcription_cmd(AUDIO_FILE)
        print(f"[Floating Recorder] Executing transcription command: {' '.join(cmd)}")
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            text = ' '.join((res.stdout or '').strip().split())
            print(f"[Floating Recorder] Transcription result: '{text}'")
            GLib.idle_add(self.on_transcription_finished, text)
        except Exception as e:
            print(f"[Floating Recorder] Whisper error: {e}", file=sys.stderr)
            GLib.idle_add(self.on_transcription_finished, "")

    def on_transcription_finished(self, text):
        self.state = 'breathing'
        if text:
            self.transcript = text
            self.copy_to_clipboard(text)
            self.send_desktop_notification(text)

            # Persist to history for HTMX web dashboard
            duration = getattr(self, 'last_recording_duration', 0.0)
            add_transcription(text, duration_sec=duration)
            
            # Auto-paste directly into previously focused application
            threading.Thread(target=paste_text, args=(text,), daemon=True).start()

            if self.transcript_dismiss_timer:
                GLib.source_remove(self.transcript_dismiss_timer)
            self.transcript_dismiss_timer = GLib.timeout_add_seconds(7, self.clear_transcript)
        else:
            self.clear_transcript()

        self.update_input_shape()

    def clear_transcript(self):
        if self.transcript_dismiss_timer:
            GLib.source_remove(self.transcript_dismiss_timer)
            self.transcript_dismiss_timer = None
        self.transcript = ''
        self.update_input_shape()
        self.queue_draw()
        return False

    def copy_to_clipboard(self, text):
        try:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).set_text(text, -1)
        except Exception as e:
            print(f"[Floating Recorder] Clipboard error: {e}", file=sys.stderr)

    def send_desktop_notification(self, text):
        try:
            subprocess.Popen([
                'notify-send',
                '-a', 'Floating Recorder',
                '-i', 'audio-input-microphone',
                'Transcription Copied & Pasted',
                text.replace('"', '\\"')
            ])
        except Exception:
            pass

    # --- Raw Input Device Listener for Push-to-Talk ---
    def raw_input_listener_thread(self):
        KEY_RIGHTCTRL = 97
        EVENT_FORMAT = 'qqHHi'
        EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
        
        fds = []
        for path in sorted(glob.glob('/dev/input/event*')):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                fds.append(fd)
            except (PermissionError, OSError):
                continue
                
        if not fds:
            print("[Floating Recorder] /dev/input/event* not readable. Push-to-talk via Right Ctrl disabled.")
            print("[Floating Recorder] To enable Right Ctrl hold-to-talk: sudo usermod -aG input $USER (or sudo chmod a+r /dev/input/event*)")
            print("[Floating Recorder] You can also use GNOME global shortcut <Control><Alt>r or run 'floating-recorder-toggle'.")
            return

        print(f"[Floating Recorder] Monitoring {len(fds)} raw input devices for Right Ctrl push-to-talk...")
        poll = select.poll()
        for fd in fds:
            poll.register(fd, select.POLLIN)

        pressed = False
        while True:
            try:
                events = poll.poll(1000)
                for fd, mask in events:
                    if mask & select.POLLIN:
                        while True:
                            try:
                                data = os.read(fd, EVENT_SIZE)
                                if len(data) < EVENT_SIZE:
                                    break
                                sec, usec, ev_type, ev_code, ev_value = struct.unpack(EVENT_FORMAT, data)
                                # EV_KEY is type 1
                                if ev_type == 1 and ev_code == KEY_RIGHTCTRL:
                                    if ev_value == 1 and not pressed:
                                        pressed = True
                                        print("[Floating Recorder] Push-to-talk started (Right Ctrl)")
                                        GLib.idle_add(self.start_recording)
                                    elif ev_value == 0 and pressed:
                                        pressed = False
                                        print("[Floating Recorder] Push-to-talk ended (Right Ctrl)")
                                        GLib.idle_add(self.stop_recording)
                            except (BlockingIOError, OSError):
                                break
            except Exception as e:
                time.sleep(1)


def main():
    # Save PID
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    # Register GNOME custom keybinding
    setup_gnome_shortcut()

    win = FloatingRecorderWindow()

    # Start embedded HTMX web dashboard (same app)
    web_port = int(os.environ.get("RECORDER_PORT", 8088))
    win.web_port = web_port
    web_server = EmbeddedWebServer(
        host="127.0.0.1",
        port=web_port,
        toggle_callback=lambda: GLib.idle_add(win.toggle_recording)
    )
    web_server.start()

    # Handle SIGUSR1 to toggle recording
    def on_sigusr1(signum, frame):
        GLib.idle_add(win.toggle_recording)
    signal.signal(signal.SIGUSR1, on_sigusr1)

    win.show_all()
    win.enforce_always_on_top()

    # Anchor to bottom-right of primary display work area
    try:
        display = Gdk.Display.get_default()
        if display:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            if monitor:
                geom = monitor.get_workarea() if hasattr(monitor, 'get_workarea') else monitor.get_geometry()
                margin_x, margin_y = 20, 20
                x = geom.x + geom.width - win.fixed_width - margin_x
                y = geom.y + geom.height - win.fixed_height - margin_y
                win.move(max(0, x), max(0, y))
    except Exception as e:
        print("[Floating Recorder] Positioning note:", e)

    try:
        Gtk.main()
    finally:
        web_server.stop()
        if os.path.exists(PID_FILE):
            try: os.remove(PID_FILE)
            except OSError: pass


if __name__ == '__main__':
    main()
