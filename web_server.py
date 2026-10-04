"""
Embedded Web Server for Voice Orb (Floating Recorder)
Provides a minimal, fast HTMX-powered dashboard for viewing, copying,
managing transcriptions, and configuring recording integrations (whisper.cpp).
"""

import os
import time
import json
import hashlib
import html
import urllib.parse
import subprocess
import signal
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading

HOME = os.path.expanduser('~')
CACHE_DIR = os.environ.get('XDG_CACHE_HOME', os.path.join(HOME, '.cache'))
HISTORY_FILE = os.path.join(CACHE_DIR, 'floating-recorder-history.json')
CONFIG_FILE = os.path.join(CACHE_DIR, 'voice-orb-config.json')
STATIC_DIR = os.path.join(HOME, 'development', 'floating-recorder', 'static')

DEFAULT_CONFIG = {
    "active_integration": "whisper_cpp",
    "whisper_cpp": {
        "binary_path": os.path.join(HOME, '.local', 'bin', 'whisper-cli'),
        "model_path": os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en-q5_1.bin'),
        "cli_args": "-nt -np -t 4",
        "start_command": os.path.join(HOME, 'development', 'whisper.cpp', 'build', 'bin', 'whisper-server') + f" -m {os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en-q5_1.bin')} --port 8080"
    }
}

INTEGRATED_SERVICE_PROCESS = None

def get_service_status():
    global INTEGRATED_SERVICE_PROCESS
    if INTEGRATED_SERVICE_PROCESS is not None:
        poll = INTEGRATED_SERVICE_PROCESS.poll()
        if poll is None:
            return True, INTEGRATED_SERVICE_PROCESS.pid
        else:
            INTEGRATED_SERVICE_PROCESS = None
    return False, None

