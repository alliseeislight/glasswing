"""Sidebar: places, bookmarks, devices, trash, connect to server."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from . import dialogs, dnd, prefs as prefs_mod, trash, ui, util

BOOKMARK_MIME = "application/x-glass-bookmark"


class SidebarRow(Gtk.Button):
    def __init__(self, icon_name, text, window=None, path=None, css=None):
        super().__init__()
        self.window = window
        self.path = path
        self.add_css_class("side-row")
        if css:
            self.add_css_class(css)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.icon = ui.image_icon(icon_name, 16)
        box.append(self.icon)
        self.label = ui.label(text, "side-label", ellipsize=2)
        self.label.set_hexpand(True)
        box.append(self.label)
        self.badge = ui.label("", "side-badge", xalign=0.5)
        self.badge.set_visible(False)
        box.append(self.badge)
        self.set_child(box)
        self.set_tooltip_text(text)
        if path is not None:
            self.connect("clicked", lambda *_: window.navigate(path))

    def set_badge(self, text):
        self.badge.set_text(text or "")
        self.badge.set_visible(bool(text))

    def set_on(self, on: bool):
        if on:
            self.add_css_class("side-on")
        else:
            self.remove_css_class("side-on")


class Section(Gtk.Box):
    def __init__(self, title, key, prefs, start_open=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.key = key
        self.prefs = prefs
        self.head = Gtk.Button()
        self.head.add_css_class("side-head")
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.arrow = ui.image_icon("pan-down-symbolic", 12)
        hb.append(self.arrow)
        hb.append(ui.label(title.upper(), "side-head-label"))
        self.head.set_child(hb)
        self.append(self.head)
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_transition_duration(140)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.revealer.set_child(self.rows)
        self.append(self.revealer)
        open_state = prefs.get("sidebar_open", {}).get(key, start_open)
        self.set_open(open_state)
        self.head.connect("clicked", lambda *_: self.set_open(not self.revealer.get_reveal_child()))

    def set_open(self, open_: bool):
        self.revealer.set_reveal_child(bool(open_))
        self.arrow.set_from_icon_name("pan-down-symbolic" if open_ else "pan-end-symbolic")
        states = dict(self.prefs.get("sidebar_open", {}))
        states[self.key] = bool(open_)
        self.prefs.data["sidebar_open"] = states
        self.prefs.save()

    def clear(self):
        child = self.rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.rows.remove(child)
            child = nxt


class Sidebar(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window = window
        self.prefs = window.prefs
        self.add_css_class("sidebar")
        self.set_size_request(212, -1)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)
        self.append(self.scroller)
        self.inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.inner.set_margin_top(4)
        self.inner.set_margin_bottom(8)
        self.scroller.set_child(self.inner)

        self.places = Section("Places", "places", self.prefs, True)
        self.bookmarks = Section("Bookmarks", "bookmarks", self.prefs, True)
        self.devices = Section("Devices", "devices", self.prefs, True)
        self.inner.append(self.places)
        self.inner.append(self.bookmarks)
        self.inner.append(self.devices)

        self.device_rows = []
        self.bookmark_rows = {}
        self.place_rows = {}
        self.trash_row = None
        self._build_places()
        self._build_devices()
        self._refresh_bookmarks()

        monitor = Gio.VolumeMonitor.get()
        if monitor:
            monitor.connect("mount-added", lambda *_: self._build_devices())
            monitor.connect("mount-removed", lambda *_: self._build_devices())
            monitor.connect("mount-changed", lambda *_: self._build_devices())
            monitor.connect("volume-added", lambda *_: self._build_devices())
            monitor.connect("volume-removed", lambda *_: self._build_devices())

    # ------------------------------------------------------------------ places
    def _build_places(self):
        self.places.clear()
        dirs = util.dirs_from_xdg()
        entries = [
            ("Recent", "document-open-recent-symbolic", "recent://"),
            ("Starred", "starred-symbolic", "starred://"),
            ("Home", "user-home-symbolic", util.HOME),
        ]
        for name, key in (("Desktop", "DESKTOP"), ("Documents", "DOCUMENTS"),
                          ("Downloads", "DOWNLOAD"), ("Music", "MUSIC"),
                          ("Pictures", "PICTURES"), ("Videos", "VIDEOS")):
            path = dirs.get(key)
            if path and os.path.isdir(path):
                entries.append((name, {
                    "Desktop": "user-desktop-symbolic",
                    "Documents": "folder-documents-symbolic",
                    "Downloads": "folder-download-symbolic",
                    "Music": "folder-music-symbolic",
                    "Pictures": "folder-pictures-symbolic",
                    "Videos": "folder-videos-symbolic",
                }[name], path))
        for name, icon, target in entries:
            row = SidebarRow(icon, name, self.window, target)
            self.places.rows.append(row)
            self.place_rows[target] = row

        self.places.rows.append(ui.sep())
        self.trash_row = SidebarRow("user-trash-symbolic", "Trash", self.window, "trash://")
        self.trash_row.connect("clicked", lambda *_: self.update_trash_count())
        gest = Gtk.GestureClick.new()
        gest.set_button(3)
        gest.connect("pressed", self._trash_menu)
        self.trash_row.add_controller(gest)
        self.places.rows.append(self.trash_row)
        self.update_trash_count()

    def _trash_menu(self, gesture, n, x, y):
        pop = Gtk.Popover()
        pop.add_css_class("glass-popover")
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        open_btn = Gtk.Button(label="Open Trash")
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", lambda *_: (pop.popdown(), self.window.navigate("trash://")))
        empty_btn = Gtk.Button(label="Empty Trash")
        empty_btn.add_css_class("flat")
        empty_btn.connect("clicked", lambda *_: (pop.popdown(), self.window.empty_trash()))
        box.append(open_btn)
        box.append(empty_btn)
        pop.set_child(box)
        pop.set_parent(self.trash_row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.popup()

    def update_trash_count(self):
        if not self.trash_row:
            return
        n = trash.trash_count()
        self.trash_row.set_badge(str(n) if n else "")

    # --------------------------------------------------------------- bookmarks
    def _refresh_bookmarks(self):
        self.bookmarks.clear()
        self.bookmark_rows = {}
        marks = self.prefs.bookmarks()
        if not marks:
            hint = ui.label("Drop a folder here", "side-sub")
            hint.set_margin_start(10)
            hint.set_margin_top(2)
            self.bookmarks.rows.append(hint)
        for b in marks:
            path = b.get("path")
            if not path:
                continue
            row = SidebarRow("folder-symbolic", b.get("label") or util.display_name(path),
                             self.window, path)
            row.set_tooltip_text(path)
            self._bookmark_dnd(row, path)
            gest = Gtk.GestureClick.new()
            gest.set_button(3)
            gest.connect("pressed", self._bookmark_menu, path)
            row.add_controller(gest)
            self.bookmarks.rows.append(row)
            self.bookmark_rows[path] = row
        # The whole section is a drop target for new bookmarks.
        dnd.add_file_drop_target(self.bookmarks, self._bookmark_drop)

    def _bookmark_dnd(self, row, path):
        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.MOVE)

        def prepare(src, x, y):
            content = Gdk.ContentProvider.new_typed(GObject.TYPE_STRING, path)
            return content

        source.connect("prepare", prepare)
        row.add_controller(source)
        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

        def drop(t, value, x, y):
            try:
                other = str(value)
            except Exception:
                return False
            marks = [b["path"] for b in self.prefs.bookmarks()]
            if other not in marks or path not in marks or other == path:
                return False
            marks.remove(other)
            marks.insert(marks.index(path), other)
            self.prefs.data["bookmarks"] = [{"path": p, "label": util.display_name(p)} for p in marks]
            self.prefs.save()
            self._refresh_bookmarks()
            self.window.refresh_sidebar()
            return True

        target.connect("drop", drop)
        row.add_controller(target)

    def _bookmark_drop(self, paths, cut, x, y):
        for p in paths:
            if os.path.isdir(p):
                self.prefs.add_bookmark(p)
        self._refresh_bookmarks()
        self.window.sync_breadcrumb()
        return True

    def _bookmark_menu(self, gesture, n, x, y, path):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        items = [
            ("Open", lambda: self.window.navigate(path)),
            ("Open in New Tab", lambda: self.window.open_in_new_tab(path)),
            ("Open in New Window", lambda: self.window.open_in_new_window(path)),
            ("", None),
            ("Move Up", lambda: (self.prefs.move_bookmark(path, -1), self._refresh_bookmarks())),
            ("Move Down", lambda: (self.prefs.move_bookmark(path, 1), self._refresh_bookmarks())),
            ("Remove Bookmark", lambda: (self.prefs.remove_bookmark(path), self._refresh_bookmarks())),
        ]
        for text, fn in items:
            if fn is None:
                box.append(ui.sep())
                continue
            b = Gtk.Button(label=text)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, f=fn: (pop.popdown(), f()))
            box.append(b)
        pop.set_child(box)
        pop.set_parent(gesture.get_widget())
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.popup()

    # ----------------------------------------------------------------- devices
    def _build_devices(self):
        self.devices.clear()
        self.device_rows = []
        try:
            monitor = Gio.VolumeMonitor.get()
            mounts = monitor.get_mounts() if monitor else []
        except Exception:
            mounts = []
        seen = set()
        for mount in mounts:
            try:
                root = mount.get_root()
                path = root.get_path()
                if not path or path in seen or path == "/":
                    continue
                seen.add(path)
                name = mount.get_name() or util.display_name(path)
                volume = mount.get_volume()
                icon = mount.get_icon() or (volume.get_icon() if volume else None)
                row = SidebarRow("drive-harddisk-symbolic", util.fsdec(name), self.window, path)
                if icon is not None:
                    try:
                        row.icon.set_from_gicon(icon)
                    except Exception:
                        pass
                free = total = 0
                free, total = util.free_space(path)
                if total:
                    frac = 1.0 - (free / total)
                    bar = Gtk.ProgressBar()
                    bar.add_css_class("side-bar")
                    bar.set_fraction(max(0.0, min(1.0, frac)))
                    bar.set_show_text(False)
                    row.set_badge(util.human_size(free))
                    sub = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                    sub.append(row)
                    bar.set_margin_start(10)
                    bar.set_margin_end(10)
                    bar.set_margin_bottom(2)
                    sub.append(bar)
                    self.devices.rows.append(sub)
                else:
                    self.devices.rows.append(row)
                gest = Gtk.GestureClick.new()
                gest.set_button(3)
                gest.connect("pressed", self._device_menu, mount, path)
                row.add_controller(gest)
                self.device_rows.append(row)
            except Exception:
                continue
        if not self.devices.rows.get_first_child():
            hint = ui.label("No removable devices", "side-sub")
            hint.set_margin_start(10)
            self.devices.rows.append(hint)
        connect_row = SidebarRow("network-server-symbolic", "Connect to Server\u2026", None)
        connect_row.connect("clicked", lambda *_: dialogs.connect_server(self.window))
        self.devices.rows.append(ui.sep())
        self.devices.rows.append(connect_row)
        if self.prefs.get("sidebar_open", {}).get("devices", True):
            self.devices.revealer.set_reveal_child(True)

    def _device_menu(self, gesture, n, x, y, mount, path):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        def add(text, fn):
            b = Gtk.Button(label=text)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b: (pop.popdown(), fn()))
            box.append(b)

        add("Open", lambda: self.window.navigate(path))
        add("Open in New Tab", lambda: self.window.open_in_new_tab(path))

        def unmount():
            def done(m, res):
                try:
                    m.unmount_with_operation_finish(res)
                except GLib.Error as e:
                    self.window.toast(e.message)
            op = Gio.MountOperation()
            mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)

        def eject():
            vol = mount.get_volume()
            if vol is None:
                return

            def done(v, res):
                try:
                    v.eject_with_operation_finish(res)
                except GLib.Error as e:
                    self.window.toast(e.message)

            op = Gio.MountOperation()
            vol.eject_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)

        add("Unmount", unmount)
        vol = mount.get_volume()
        if vol is not None and vol.can_eject():
            add("Eject", eject)
        pop.set_child(box)
        pop.set_parent(gesture.get_widget())
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.popup()

    # ------------------------------------------------------------------ state
    def set_location(self, location: str):
        for target, row in self.place_rows.items():
            row.set_on(target == location)
        for path, row in self.bookmark_rows.items():
            row.set_on(path == location)
        for row in self.device_rows:
            row.set_on(bool(row.path) and row.path == location)
        if self.trash_row:
            self.trash_row.set_on(location == "trash://")
        self.update_trash_count()
