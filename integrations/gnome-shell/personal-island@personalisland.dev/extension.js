import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

const APP = 'dev.personalisland.Island';
const HOST = 'dev.personalisland.Shell';
const PATH = '/dev/personalisland/Island';
const DESKTOP_FILE = 'dev.personalisland.desktop.desktop';
const SLOT_WIDTH = 176;

export default class PersonalIsland extends Extension {
    enable() {
        this._cancel = new Gio.Cancellable();
        this._selection = global.display.get_selection();
        this._selectionId = this._selection.connect('owner-changed',
            (_selection, type, owner) => this._clipboardChanged(type, owner));
        this._date = Main.panel.statusArea.dateMenu;
        this._restoreDate = this._date.visible;
        this._slot = new PanelMenu.Button(0.5, 'Personal Island', true);
        this._slot.add_style_class_name('personal-island-slot');
        this._face = new St.Button({
            accessible_name: 'Раскрыть или свернуть Personal Island',
            style_class: 'personal-island-face',
            can_focus: true,
            reactive: true,
            track_hover: true,
            clip_to_allocation: true,
            width: SLOT_WIDTH,
        });
        this._viewport = new Clutter.Actor({
            layout_manager: new Clutter.FixedLayout(),
            clip_to_allocation: true,
            width: SLOT_WIDTH,
            height: 1,
        });
        this._clone = new Clutter.Clone();
        this._viewport.add_child(this._clone);
        this._highlight = new St.Widget({style_class: 'personal-island-highlight', reactive: false});
        this._viewport.add_child(this._highlight);
        this._face.child = this._viewport;
        this._face.connect('clicked', () => {
            this._call('Toggle').catch(error => this._report(error));
        });
        this._slot.add_child(this._face);
        const position = Main.panel._centerBox.get_children().indexOf(this._date.container);
        Main.panel.addToStatusArea(this.uuid, this._slot, Math.max(0, position), 'center');
        this._slot.hide();
        this._face.connect('notify::allocation', () => this._queueLayout());
        Main.layoutManager.connectObject('monitors-changed', () => this._queueLayout(), this);
        global.display.connectObject('window-created', () => this._queueLayout(),
            'notify::focus-window', () => this._rememberFocus(), this);
        global.window_manager.connectObject('map', () => this._queueLayout(), this);

        this._host = Gio.bus_own_name_on_connection(Gio.DBus.session, HOST,
            Gio.BusNameOwnerFlags.NONE,
            () => {
                this._watch = Gio.bus_watch_name_on_connection(Gio.DBus.session, APP,
                    Gio.BusNameWatcherFlags.NONE,
                    (_connection, _name, owner) => this._connected(owner),
                    () => this._disconnected());
            }, null);
    }