def start_integrated_service(cmd_str):
    global INTEGRATED_SERVICE_PROCESS
    is_running, pid = get_service_status()
    if is_running:
        return False, f"Service is already running (PID {pid})"
    
    cmd_str = cmd_str.strip()
    if not cmd_str:
        return False, "No start command specified"
        
    try:
        INTEGRATED_SERVICE_PROCESS = subprocess.Popen(
            cmd_str,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        time.sleep(0.5)
        poll = INTEGRATED_SERVICE_PROCESS.poll()
        if poll is not None:
            err = INTEGRATED_SERVICE_PROCESS.stderr.read().decode('utf-8', errors='replace')
            INTEGRATED_SERVICE_PROCESS = None
            return False, f"Service exited immediately (code {poll}): {err[:200]}"
        return True, f"Integrated service started successfully (PID {INTEGRATED_SERVICE_PROCESS.pid})"
    except Exception as e:
        INTEGRATED_SERVICE_PROCESS = None
        return False, f"Failed to start service: {str(e)}"

def stop_integrated_service():
    global INTEGRATED_SERVICE_PROCESS
    is_running, pid = get_service_status()
    if not is_running:
        return False, "Service is not running"
    
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        try:
            INTEGRATED_SERVICE_PROCESS.wait(timeout=2)
        except Exception:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception as e:
        print("[Service Manager] Stop error:", e)
    INTEGRATED_SERVICE_PROCESS = None
    return True, "Integrated service stopped successfully"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            if 'whisper_cpp' not in cfg:
                cfg['whisper_cpp'] = DEFAULT_CONFIG['whisper_cpp'].copy()
            else:
                for k, v in DEFAULT_CONFIG['whisper_cpp'].items():
                    if k not in cfg['whisper_cpp']:
                        cfg['whisper_cpp'][k] = v
            if 'active_integration' not in cfg:
                cfg['active_integration'] = 'whisper_cpp'
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[Config] Error saving config:", e)

def build_transcription_cmd(audio_file_path):
    cfg = load_config()
    integration = cfg.get('active_integration', 'whisper_cpp')
    
    if integration == 'whisper_cpp':
        w_cfg = cfg.get('whisper_cpp', {})
        bin_path = w_cfg.get('binary_path', '').strip() or os.path.join(HOME, '.local', 'bin', 'whisper-cli')
        model_path = w_cfg.get('model_path', '').strip() or os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en-q5_1.bin')
        raw_args = w_cfg.get('cli_args', '-nt -np -t 4').strip()
        extra_args = [a for a in raw_args.split() if a]
        
        return [bin_path, '-m', model_path, '-f', audio_file_path] + extra_args
    else:
        bin_path = os.path.join(HOME, '.local', 'bin', 'whisper-cli')
        model_path = os.path.join(HOME, 'development', 'whisper.cpp', 'models', 'ggml-base.en-q5_1.bin')
        return [bin_path, '-m', model_path, '-f', audio_file_path, '-nt', '-np', '-t', '4']

def get_history_hash(records):
    raw = json.dumps(records, sort_keys=True)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_history(records):
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[History] Error saving history:", e)

def add_transcription(text, duration_sec=0.0):
    if not text or not text.strip():
        return None
    records = load_history()
    entry = {
        'id': f"{int(time.time() * 1000)}",
        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'text': text.strip(),
        'duration': round(duration_sec, 1),
        'words': len(text.strip().split())
    }
    records.insert(0, entry)
    records = records[:500]
    save_history(records)
    return entry

def delete_transcription(entry_id):
    records = load_history()
    records = [r for r in records if str(r.get('id')) != str(entry_id)]
    save_history(records)

def clear_all_transcriptions():
    save_history([])

def render_cards_html(records, search_query=""):
    if search_query:
        q = search_query.lower()
        records = [r for r in records if q in r.get('text', '').lower()]

    if not records:
        if search_query:
            return '<div class="empty-state">No transcriptions matching your search.</div>'
        return '''
        <div class="empty-state">
            <div class="empty-icon">🎙️</div>
            <h3>No Transcriptions Yet</h3>
            <p>Use the floating button or hold <kbd>Right Ctrl</kbd> / press <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>R</kbd> to record audio.</p>
        </div>
        '''

    html_parts = []
    for r in records:
        rid = html.escape(str(r.get('id', '')))
        ts = html.escape(r.get('timestamp', ''))
        txt = html.escape(r.get('text', ''))
        raw_txt = r.get('text', '').replace('`', '\\`').replace('\\', '\\\\')
        words = r.get('words', len(txt.split()))
        dur = r.get('duration', 0.0)

        badge_dur = f'<span class="badge badge-dur">{dur}s</span>' if dur > 0 else ''
        
        card = f'''
        <div class="card" id="card-{rid}">
            <div class="card-header">
                <div class="meta">
                    <span class="timestamp">{ts}</span>
                    <span class="badge badge-words">{words} words</span>
                    {badge_dur}
                </div>
                <div class="actions">
                    <button class="btn btn-sm btn-copy" onclick="copyCardText(this, `{raw_txt}`)">
                        <span class="icon">📋</span> Copy
                    </button>
                    <button class="btn btn-sm btn-delete" 
                            hx-delete="/api/transcriptions/{rid}" 
                            hx-target="#card-{rid}" 
                            hx-swap="outerHTML">
                        <span class="icon">🗑️</span>
                    </button>
                </div>
            </div>
            <div class="card-body">
                <p class="transcript-text">{txt}</p>
            </div>
        </div>
        '''
        html_parts.append(card)

    return "\n".join(html_parts)

def render_history_view_html(records, search_query=""):
    toolbar = '''
    <div class="toolbar">
        <div class="search-box">
            <span class="search-icon">🔍</span>
            <input type="text" 
                   id="search-input" 
                   placeholder="Search transcriptions..." 
                   name="q"
                   hx-get="/api/transcriptions"
                   hx-trigger="keyup changed delay:250ms"
                   hx-target="#transcriptions-list">
        </div>
        <div class="stats">
            <span>Auto-updates via HTMX</span>
        </div>
    </div>
    <div id="transcriptions-list" 
         class="cards-list"
         hx-get="/api/transcriptions" 
         hx-trigger="load, every 3s" 
         hx-swap="innerHTML">
        ''' + render_cards_html(records, search_query) + '''
    </div>
    '''
    return toolbar

def render_integrations_html(cfg, success_msg="", error_msg=""):
    w_cfg = cfg.get('whisper_cpp', {})
    bin_path = html.escape(w_cfg.get('binary_path', ''))
    model_path = html.escape(w_cfg.get('model_path', ''))
    cli_args = html.escape(w_cfg.get('cli_args', '-nt -np -t 4'))
    start_cmd = html.escape(w_cfg.get('start_command', DEFAULT_CONFIG['whisper_cpp']['start_command']))
    
    msg_html = ""
    if success_msg:
        msg_html += f'''
        <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--accent-emerald); color: var(--accent-emerald); padding: 12px 16px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; margin-bottom: 20px;">
            ✓ {html.escape(success_msg)}
        </div>
        '''
    if error_msg:
        msg_html += f'''
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid var(--accent-red); color: var(--accent-red); padding: 12px 16px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; margin-bottom: 20px;">
            ⚠️ {html.escape(error_msg)}
        </div>
        '''

    is_running, pid = get_service_status()
    if is_running:
        status_color = "var(--accent-emerald)"
        status_text = f"Running (PID {pid})"
        service_btn = '''
        <button type="button" hx-post="/api/integrations/service/stop" hx-target="#main-content" hx-swap="innerHTML" class="btn" style="background: var(--accent-red); color: white; border: none; padding: 8px 16px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; cursor: pointer;">
            ⏹ Stop Service
        </button>
        '''
    else:
        status_color = "var(--text-muted)"
        status_text = "Stopped (Decoupled)"
        service_btn = '''
        <button type="button" hx-post="/api/integrations/service/start" hx-target="#main-content" hx-swap="innerHTML" class="btn" style="background: var(--accent-emerald); color: white; border: none; padding: 8px 16px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; cursor: pointer;">
            ▶ Start Service
        </button>
        '''

    return f'''
    <div class="integrations-container" style="max-width: 700px; margin: 0 auto; background: var(--bg-card); padding: 24px; border-radius: var(--radius-md); border: 1px solid var(--border);">
        <h2 style="font-size: 18px; margin-bottom: 8px; color: var(--text-primary);">Voice & Transcription Integrations</h2>
        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px;">
            Configure transcription engine paths, options, and service execution commands. Voice Orb can launch integrated services or run with externally hosted/decoupled backends.
        </p>

        {msg_html}

        <div style="background: var(--bg-surface); border: 1px solid var(--border); padding: 16px; border-radius: var(--radius-sm); margin-bottom: 20px;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <div style="font-size: 14px; font-weight: 600; color: var(--text-primary);">Integrated App Service Manager</div>
                    <div style="font-size: 12px; color: {status_color}; margin-top: 4px;">● Status: {status_text}</div>
                </div>
                <div>
                    {service_btn}
                </div>
            </div>
        </div>

        <form hx-post="/api/integrations" hx-target="#main-content" hx-swap="innerHTML">
            <div style="margin-bottom: 20px;">
                <label style="display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; color: var(--accent-cyan);">Active Integration Engine</label>
                <select name="active_integration" style="width: 100%; padding: 10px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm); font-size: 14px;">
                    <option value="whisper_cpp" selected>whisper.cpp (Local C++ Inference)</option>
                    <option value="custom_cli">Custom Command Template (Extensible)</option>
                </select>
            </div>

            <div style="border-top: 1px solid var(--border); padding-top: 18px; margin-top: 18px;">
                <h3 style="font-size: 15px; font-weight: 600; margin-bottom: 14px; color: var(--text-primary);">whisper.cpp Parameters</h3>
                
                <div style="margin-bottom: 16px;">
                    <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">Binary Executable Path (whisper-cli)</label>
                    <input type="text" name="binary_path" value="{bin_path}" placeholder="/path/to/whisper-cli" style="width: 100%; padding: 9px 12px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm); font-size: 13px; font-family: monospace;">
                    <span style="font-size: 11px; color: var(--text-muted); display: block; margin-top: 4px;">Location of compiled whisper-cli binary</span>
                </div>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">GGML Model File (.bin)</label>
                    <input type="text" name="model_path" value="{model_path}" placeholder="/path/to/ggml-base.en-q5_1.bin" style="width: 100%; padding: 9px 12px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm); font-size: 13px; font-family: monospace;">
                    <span style="font-size: 11px; color: var(--text-muted); display: block; margin-top: 4px;">Path to whisper.cpp model (base.en, small.en, etc.)</span>
                </div>

                <div style="margin-bottom: 16px;">
                    <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--text-secondary);">CLI Flags & Arguments</label>
                    <input type="text" name="cli_args" value="{cli_args}" placeholder="-nt -np -t 4" style="width: 100%; padding: 9px 12px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm); font-size: 13px; font-family: monospace;">
                    <span style="font-size: 11px; color: var(--text-muted); display: block; margin-top: 4px;">Additional arguments (e.g. -nt for no timestamps, -np for no print, -t for CPU threads)</span>
                </div>

                <div style="margin-bottom: 22px;">
                    <label style="display: block; font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--accent-cyan);">Service Start Command (Decoupled Execution)</label>
                    <input type="text" name="start_command" value="{start_cmd}" placeholder="/path/to/whisper-server -m /path/to/model.bin --port 8080" style="width: 100%; padding: 9px 12px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm); font-size: 13px; font-family: monospace;">
                    <span style="font-size: 11px; color: var(--text-muted); display: block; margin-top: 4px;">Command executed when clicking 'Start Service' above. Allows running whisper-server / background daemon directly from Voice Orb.</span>
                </div>
            </div>

            <button type="submit" class="btn" style="background: var(--accent-blue); color: white; border: none; padding: 11px 20px; font-weight: 600; width: 100%; cursor: pointer; border-radius: var(--radius-sm); font-size: 14px;">
                💾 Save Integration Settings
            </button>
        </form>
    </div>
    '''

INDEX_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Orb — Dashboard & Integrations</title>
    <script src="/static/htmx.min.js" onerror="this.onerror=null;this.src='https://unpkg.com/htmx.org@2.0.4'"></script>
    <style>
        :root {
            --bg-base: #090d16;
            --bg-surface: #111827;
            --bg-card: #1a2234;
            --bg-card-hover: #222c42;
            --border: #28354d;
            --border-light: #374765;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-cyan: #38bdf8;
            --accent-blue: #3b82f6;
            --accent-emerald: #10b981;
            --accent-red: #ef4444;
            --radius-md: 10px;
            --radius-sm: 6px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-base);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            line-height: 1.5;
        }

        header {
            background-color: var(--bg-surface);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 50;
            padding: 14px 24px;
            backdrop-filter: blur(8px);
        }

        .header-container {
            max-width: 900px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-icon {
            width: 34px;
            height: 34px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-cyan));
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.35);
        }

        .brand h1 {
            font-size: 18px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: -0.02em;
        }

        .nav-tabs {
            display: flex;
            gap: 8px;
            background: var(--bg-base);
            padding: 4px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
        }

        .nav-tab {
            padding: 6px 14px;
            font-size: 13px;
            font-weight: 600;
            color: var(--text-secondary);
            border: none;
            background: transparent;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
        }

        .nav-tab.active, .nav-tab:hover {
            background: var(--bg-card);
            color: var(--text-primary);
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 3px 8px;
            border-radius: 20px;
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-emerald);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background-color: var(--accent-emerald);
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.85); }
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 7px 14px;
            border-radius: var(--radius-sm);
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            border: 1px solid transparent;
        }

        .btn-record {
            background: rgba(59, 130, 246, 0.15);
            color: var(--accent-cyan);
            border-color: rgba(56, 189, 248, 0.3);
        }

        .btn-record:hover {
            background: rgba(59, 130, 246, 0.25);
            border-color: var(--accent-cyan);
        }

        .btn-danger {
            background: rgba(239, 68, 68, 0.12);
            color: var(--accent-red);
            border-color: rgba(239, 68, 68, 0.3);
        }

        .btn-danger:hover {
            background: rgba(239, 68, 68, 0.22);
            border-color: var(--accent-red);
        }

        .btn-sm {
            padding: 4px 10px;
            font-size: 12px;
        }

        .btn-copy {
            background: var(--bg-surface);
            color: var(--text-secondary);
            border-color: var(--border);
        }

        .btn-copy:hover {
            background: var(--bg-card-hover);
            color: var(--text-primary);
        }

        .btn-delete {
            background: transparent;
            color: var(--text-muted);
            border-color: transparent;
        }

        .btn-delete:hover {
            color: var(--accent-red);
            background: rgba(239, 68, 68, 0.1);
        }

        main {
            max-width: 900px;
            margin: 24px auto;
            padding: 0 24px;
            flex: 1;
            width: 100%;
        }

        .toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 20px;
        }

        .search-box {
            position: relative;
            flex: 1;
            max-width: 400px;
        }

        .search-icon {
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 14px;
        }

        .search-box input {
            width: 100%;
            padding: 9px 12px 9px 36px;
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
            transition: border-color 0.15s ease;
        }

        .search-box input:focus {
            border-color: var(--accent-blue);
        }

        .stats {
            font-size: 12px;
            color: var(--text-muted);
        }

        .cards-list {
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 16px;
            transition: transform 0.15s ease, border-color 0.15s ease;
        }

        .card:hover {
            border-color: var(--border-light);
        }

        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 10px;
        }

        .meta {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .timestamp {
            font-size: 12px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .badge {
            font-size: 11px;
            padding: 2px 7px;
            border-radius: 12px;
            font-weight: 600;
        }

        .badge-words {
            background: rgba(56, 189, 248, 0.12);
            color: var(--accent-cyan);
            border: 1px solid rgba(56, 189, 248, 0.25);
        }

        .badge-dur {
            background: rgba(16, 185, 129, 0.12);
            color: var(--accent-emerald);
            border: 1px solid rgba(16, 185, 129, 0.25);
        }

        .actions {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .transcript-text {
            font-size: 14.5px;
            color: var(--text-primary);
            white-space: pre-wrap;
            word-break: break-word;
        }

        .empty-state {
            text-align: center;
            padding: 48px 24px;
            background: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: var(--radius-md);
            color: var(--text-secondary);
        }

        .empty-icon {
            font-size: 36px;
            margin-bottom: 12px;
        }

        .empty-state h3 {
            font-size: 16px;
            color: var(--text-primary);
            margin-bottom: 6px;
        }

        .empty-state p {
            font-size: 13px;
        }

        kbd {
            background: var(--bg-surface);
            border: 1px solid var(--border-light);
            border-radius: 4px;
            padding: 2px 5px;
            font-size: 11px;
            font-family: inherit;
            color: var(--accent-cyan);
        }

        footer {
            text-align: center;
            padding: 20px;
            font-size: 12px;
            color: var(--text-muted);
            border-top: 1px solid var(--border);
        }
    </style>
</head>
<body>
    <header>
        <div class="header-container">
            <div class="brand">
                <div class="brand-icon">🎙️</div>
                <div>
                    <h1>Voice Orb</h1>
                </div>
                <div class="status-pill">
                    <span class="status-dot"></span>
                    <span>Live</span>
                </div>
            </div>

            <nav class="nav-tabs">
                <button class="nav-tab active" id="tab-history" hx-get="/api/view/history" hx-target="#main-content" onclick="setActiveTab(this)">History</button>
                <button class="nav-tab" id="tab-integrations" hx-get="/api/view/integrations" hx-target="#main-content" onclick="setActiveTab(this)">Integrations</button>
            </nav>

            <div class="header-actions" style="display: flex; align-items: center; gap: 8px;">
                <div id="header-service-btn" hx-get="/api/service/button" hx-trigger="load, every 3s" hx-swap="outerHTML">
                    <button class="btn btn-sm" style="background: rgba(16, 185, 129, 0.2); color: var(--accent-emerald); border: 1px solid rgba(16, 185, 129, 0.4); font-size: 12px;">
                        ▶ Start Service
                    </button>
                </div>
                <button class="btn btn-record" hx-post="/api/toggle" hx-swap="none">
                    <span>●</span> Toggle Record
                </button>
                <button class="btn btn-danger btn-sm" 
                        hx-post="/api/clear" 
                        hx-target="#main-content" 
                        hx-confirm="Are you sure you want to clear all transcriptions?">
                    Clear All
                </button>
            </div>
        </div>
    </header>

    <main id="main-content">
        <div class="toolbar">
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" 
                       id="search-input" 
                       placeholder="Search transcriptions..." 
                       name="q"
                       hx-get="/api/transcriptions"
                       hx-trigger="keyup changed delay:250ms"
                       hx-target="#transcriptions-list">
            </div>
            <div class="stats">
                <span>Auto-updates via HTMX</span>
            </div>
        </div>

        <div id="transcriptions-list" 
             class="cards-list"
             hx-get="/api/transcriptions" 
             hx-trigger="load, every 3s" 
             hx-swap="innerHTML">
            <div class="empty-state">Loading transcriptions...</div>
        </div>
    </main>

    <footer>
        Voice Orb &bull; Dynamic Local AI Voice Frontend &bull; Lightweight Native GTK3 + HTMX
    </footer>

    <script>
        function copyCardText(btn, text) {
            navigator.clipboard.writeText(text).then(() => {
                const orig = btn.innerHTML;
                btn.innerHTML = '<span class="icon">✓</span> Copied!';
                btn.style.color = '#10b981';
                setTimeout(() => {
                    btn.innerHTML = orig;
                    btn.style.color = '';
                }, 1500);
            });
        }

        function setActiveTab(clickedBtn) {
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            clickedBtn.classList.add('active');
        }
    </script>
</body>
</html>
'''

class RecorderHTTPRequestHandler(BaseHTTPRequestHandler):
    app_toggle_callback = None

    def log_message(self, format, *args):
        pass

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, hx-request, hx-target, hx-current-url')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == '/api/service/button':
            is_running, pid = get_service_status()
            if is_running:
                html_btn = f'''
                <div id="header-service-btn" style="display: inline-block;">
                    <button class="btn btn-sm" style="background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.4); font-size: 12px; cursor: pointer;" hx-post="/api/integrations/service/stop" hx-target="#header-service-btn" hx-swap="outerHTML">
                        ⏹ Stop Service (PID {pid})
                    </button>
                </div>
                '''
            else:
                html_btn = '''
                <div id="header-service-btn" style="display: inline-block;">
                    <button class="btn btn-sm" style="background: rgba(16, 185, 129, 0.2); color: var(--accent-emerald); border: 1px solid rgba(16, 185, 129, 0.4); font-size: 12px; cursor: pointer;" hx-post="/api/integrations/service/start" hx-target="#header-service-btn" hx-swap="outerHTML">
                        ▶ Start Service
                    </button>
                </div>
                '''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_btn.encode('utf-8'))
            return

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode('utf-8'))
            return

        if path == '/static/htmx.min.js':
            htmx_path = os.path.join(STATIC_DIR, 'htmx.min.js')
            if os.path.exists(htmx_path):
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                with open(htmx_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        if path == '/api/transcriptions':
            records = load_history()
            current_hash = get_history_hash(records)
            search_query = query.get('q', [''])[0]

            if not search_query:
                client_etag = self.headers.get('If-None-Match', '')
                if client_etag == current_hash:
                    self.send_response(304)
                    self.send_cors_headers()
                    self.end_headers()
                    return

            cards_html = render_cards_html(records, search_query=search_query)

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('ETag', current_hash)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(cards_html.encode('utf-8'))
            return

        if path == '/api/view/history':
            records = load_history()
            html_out = render_history_view_html(records)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        if path == '/api/view/integrations':
            cfg = load_config()
            html_out = render_integrations_html(cfg)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        if path == '/api/transcriptions/json':
            records = load_history()
            data = json.dumps(records, ensure_ascii=False)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data.encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/toggle':
            if RecorderHTTPRequestHandler.app_toggle_callback:
                RecorderHTTPRequestHandler.app_toggle_callback()
            self.send_response(200)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"OK")
            return

        if path == '/api/clear':
            clear_all_transcriptions()
            records = load_history()
            html_out = render_history_view_html(records)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        if path == '/api/integrations/service/start':
            cfg = load_config()
            w_cfg = cfg.get('whisper_cpp', {})
            start_cmd = w_cfg.get('start_command', DEFAULT_CONFIG['whisper_cpp']['start_command'])
            ok, msg = start_integrated_service(start_cmd)
            if ok:
                html_out = render_integrations_html(cfg, success_msg=msg)
            else:
                html_out = render_integrations_html(cfg, error_msg=msg)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        if path == '/api/integrations/service/stop':
            cfg = load_config()
            ok, msg = stop_integrated_service()
            if ok:
                html_out = render_integrations_html(cfg, success_msg=msg)
            else:
                html_out = render_integrations_html(cfg, error_msg=msg)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        if path == '/api/integrations':
            content_length = int(self.headers.get('Content-Length', 0))
            body_data = self.rfile.read(content_length).decode('utf-8')
            params = urllib.parse.parse_qs(body_data)

            active_integration = params.get('active_integration', ['whisper_cpp'])[0]
            binary_path = params.get('binary_path', [''])[0].strip()
            model_path = params.get('model_path', [''])[0].strip()
            cli_args = params.get('cli_args', ['-nt -np -t 4'])[0].strip()
            start_command = params.get('start_command', [''])[0].strip()

            cfg = load_config()
            cfg['active_integration'] = active_integration
            cfg['whisper_cpp'] = {
                'binary_path': binary_path,
                'model_path': model_path,
                'cli_args': cli_args,
                'start_command': start_command
            }
            save_config(cfg)

            html_out = render_integrations_html(cfg, success_msg="Integration settings saved successfully!")
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(html_out.encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith('/api/transcriptions/'):
            entry_id = path.replace('/api/transcriptions/', '').strip()
            delete_transcription(entry_id)
            self.send_response(200)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"")
            return

        self.send_response(404)
        self.end_headers()


class EmbeddedWebServer:
    def __init__(self, host="127.0.0.1", port=8088, toggle_callback=None):
        self.host = host
        self.port = port
        RecorderHTTPRequestHandler.app_toggle_callback = toggle_callback
        self.server = None
        self.thread = None

    def start(self):
        for p in range(self.port, self.port + 10):
            try:
                self.server = ThreadingHTTPServer((self.host, p), RecorderHTTPRequestHandler)
                self.port = p
                break
            except OSError:
                continue

        if not self.server:
            print(f"[Web Server] Could not bind to port {self.port}", file=sys.stderr)
            return

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[Web Server] Dashboard running at http://{self.host}:{self.port}/")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            print("[Web Server] Dashboard stopped.")
