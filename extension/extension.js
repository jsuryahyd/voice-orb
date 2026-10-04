import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import St from 'gi://St';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

export default class VoiceOrbExtension extends Extension {
    enable() {
        console.log('[Voice-Orb-Extension] Enabling Voice Orb GNOME Shell extension...');
        this._indicator = null;
        this._timerId = 0;

        // 1. Create System Tray Top Bar Panel Indicator
        this._createPanelIndicator();

        // 2. Start Taskbar Hiding & Always-On-Top Enforcer Loop for Voice Orb Windows
        this._startWindowRulesLoop();
    }

    disable() {
        console.log('[Voice-Orb-Extension] Disabling Voice Orb extension...');

        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }

        if (this._timerId > 0) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
    }

    _createPanelIndicator() {
        try {
            this._indicator = new PanelMenu.Button(0.0, 'Voice-Orb', false);
            const icon = new St.Icon({
                icon_name: 'audio-input-microphone-symbolic',
                style_class: 'system-status-icon',
            });
            this._indicator.add_child(icon);

            this._indicator.connect('button-press-event', () => {
                console.log('[Voice-Orb-Extension] System tray indicator clicked, opening web dashboard...');
                try {
                    Gio.AppInfo.launch_default_for_uri('http://127.0.0.1:8088/', null);
                } catch (e) {
                    console.error('[Voice-Orb-Extension] Launch error:', e);
                }
            });

            Main.panel.addToStatusArea('voice-orb-indicator', this._indicator);
            console.log('[Voice-Orb-Extension] System tray panel indicator added to GNOME top bar!');
        } catch (e) {
            console.error(`[Voice-Orb-Extension] Error creating panel indicator: ${e}`);
        }
    }

    _startWindowRulesLoop() {
        this._timerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
            this._applyWindowRules();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _applyWindowRules() {
        try {
            const actors = global.get_window_actors();
            for (const actor of actors) {
                const win = actor.meta_window;
                if (!win) continue;
                const wmClass = (win.get_wm_class() || '').toLowerCase();
                const title = (win.get_title() || '').toLowerCase();
                if (wmClass.includes('voice-orb') || title.includes('voice-orb') || wmClass.includes('floating-recorder')) {
                    win.skip_taskbar = true;
                    win.make_above();
                }
            }
        } catch (e) {
            // Ignore temporary window lookup errors
        }
    }
}
