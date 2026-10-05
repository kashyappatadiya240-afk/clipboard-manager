/* extension.js - Klipora Native GNOME Shell Picker Overlay */

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import Clutter from 'gi://Clutter';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

const BACKEND_PICKER_IFACE_XML = `
<node>
  <interface name="com.kashyap.Klipora.Picker">
    <method name="GetHistory">
      <arg type="s" name="query" direction="in"/>
      <arg type="u" name="limit" direction="in"/>
      <arg type="a(ss)" name="items" direction="out"/>
    </method>
    <method name="CopyItem">
      <arg type="s" name="item_id" direction="in"/>
      <arg type="b" name="success" direction="out"/>
    </method>
  </interface>
</node>
`;

const SHELL_PICKER_DBUS_XML = `
<node>
  <interface name="com.kashyap.Klipora.Shell">
    <method name="Toggle"/>
    <method name="Show"/>
    <method name="Hide"/>
    <method name="IsVisible">
      <arg type="b" name="visible" direction="out"/>
    </method>
    <method name="GetStackingOrder">
      <arg type="i" name="window_group_index" direction="out"/>
      <arg type="i" name="top_window_group_index" direction="out"/>
      <arg type="i" name="picker_container_index" direction="out"/>
    </method>
  </interface>
</node>
`;

const PickerProxyWrapper = Gio.DBusProxy.makeProxyWrapper(BACKEND_PICKER_IFACE_XML);

export default class KliporaExtension extends Extension {
    enable() {
        console.log('[Klipora] Enabling GNOME Shell extension...');
        this._settings = this.getSettings();
        this._proxy = null;
        this._dbusImpl = null;
        this._initDBus();

        // Build UI container
        this._createUI();

        // Export Shell D-Bus interface for IPC and automated verification
        try {
            this._dbusImpl = Gio.DBusExportedObject.wrapJSObject(SHELL_PICKER_DBUS_XML, this);
            this._dbusImpl.export(Gio.DBus.session, '/com/kashyap/Klipora/Shell');
        } catch (e) {
            console.error('[Klipora] Failed to export Shell D-Bus interface:', e);
        }

        // Register Super+V global keybinding
        Main.wm.addKeybinding(
            'toggle-clipboard-picker',
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW | Shell.ActionMode.POPUP,
            () => this.toggle()
        );

        console.log('[Klipora] GNOME Shell extension enabled successfully.');
    }

    _initDBus() {
        try {
            this._proxy = new PickerProxyWrapper(
                Gio.DBus.session,
                'com.kashyap.Klipora.Picker',
                '/com/kashyap/Klipora'
            );
        } catch (e) {
            console.error('[Klipora] Failed to create D-Bus proxy:', e);
        }
    }