    disable() {
        this._selection.disconnect(this._selectionId);
        this._selection = null;
        if (this._watch)
            Gio.bus_unwatch_name(this._watch);
        this._watch = 0;
        if (this._host)
            Gio.bus_unown_name(this._host);
        this._host = 0;
        this._cancel.cancel();
        this._cancel = null;
        this._disconnected();
        if (this._layout)
            global.compositor.get_laters().remove(this._layout);
        this._layout = 0;
        global.display.disconnectObject(this);
        global.window_manager.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);
        this._slot.destroy();
        this._slot = this._date = this._clone = this._face = this._viewport = this._highlight = null;
        this._launchTried = false;
    }

    async _connected(owner) {
        this._owner = owner;
        this._launchTried = true;
        try {
            const result = await this._dbus('org.freedesktop.DBus', '/org/freedesktop/DBus',
                'org.freedesktop.DBus', 'GetConnectionUnixProcessID', new GLib.Variant('(s)', [owner]));
            if (this._owner !== owner)
                return;
            [this._pid] = result.deepUnpack();
            this._queueLayout();
            void this._call('WatchClipboard').catch(error => this._report(error));
            await this._setHeight();
        } catch (error) {
            this._report(error);
        }
    }

    _disconnected() {
        this._clipRead?.cancel();
        this._clipRead = null;
        this._owner = this._pid = null;
        this._height = 0;
        this._detach();
        if (this._cancel && !this._launchTried) {
            // The portable AppImage registers the same desktop entry as the package.
            this._launchTried = true;
            try {
                GioUnix.DesktopAppInfo.new(DESKTOP_FILE)?.launch([], global.create_app_launch_context(0, -1));
            } catch (error) {
                this._report(error);
            }
        }
    }

    async _clipboardChanged(type, owner) {
        if (type !== Meta.SelectionType.SELECTION_CLIPBOARD)
            return;
        this._clipRead?.cancel();
        this._clipRead = null;
        if (!owner || !this._owner)
            return;

        const cancel = this._clipRead = new Gio.Cancellable();
        try {
            const [enabled, epoch] = (await this._call('ClipboardEpoch')).deepUnpack();
            if (!enabled || cancel.is_cancelled())
                return;
            const types = this._selection.get_mimetypes(type) ?? [];
            if (types.includes('x-kde-passwordManagerHint'))
                return;
            const mime = ['x-special/gnome-copied-files', 'text/uri-list', 'image/png',
                'text/plain;charset=utf-8', 'UTF8_STRING', 'text/plain'].find(type => types.includes(type));
            if (!mime)
                return;

            const limit = mime === 'image/png' ? 8 * 1024 * 1024 : 256 * 1024;
            const output = Gio.MemoryOutputStream.new_resizable();
            const data = await new Promise((resolve, reject) => {
                this._selection.transfer_async(type, mime, limit + 1, output, cancel, (selection, result) => {
                    try {
                        selection.transfer_finish(result);
                        output.close(null);
                        resolve(output.steal_as_bytes());
                    } catch (error) {
                        reject(error);
                    }
                });
            });
            if (!cancel.is_cancelled() && data.get_size() > 0 && data.get_size() <= limit)
                await this._call('CaptureClipboard', new GLib.Variant('(usay)', [epoch, mime, data.get_data()]));
        } catch (error) {
            if (!cancel.is_cancelled())
                this._report(error);
        } finally {
            if (this._clipRead === cancel)
                this._clipRead = null;
        }
    }

    _rememberFocus() {
        const focused = global.display.focus_window;
        if (focused && focused !== this._window)
            this._previousFocus = focused;
    }

    _attach(actor) {
        const window = actor.get_meta_window();
        this._actor = actor;
        this._window = window;
        this._rememberFocus();
        this._wasSticky = window.is_on_all_workspaces();
        if (!this._wasSticky)
            window.stick();
        this._clone.set_source(actor);
        this._date.hide();
        this._slot.show();
        window.connectObject('size-changed', () => this._queueLayout(),
            'position-changed', () => this._queueLayout(),
            'unmanaged', () => {
                this._detach(false);
            }, this);
    }

    _detach(restore = true) {
        if (this._window) {
            this._window.disconnectObject(this);
            if (restore) {
                this._actor.remove_clip();
                if (!this._wasSticky)
                    this._window.unstick();
            }
        }
        this._actor = this._window = this._previousFocus = null;
        this._expanded = false;
        this._clone.set_source(null);
        this._slot.hide();
        if (this._restoreDate)
            this._date.show();
    }

    _queueLayout() {
        if (this._layout || !this._cancel)
            return;
        this._layout = global.compositor.get_laters().add(Meta.LaterType.BEFORE_REDRAW, () => {
            this._layout = 0;
            this._layoutSurface();
            return GLib.SOURCE_REMOVE;
        });
    }

    async _setHeight() {
        const height = Math.round(Main.panel.get_allocation_box().get_height());
        if (height <= 0 || height === this._height || !this._owner)
            return;
        this._height = height;
        this._viewport.set_height(height);
        this._highlight.set_size(SLOT_WIDTH, height);
        try {
            await this._call('Attach', new GLib.Variant('(u)', [height]));
        } catch (error) {
            this._height = 0;
            this._report(error);
        }
    }

    _layoutSurface() {
        if (!this._actor && this._pid) {
            const actor = global.get_window_actors().find(actor => {
                const window = actor.get_meta_window();
                return window?.mapped && window.get_pid() === this._pid &&
                    window.get_title() === 'Personal Island';
            });
            if (actor)
                this._attach(actor);
        }
        if (!this._actor || this._face.width <= 0 || this._face.height <= 0)
            return;

        const [slotX, slotY] = this._face.get_transformed_position();
        void this._setHeight();
        const frame = this._window.get_frame_rect();
        const buffer = this._window.get_buffer_rect();
        const center = slotX + this._face.width / 2;
        const x = Math.round(center - frame.width / 2);
        const y = Math.round(slotY);
        const expanded = frame.width > 500;
        this._clone.set_size(buffer.width, buffer.height);
        this._clone.set_position((this._face.width - buffer.width) / 2, 0);
        if (expanded) {
            this._actor.remove_clip();
        } else {
            this._actor.set_clip(0, 0, buffer.width, this._height);
            if (this._expanded && this._window.has_focus() && this._previousFocus?.get_compositor_private())
                this._previousFocus.activate(global.get_current_time());
        }
        this._expanded = expanded;
        if (frame.x !== x || frame.y !== y)
            this._window.move_frame(true, x, y);
    }

    _call(method, parameters = null) {
        return this._dbus(this._owner || APP, PATH, APP, method, parameters);
    }

    _dbus(destination, path, iface, method, parameters) {
        const cancel = this._cancel;
        return new Promise((resolve, reject) => {
            Gio.DBus.session.call(destination, path, iface, method, parameters, null,
                Gio.DBusCallFlags.NO_AUTO_START, 3000, cancel, (connection, result) => {
                    try {
                        resolve(connection.call_finish(result));
                    } catch (error) {
                        reject(error);
                    }
                });
        });
    }

    _report(error) {
        if (this._cancel)
            console.warn(`Personal Island: ${error.message}`);
    }
}