    _createUI() {
        this._container = new St.BoxLayout({
            name: 'klipora-container',
            style_class: 'clipboard-picker-container',
            vertical: true,
            reactive: true,
            track_hover: true,
            visible: false,
        });

        // Search entry
        this._searchEntry = new St.Entry({
            name: 'clipboardSearchEntry',
            style_class: 'clipboard-search-entry',
            hint_text: 'Search clipboard...',
            can_focus: true,
        });

        this._searchEntry.clutter_text.connect('text-changed', () => {
            this._loadHistory(this._searchEntry.get_text());
        });

        // Key handler for Escape key on search entry
        this._searchEntry.clutter_text.connect('key-press-event', (actor, event) => {
            const symbol = event.get_key_symbol();
            if (symbol === Clutter.KEY_Escape) {
                this.hide();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        this._container.add_child(this._searchEntry);

        // Scroll view for history items
        this._scrollView = new St.ScrollView({
            style_class: 'clipboard-scroll-view',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
        });

        this._itemList = new St.BoxLayout({
            vertical: true,
            style_class: 'clipboard-item-list',
        });
        this._scrollView.add_child(this._itemList);
        this._container.add_child(this._scrollView);

        // Key handler on container for Escape key
        this._container.connect('key-press-event', (actor, event) => {
            const symbol = event.get_key_symbol();
            if (symbol === Clutter.KEY_Escape) {
                this.hide();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        // Add to top chrome layer so it remains visually above normal application windows
        Main.layoutManager.addTopChrome(this._container, {
            affectsStruts: false,
            trackFullscreen: true,
        });
    }

    _updatePosition() {
        const monitor = Main.layoutManager.primaryMonitor || {x: 0, y: 0, width: 1280, height: 800};
        const width = 460;
        const height = 400;
        this._container.set_size(width, height);
        const posX = Math.round(monitor.x + (monitor.width - width) / 2);
        const posY = Math.round(monitor.y + (monitor.height - height) / 2);
        this._container.set_position(posX, posY);
    }

    // D-Bus and Keybinding entry point
    Toggle() {
        this.toggle();
    }

    Show() {
        this.show();
    }

    Hide() {
        this.hide();
    }

    IsVisible() {
        return this._container ? this._container.visible : false;
    }

    GetStackingOrder() {
        if (!this._container) return [-1, -1, -1];
        const children = Main.layoutManager.uiGroup.get_children();
        const wgIdx = children.indexOf(global.window_group);
        const topWgIdx = children.indexOf(global.top_window_group);
        const cIdx = children.indexOf(this._container);
        return [wgIdx, topWgIdx, cIdx];
    }

    toggle() {
        if (this._container && this._container.visible) {
            this.hide();
        } else {
            this.show();
        }
    }

    show() {
        if (!this._container) return;
        this._updatePosition();
        this._container.show();
        this._searchEntry.set_text('');
        this._loadHistory('');
        this._searchEntry.clutter_text.grab_key_focus();

        const children = Main.layoutManager.uiGroup.get_children();
        const windowGroupIdx = children.indexOf(global.window_group);
        const topWindowGroupIdx = children.indexOf(global.top_window_group);
        const containerIdx = children.indexOf(this._container);
        console.log(`[Klipora Stacking] global.window_group index: ${windowGroupIdx}, global.top_window_group index: ${topWindowGroupIdx}, picker container index: ${containerIdx}`);
    }

    hide() {
        if (this._container) {
            this._container.hide();
        }
    }

    _loadHistory(query) {
        if (!this._proxy) {
            this._initDBus();
        }

        if (!this._proxy) {
            this._renderItems([]);
            return;
        }

        this._proxy.GetHistoryRemote(query || '', 20, (items, error) => {
            if (error) {
                console.error('[Klipora] GetHistory error:', error);
                this._renderItems([]);
                return;
            }
            this._renderItems(items || []);
        });
    }

    _renderItems(items) {
        this._itemList.destroy_all_children();

        if (items.length === 0) {
            const emptyLabel = new St.Label({
                text: 'No clipboard history matching query',
                style_class: 'clipboard-empty-label',
            });
            this._itemList.add_child(emptyLabel);
            return;
        }

        for (const [id, text] of items) {
            const cleanText = text.replace(/[\r\n\t]+/g, ' ').trim();
            const displayText = cleanText.length > 70 ? cleanText.substring(0, 67) + '...' : cleanText;

            const btn = new St.Button({
                style_class: 'clipboard-item-button',
                reactive: true,
                can_focus: true,
                x_align: Clutter.ActorAlign.FILL,
            });

            const label = new St.Label({
                text: displayText,
                style_class: 'clipboard-item-label',
            });
            btn.set_child(label);

            btn.connect('clicked', () => {
                this._copyItem(id, label, displayText);
            });

            this._itemList.add_child(btn);
        }
    }

    _copyItem(id, labelWidget, originalText) {
        if (!this._proxy) return;

        this._proxy.CopyItemRemote(id, (success, error) => {
            if (error) {
                console.error('[Klipora] CopyItem error:', error);
                return;
            }
            if (success) {
                labelWidget.set_text('✓ Copied to clipboard!');
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 800, () => {
                    labelWidget.set_text(originalText);
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
    }

    disable() {
        console.log('[Klipora] Disabling GNOME Shell extension...');
        Main.wm.removeKeybinding('toggle-clipboard-picker');

        if (this._dbusImpl) {
            try {
                this._dbusImpl.unexport();
            } catch (e) {
                // Ignore
            }
            this._dbusImpl = null;
        }

        if (this._container) {
            Main.layoutManager.removeChrome(this._container);
            this._container.destroy();
            this._container = null;
        }

        this._proxy = null;
        this._settings = null;
        console.log('[Klipora] GNOME Shell extension disabled.');
    }
}
