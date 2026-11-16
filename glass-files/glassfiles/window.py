"""The main window: chrome, tabs, split panes, actions, jobs, status."""

from __future__ import annotations

import os
import shlex
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import (accent as accent_mod, css, dialogs, dnd, jobs, model, ops,
               prefs as prefs_mod, quicklook, search, sidebar as sidebar_mod,
               tabstrip as tabstrip_mod, thumbs, trash, ui, undo as undo_mod, util)


class Tab:
    def __init__(self, window, location=None, source_kind="dir", split=False):
        self.window = window
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_wide_handle(False)
        self.paned.set_resize_start_child(True)
        self.paned.set_resize_end_child(True)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)
        self.root.append(self.paned)
        self.panes: list = []
        self.active = 0
        first = self._make_pane(location, source_kind)
        self.panes.append(first)
        self.paned.set_start_child(first)
        if split:
            self.add_split(location)

    def _make_pane(self, location, source_kind="dir"):
        pane = Pane(self.window, location, source_kind)
        pane.connect("navigated", lambda p, loc: self.window.on_pane_navigated(p))
        pane.connect("selection-changed", lambda p: self.window.on_pane_selection(p))
        pane.connect("title-changed", lambda p, t: self.window.on_pane_title(p))
        pane.connect("toast", lambda p, msg: self.window.toast(msg))
        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("pressed", lambda g, n, x, y, p=pane: self.window.set_active_pane(p))
        pane.add_controller(click)
        return pane

    def add_split(self, location=None):
        if len(self.panes) >= 2:
            return
        loc = location or self.pane().location
        kind = self.pane().source_kind
        if kind != "dir":
            loc, kind = util.HOME, "dir"
        p2 = self._make_pane(loc, kind)
        self.panes.append(p2)
        self.paned.set_end_child(p2)
        self.active = 1
        w = max(400, self.window.get_width() - 240)
        self.paned.set_position(max(200, w // 2))
        self.window.set_active_pane(p2)
        self.window.tabstrip.rebuild()

    def remove_split(self):
        while len(self.panes) > 1:
            p = self.panes.pop()
            p.model.stop() if p.model else None
            if self.paned.get_end_child() is p:
                self.paned.set_end_child(None)
            if self.paned.get_start_child() is p:
                self.paned.set_start_child(None)
            p.unparent()
        self.active = 0
        self.window.set_active_pane(self.panes[0])
        self.window.tabstrip.rebuild()

    def pane(self):
        if not self.panes:
            return None
        return self.panes[min(self.active, len(self.panes) - 1)]

    def set_active_pane(self, pane):
        if pane in self.panes:
            self.active = self.panes.index(pane)
            for p in self.panes:
                p.set_active(p is pane)

    def title(self):
        p = self.pane()
        return p.title() if p else "Glass Files"

    def tooltip(self):
        p = self.pane()
        if not p:
            return ""
        if p.source_kind == "dir":
            return p.location
        return p.title()

    def serialize(self):
        return {
            "active": self.active,
            "panes": [{"location": p.location, "kind": p.source_kind,
                       "view": p.view_mode, "icon_size": p.icon_size,
                       "sort": p.sort_key, "desc": p.sort_desc}
                      for p in self.panes],
        }


Pane = None  # late import to avoid a cycle with window in pane.py


class GlassWindow(Gtk.ApplicationWindow):
    def __init__(self, app, prefs, location=None, source_kind="dir", split=False):
        super().__init__(application=app)
        global Pane
        from .pane import Pane as _Pane

        Pane = _Pane

        self.prefs = prefs
        self.app = app
        self.set_title("Glass Files")
        self.set_decorated(False)
        self.set_default_size(prefs.get("window", {}).get("width", 1280) or 1280,
                              prefs.get("window", {}).get("height", 820) or 820)
        self.set_size_request(720, 480)
        self.add_css_class("glass-window")
        self.add_css_class("glass-root")

        self.thumbpool = thumbs.ThumbPool()
        self.jobs = jobs.JobQueue(self._on_job_update, max_workers=2)
        self.undo_stack = undo_mod.UndoStack(on_change=self._update_undo)
        self.tabs: list[Tab] = []
        self.active_tab = None
        self._closed: list[dict] = []
        self._clip_cut = False
        self._drag_tab = None
        self._search_timeout = 0
        self._toast_timeout = 0
        self._quick = None
        self._suppress_zoom = False
        self._suppress_search = False
        self._suppress_view = False
        self._zoom_timeout = 0
        self._last_location = util.HOME

        self._build_ui()
        self._install_actions()
        self._install_keys()
        self._apply_css()
        self.apply_preferences(initial=True)
        self.new_tab(location or util.HOME, source_kind, split=split)
        self.connect("close-request", self._on_close)

        if prefs.get("window", {}).get("maximized"):
            self.maximize()

    # -------------------------------------------------------------------- ui
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("glass-root")
        self.set_child(root)
        self.root = root

        chrome = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        chrome.add_css_class("chrome")
        handle = Gtk.WindowHandle()
        handle.set_child(chrome)
        root.append(handle)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.back_btn = ui.button(icon="go-previous-symbolic", tooltip="Back (Alt+Left)",
                                  css="nav-btn", size=15)
        self.forward_btn = ui.button(icon="go-next-symbolic", tooltip="Forward (Alt+Right)",
                                     css="nav-btn", size=15)
        self.up_btn = ui.button(icon="go-up-symbolic", tooltip="Up (Alt+Up)",
                                css="nav-btn", size=15)
        self.refresh_btn = ui.button(icon="view-refresh-symbolic", tooltip="Refresh (F5)",
                                     css="nav-btn", size=15)
        self.back_btn.connect("clicked", lambda *_: self._pane_call("back"))
        self.forward_btn.connect("clicked", lambda *_: self._pane_call("forward"))
        self.up_btn.connect("clicked", lambda *_: self._pane_call("up"))
        self.refresh_btn.connect("clicked", lambda *_: self._pane_call("refresh"))
        for b in (self.back_btn, self.forward_btn, self.up_btn, self.refresh_btn):
            top.append(b)
        top.append(ui.spacer(False))

        self.path_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.path_pill.add_css_class("pill")
        self.path_pill.set_hexpand(True)
        self.path_stack = Gtk.Stack()
        self.path_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.path_stack.set_hexpand(True)
        self.crumbs_scroll = Gtk.ScrolledWindow()
        self.crumbs_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.crumbs_scroll.set_hexpand(True)
        self.crumbs_scroll.set_propagate_natural_height(True)
        self.crumbs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.crumbs.set_hexpand(True)
        self.crumbs_scroll.set_child(self.crumbs)
        self.path_stack.add_named(self.crumbs_scroll, "crumbs")

        self.path_entry = Gtk.Entry()
        self.path_entry.add_css_class("path-entry")
        self.path_entry.set_hexpand(True)
        self._completion_setup()
        self.path_stack.add_named(self.path_entry, "entry")
        self.path_pill.append(self.path_stack)
        top.append(self.path_pill)

        self.search_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.search_pill.add_css_class("pill")
        self.search = Gtk.SearchEntry()
        self.search.add_css_class("search-entry")
        self.search.set_placeholder_text("Search")
        self.search.set_size_request(190, -1)
        self.search.set_tooltip_text("Type to filter. Enter searches subfolders.")
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", self._on_search_activate)
        self.search_pill.append(self.search)
        top.append(self.search_pill)

        self.seg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.seg.add_css_class("seg")
        self.seg.add_css_class("pill")
        self.btn_grid = Gtk.ToggleButton()
        self.btn_grid.set_child(ui.image_icon("view-grid-symbolic", 15))
        self.btn_grid.add_css_class("seg-btn")
        self.btn_grid.set_tooltip_text("Icons (Ctrl+1)")
        self.btn_list = Gtk.ToggleButton()
        self.btn_list.set_child(ui.image_icon("view-list-symbolic", 15))
        self.btn_list.add_css_class("seg-btn")
        self.btn_list.set_tooltip_text("List (Ctrl+2)")
        self.btn_compact = Gtk.ToggleButton()
        self.btn_compact.set_child(ui.image_icon("view-list-symbolic", 15))
        self.btn_compact.add_css_class("seg-btn")
        self.btn_compact.set_tooltip_text("Compact (Ctrl+3)")
        self.btn_grid.set_group(self.btn_list)
        self.btn_compact.set_group(self.btn_list)
        self.btn_grid.connect("toggled", lambda b: b.get_active() and self.set_view("grid"))
        self.btn_list.connect("toggled", lambda b: b.get_active() and self.set_view("list"))
        self.btn_compact.connect("toggled", lambda b: b.get_active() and self.set_view("compact"))
        for b in (self.btn_grid, self.btn_list, self.btn_compact):
            self.seg.append(b)
        top.append(self.seg)

        self.sort_btn = Gtk.MenuButton()
        self.sort_btn.set_child(ui.image_icon("view-sort-descending-symbolic", 15))
        self.sort_btn.add_css_class("nav-btn")
        self.sort_btn.set_tooltip_text("Sort")
        self.sort_btn.set_popover(self._make_sort_popover())
        top.append(self.sort_btn)

        self.newfolder_btn = ui.button(icon="folder-new-symbolic", tooltip="New folder (Ctrl+Shift+N)",
                                       css="nav-btn", size=15)
        self.newfolder_btn.connect("clicked", lambda *_: self.new_folder())
        top.append(self.newfolder_btn)

        self.more_btn = Gtk.MenuButton()
        self.more_btn.set_child(ui.image_icon("open-menu-symbolic", 15))
        self.more_btn.add_css_class("nav-btn")
        self.more_btn.set_tooltip_text("More")
        self.more_btn.set_popover(self._make_more_popover())
        top.append(self.more_btn)

        top.append(ui.spacer(False))
        min_btn = ui.button(icon="window-minimize-symbolic", tooltip="Minimize",
                            css="win-btn", size=12)
        max_btn = ui.button(icon="window-maximize-symbolic", tooltip="Maximize",
                            css="win-btn", size=12)
        close_btn = ui.button(icon="window-close-symbolic", tooltip="Close",
                              css="win-btn close", size=12)
        min_btn.connect("clicked", lambda *_: self.minimize())
        max_btn.connect("clicked", lambda *_: self._toggle_maximize())
        close_btn.connect("clicked", lambda *_: self.close())
        for b in (min_btn, max_btn, close_btn):
            top.append(b)
        chrome.append(top)

        self.tabstrip = tabstrip_mod.TabStrip(self)
        chrome.append(self.tabstrip)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.add_css_class("main-paned")
        self.sidebar = sidebar_mod.Sidebar(self)
        paned.set_start_child(self.sidebar)
        paned.set_shrink_start_child(False)
        paned.set_resize_start_child(False)
        paned.set_position(212)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.tab_stack = Gtk.Stack()
        self.tab_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.tab_stack.set_transition_duration(110)
        self.tab_stack.set_hexpand(True)
        self.tab_stack.set_vexpand(True)
        content.append(self.tab_stack)
        content.append(self._build_status())
        paned.set_end_child(content)
        paned.set_resize_end_child(True)
        root.append(paned)
        self.main_paned = paned

        self.monitor = Gio.File.new_for_path(
            os.path.expanduser("~/.config/kitty/colors.conf")).monitor_file(
            Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self._on_colors_changed)
        self._colors_timeout = 0

    def _build_status(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.add_css_class("status")
        self.status_count = ui.label("", "status-label")
        self.status_sel = ui.label("", "status-label status-strong")
        self.status_toast = ui.label("", "status-label link")
        self.status_toast.set_visible(False)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        bar.append(self.status_count)
        bar.append(self.status_sel)
        bar.append(self.status_toast)
        bar.append(self.spinner)
        bar.append(ui.spacer())
        self.status_free = ui.label("", "status-label")
        bar.append(self.status_free)
        self.zoom = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 56, 256, 4)
        self.zoom.add_css_class("zoom")
        self.zoom.set_draw_value(False)
        self.zoom.set_tooltip_text("Icon size")
        self.zoom.set_value(112)
        self.zoom.set_size_request(96, -1)
        self.zoom.connect("value-changed", self._on_zoom)
        bar.append(self.zoom)
        self.jobs_btn = Gtk.MenuButton()
        self.jobs_btn.set_child(ui.image_icon("emblem-downloads-symbolic", 14))
        self.jobs_btn.add_css_class("nav-btn")
        self.jobs_btn.set_tooltip_text("File operations")
        self.jobs_btn.set_popover(self._make_jobs_popover())
        bar.append(self.jobs_btn)
        return bar

    def _make_sort_popover(self):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for label, key in (("Name", "name"), ("Size", "size"), ("Modified", "modified"),
                           ("Type", "type"), ("Extension", "extension")):
            b = Gtk.Button()
            b.add_css_class("flat")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.append(ui.label(label, "small"))
            row.append(ui.spacer())
            mark = ui.label("", "link small")
            row.append(mark)
            b.set_child(row)
            b._mark = mark
            b._key = key
            b.connect("clicked", lambda _b, k=key: (self._set_sort(k), pop.popdown()))
            box.append(b)
        box.append(ui.sep())
        desc = Gtk.CheckButton(label="Descending")
        desc.add_css_class("small")
        desc.connect("toggled", lambda c: self.set_sort_desc(c.get_active()))
        folders = Gtk.CheckButton(label="Folders first")
        folders.add_css_class("small")
        folders.connect("toggled", lambda c: self.set_folders_first(c.get_active()))
        box.append(desc)
        box.append(folders)
        pop.set_child(box)
        pop._desc = desc
        pop._folders = folders
        pop._rows = box
        return pop

    def _make_more_popover(self):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        def add(text, fn, accel=None):
            b = Gtk.Button()
            b.add_css_class("flat")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            row.append(ui.label(text, "small"))
            row.append(ui.spacer())
            if accel:
                row.append(ui.label(accel, "faint small"))
            b.set_child(row)
            b.connect("clicked", lambda _b: (pop.popdown(), fn()))
            box.append(b)

        add("New Tab", self.new_tab, "Ctrl+T")
        add("New Window", lambda: self.app.new_window(), "Ctrl+N")
        add("Split View", self.toggle_split, "F3")
        box.append(ui.sep())
        add("Show Hidden Files", lambda: self.toggle_hidden(), "Ctrl+H")
        add("Preview Pane", lambda: self.toggle_preview(), "F11")
        add("Undo", lambda: self.undo(), "Ctrl+Z")
        add("Redo", lambda: self.redo(), "Ctrl+Shift+Z")
        box.append(ui.sep())
        add("Add Bookmark", self.add_bookmark, "Ctrl+D")
        add("Connect to Server\u2026", lambda: dialogs.connect_server(self))
        add("Empty Trash", self.empty_trash)
        box.append(ui.sep())
        add("Preferences", lambda: dialogs.preferences_dialog(self))
        add("Keyboard Shortcuts", self.show_shortcuts)
        add("About Glass Files", self.show_about)
        pop.set_child(box)
        return pop

    def _make_jobs_popover(self):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(330, -1)
        self._jobs_box = box
        pop.set_child(box)
        self._jobs_pop = pop
        return pop

    def _completion_setup(self):
        try:
            completion = Gtk.EntryCompletion()
            completion.set_minimum_key_length(1)
            completion.set_text_column(0)
            import gi as _gi

            _gi.require_version("Gtk", "4.0")
            store = Gtk.ListStore(str)
            completion.set_model(store)
            self.path_entry.set_completion(completion)
            self._completion_store = store
            self.path_entry.connect("changed", self._on_path_changed)
        except Exception:
            self._completion_store = None

    def _on_path_changed(self, entry):
        store = getattr(self, "_completion_store", None)
        if store is None:
            return
        text = entry.get_text()
        try:
            store.clear()
            expanded = os.path.expanduser(text)
            folder = expanded if expanded.endswith("/") else os.path.dirname(expanded)
            prefix = "" if expanded.endswith("/") else os.path.basename(expanded)
            if folder and os.path.isdir(folder):
                for name in sorted(os.listdir(folder)):
                    if name.startswith(".") and not prefix.startswith("."):
                        continue
                    if name.startswith(prefix):
                        candidate = os.path.join(folder, name)
                        store.append([candidate + ("/" if os.path.isdir(candidate) else "")])
        except OSError:
            pass

    # ------------------------------------------------------------------ css
    def _apply_css(self):
        self.app.reload_css()

    def resolve_theme(self):
        mode = self.prefs.get("theme", "dark")
        if mode == "auto":
            return css.LIGHT if accent_mod.desktop_is_light() else css.DARK
        return css.LIGHT if mode == "light" else css.DARK

    def apply_preferences(self, initial=False):
        self.app.reload_css()
        self.prefs.load()
        for tab in self.tabs:
            for p in tab.panes:
                p.set_preview(bool(self.prefs.get("preview", False)))
                if not initial:
                    p.view_mode = self.prefs.get("view", p.view_mode)
                    p._apply_view_mode()
                    self._sync_view_buttons()
        self.sync_status()

    def _on_colors_changed(self, monitor, file, other, event):
        if self._colors_timeout:
            GLib.source_remove(self._colors_timeout)
        self._colors_timeout = GLib.timeout_add(350, self._reload_accent)

    def _reload_accent(self):
        self._colors_timeout = 0
        self.app.reload_css()
        for win in self.app.get_windows():
            try:
                win.sync_status()
            except Exception:
                pass
        return False

    # ----------------------------------------------------------------- tabs
    def new_tab(self, location=None, source_kind="dir", split=False):
        if location is None:
            p = self.active_pane()
            if p and p.source_kind == "dir":
                location = p.location
            elif p and p.source_kind == "search":
                location = p.current_folder()
            else:
                location = util.HOME
        tab = Tab(self, location, source_kind, split=split)
        self.tabs.append(tab)
        self.tab_stack.add_named(tab.root, str(id(tab)))
        self.activate_tab(tab)
        self.tabstrip.rebuild()
        if self.active_pane():
            self.active_pane().focus_view()
        return tab

    def activate_tab(self, tab):
        if tab not in self.tabs:
            return
        self.active_tab = tab
        self.tab_stack.set_visible_child_name(str(id(tab)))
        self.tabstrip.rebuild()
        self.on_active_pane_changed(tab.pane())
        self.sync_status()

    def close_tab(self, tab):
        if tab not in self.tabs:
            return
        self._closed.append(tab.serialize())
        del self._closed[:-20]
        idx = self.tabs.index(tab)
        self.tabs.remove(tab)
        if self.tab_stack.get_child_by_name(str(id(tab))):
            self.tab_stack.remove(self.tab_stack.get_child_by_name(str(id(tab))))
        for p in tab.panes:
            if p.model:
                p.model.stop()
        tab.root.unparent()
        if not self.tabs:
            self.close()
            return
        self.activate_tab(self.tabs[min(idx, len(self.tabs) - 1)])
        self.tabstrip.rebuild()

    def close_other_tabs(self, tab):
        for other in list(self.tabs):
            if other is not tab:
                self.close_tab(other)

    def duplicate_tab(self, tab):
        self.new_tab(tab.pane().location, tab.pane().source_kind)

    def move_tab(self, src, dst):
        if src not in self.tabs or dst not in self.tabs:
            return
        i, j = self.tabs.index(src), self.tabs.index(dst)
        self.tabs.insert(j, self.tabs.pop(i))
        self.tabstrip.rebuild()

    def detach_tab(self, tab):
        loc = tab.pane().location
        self.app.new_window(loc)
        self.close_tab(tab)

    def reopen_tab(self):
        if not self._closed:
            return
        state = self._closed.pop()
        panes = state.get("panes", [])
        if not panes:
            return
        first = panes[0]
        tab = self.new_tab(first.get("location"), first.get("kind", "dir"),
                           split=len(panes) > 1)
        if len(panes) > 1:
            tab.panes[1].navigate(panes[1].get("location") or util.HOME)
            tab.active = state.get("active", 0)
            self.tabstrip.rebuild()

    def next_tab(self, delta=1):
        if len(self.tabs) < 2:
            return
        idx = self.tabs.index(self.active_tab)
        self.activate_tab(self.tabs[(idx + delta) % len(self.tabs)])

    # ------------------------------------------------------------- navigation
    def active_pane(self):
        return self.active_tab.pane() if self.active_tab else None

    def set_active_pane(self, pane):
        for tab in self.tabs:
            if pane in tab.panes:
                if self.active_tab is not tab:
                    self.activate_tab(tab)
                tab.set_active_pane(pane)
                break
        self.on_active_pane_changed(pane)

    def on_active_pane_changed(self, pane):
        if pane is None:
            return
        self.sync_breadcrumb()
        self.sync_sidebar()
        self.sync_status()
        self._sync_view_buttons()
        self._sync_zoom(pane.icon_size)
        self._sync_sort_menu()
        desired = pane.search_query or ""
        if self.search.get_text() != desired:
            self._suppress_search = True
            self.search.set_text(desired)
            self._suppress_search = False
        self._update_nav_buttons()

    def _pane_call(self, name, *args):
        p = self.active_pane()
        if p is not None and hasattr(p, name):
            return getattr(p, name)(*args)
        return None

    def navigate(self, location):
        if self.active_pane() is None:
            self.new_tab(location)
        else:
            self.active_pane().navigate(location)

    def open_path(self, path):
        if not path:
            return
        if os.path.isdir(path):
            self.navigate(path)
            return
        try:
            launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
            launcher.launch(self, None, self._on_launched)
        except Exception as e:
            self.toast(f"Cannot open: {e}")

    def _on_launched(self, launcher, result):
        try:
            launcher.launch_finish(result)
        except GLib.Error as e:
            self.toast(f"No app for this file: {e.message}")

    def open_in_new_tab(self, path=None):
        path = path or self.active_pane().first_selected() or self.active_pane().location
        if os.path.isdir(path):
            self.new_tab(path)
        elif os.path.exists(path):
            parent = os.path.dirname(path)
            tab = self.new_tab(parent)
            tab.pane()._select_path_soon(path)

    def open_in_new_window(self, path=None):
        path = path or self.active_pane().first_selected() or self.active_pane().location
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        self.app.new_window(folder)

    def open_terminal(self, path=None):
        path = path or self.active_pane().first_selected()
        if not path:
            path = self.active_pane().current_folder()
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        terminal = self.prefs.get("terminal", "kitty") or "kitty"
        try:
            cmd = shlex.split(terminal)
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
            launcher.set_cwd(path)
            launcher.spawnv(cmd)
        except GLib.Error as e:
            self.toast(f"Terminal failed: {e.message}")

    # ---------------------------------------------------------------- actions
    def _install_actions(self):
        def simple(name, fn):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda a, p: fn())
            self.add_action(act)
            return act

        def stateful(name, state_type, initial, fn):
            act = Gio.SimpleAction.new_stateful(name, state_type, initial)
            act.connect("activate", lambda a, p: fn(a, p))
            self.add_action(act)
            return act

        simple("open", lambda: self._open_selected())
        simple("open-with", lambda: dialogs.open_with_dialog(self, self._selected_or_folder()))
        simple("open-tab", self.open_in_new_tab)
        simple("open-window", self.open_in_new_window)
        simple("open-terminal", lambda: self.open_terminal())
        simple("open-terminal-here", lambda: self.open_terminal(self.active_pane().current_folder()))
        simple("back", lambda: self._pane_call("back"))
        simple("forward", lambda: self._pane_call("forward"))
        simple("up", lambda: self._pane_call("up"))
        simple("home", lambda: self.navigate(util.HOME))
        simple("refresh", lambda: self._pane_call("refresh"))
        simple("cut", lambda: self._set_clipboard(True))
        simple("copy", lambda: self._set_clipboard(False))
        simple("paste", lambda: self.paste())
        simple("rename", lambda: self.rename_selected())
        simple("batch-rename", lambda: dialogs.batch_rename_dialog(self, self.active_pane().selected_paths()))
        simple("duplicate", self.duplicate_selected)
        simple("trash", self.trash_selected)
        simple("delete", self.delete_selected)
        simple("restore", self.restore_selected)
        simple("empty-trash", self.empty_trash)
        simple("new-folder", self.new_folder)
        simple("new-file", lambda: dialogs.new_file_dialog(self, self.active_pane().current_folder()))
        simple("new-tab", lambda: self.new_tab())
        simple("close-tab", lambda: self.close_tab(self.active_tab) if self.active_tab else None)
        simple("reopen-tab", self.reopen_tab)
        simple("next-tab", lambda: self.next_tab(1))
        simple("prev-tab", lambda: self.next_tab(-1))
        simple("new-window", lambda: self.app.new_window())
        simple("close-window", lambda: self.close())
        simple("quit", lambda: self.app.quit())
        simple("compress", lambda: dialogs.compress_dialog(self, self.active_pane().selected_paths() or [self.active_pane().current_folder()]))
        simple("extract", lambda: self.extract_selected(False))
        simple("extract-to", lambda: self.extract_selected(True))
        simple("properties", lambda: self.show_properties())
        simple("copy-path", self.copy_path)
        simple("select-all", self.select_all)
        simple("invert-selection", self.invert_selection)
        simple("star-toggle", self.star_toggle)
        simple("view-grid", lambda: self.set_view("grid"))
        simple("view-list", lambda: self.set_view("list"))
        simple("view-compact", lambda: self.set_view("compact"))
        simple("show-hidden-toggle", lambda: self.toggle_hidden())
        simple("sort-name", lambda: self._set_sort("name"))
        simple("sort-size", lambda: self._set_sort("size"))
        simple("sort-modified", lambda: self._set_sort("modified"))
        simple("sort-type", lambda: self._set_sort("type"))
        simple("sort-extension", lambda: self._set_sort("extension"))
        simple("sort-desc-toggle", lambda: self._toggle_sort_desc())
        simple("folders-first-toggle", lambda: self._toggle_folders_first())
        simple("toggle-preview", self.toggle_preview)
        simple("toggle-split", self.toggle_split)
        simple("quicklook", self.toggle_quicklook)
        simple("preferences", lambda: dialogs.preferences_dialog(self))
        simple("about", self.show_about)
        simple("shortcuts", self.show_shortcuts)
        simple("undo", self.undo)
        simple("redo", self.redo)
        simple("bookmark-add", self.add_bookmark)
        simple("bookmark-remove", self.remove_bookmark)
        simple("connect-server", lambda: dialogs.connect_server(self))
        simple("zoom-in", lambda: self.bump_zoom(16))
        simple("zoom-out", lambda: self.bump_zoom(-16))
        simple("clear-search", self.clear_search)
        simple("focus-search", self.focus_search)
        simple("focus-location", self.focus_location)

        self._update_undo()

    def _install_keys(self):
        keys = Gtk.EventControllerKey.new()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_key(self, c, keyval, keycode, state):
        focus = self.get_focus()
        in_text = isinstance(focus, (Gtk.Entry, Gtk.TextView, Gtk.SearchEntry))
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if keyval == Gdk.KEY_Escape:
            if self._quick is not None and self._quick.get_visible():
                self._quick.hide()
                return True
            if self.search.get_text():
                self.clear_search()
                return True
            if self.path_stack.get_visible_child_name() == "entry":
                self._hide_path_entry()
                return True
        if keyval == Gdk.KEY_space and not in_text:
            self.toggle_quicklook()
            return True
        if keyval in (Gdk.KEY_F2,) and not in_text:
            self.rename_selected()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and not in_text:
            if shift:
                self.delete_selected()
            else:
                self.trash_selected()
            return True
        if ctrl and keyval == Gdk.KEY_l:
            self.focus_location()
            return True
        if ctrl and keyval == Gdk.KEY_f:
            self.focus_search()
            return True
        if ctrl and keyval == Gdk.KEY_h:
            self.toggle_hidden()
            return True
        if ctrl and keyval == Gdk.KEY_a and not in_text:
            self.select_all()
            return True
        if ctrl and keyval == Gdk.KEY_d and not in_text:
            self.add_bookmark()
            return True
        if ctrl and keyval == Gdk.KEY_Tab:
            self.next_tab(-1 if shift else 1)
            return True
        if keyval == Gdk.KEY_F5:
            self._pane_call("refresh")
            return True
        if keyval == Gdk.KEY_F3:
            self.toggle_split()
            return True
        if keyval == Gdk.KEY_F11:
            self.toggle_preview()
            return True
        if alt and keyval == Gdk.KEY_Left:
            self._pane_call("back")
            return True
        if alt and keyval == Gdk.KEY_Right:
            self._pane_call("forward")
            return True
        if alt and keyval == Gdk.KEY_Up:
            self._pane_call("up")
            return True
        if keyval == Gdk.KEY_BackSpace and not in_text:
            self._pane_call("up")
            return True
        if ctrl and keyval in (Gdk.KEY_equal, Gdk.KEY_plus):
            self.bump_zoom(16)
            return True
        if ctrl and keyval == Gdk.KEY_minus:
            self.bump_zoom(-16)
            return True
        if ctrl and keyval == Gdk.KEY_z:
            if in_text:
                return False
            self.redo() if shift else self.undo()
            return True
        if ctrl and keyval == Gdk.KEY_n and shift:
            self.new_folder()
            return True
        if ctrl and keyval == Gdk.KEY_1:
            self.set_view("grid")
            return True
        if ctrl and keyval == Gdk.KEY_2:
            self.set_view("list")
            return True
        if ctrl and keyval == Gdk.KEY_3:
            self.set_view("compact")
            return True
        return False

    # ----------------------------------------------------------------- search
    def _on_search_changed(self, entry):
        if self._suppress_search:
            return
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        self._search_timeout = GLib.timeout_add(160, self._apply_search)

    def _apply_search(self):
        self._search_timeout = 0
        p = self.active_pane()
        if p is not None:
            p.set_query(self.search.get_text())
            self.sync_status()
        return False

    def _on_search_activate(self, entry):
        text = entry.get_text().strip()
        if not text:
            return
        p = self.active_pane()
        if p is not None:
            p.run_recursive_search(text)

    def focus_search(self):
        self.search.grab_focus()
        self.search.select_region(0, -1)

    def clear_search(self):
        self.search.set_text("")
        p = self.active_pane()
        if p is not None:
            if p.source_kind == "search":
                p.navigate(p.current_folder())
            else:
                p.set_query("")
        self.sync_status()

    # ------------------------------------------------------------------ path
    def sync_breadcrumb(self):
        child = self.crumbs.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.crumbs.remove(child)
            child = nxt
        p = self.active_pane()
        if p is None:
            return
        if p.source_kind != "dir":
            btn = ui.button(text=p.title(), css="crumb-btn crumb-cur")
            self.crumbs.append(btn)
            return
        parts = []
        path = p.location
        while True:
            head, tail = os.path.split(path)
            if tail:
                parts.append((tail, path))
            else:
                if head == "/":
                    parts.append(("/", "/"))
                break
            if head == path:
                break
            path = head
            if path == "/":
                parts.append(("/", "/"))
                break
        parts.reverse()
        if p.location == util.HOME:
            parts = [("\u2302", util.HOME)]
        for name, seg_path in parts:
            label = util.fsdec(name)
            if seg_path == util.HOME and name == util.fsdec(os.path.basename(util.HOME)):
                label = "\u2302"
            btn = ui.button(text=label, css="crumb-btn")
            if seg_path == p.location:
                btn.add_css_class("crumb-cur")
            btn.set_tooltip_text(seg_path)
            btn.connect("clicked", lambda _b, sp=seg_path: self.navigate(sp))
            dnd.add_file_drop_target(
                btn, lambda paths, cut, x, y, sp=seg_path: self.paste_paths(paths, sp, cut))
            self.crumbs.append(btn)
            if seg_path != p.location:
                self.crumbs.append(ui.label("\u203a", "crumb-sep"))
        self.path_entry.set_text(p.location if p.source_kind == "dir" else p.title())
        self.path_stack.set_visible_child_name("crumbs")
        GLib.idle_add(self._scroll_crumbs_end)
        self._update_nav_buttons()

    def _scroll_crumbs_end(self):
        adj = self.crumbs_scroll.get_hadjustment()
        if adj:
            adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def focus_location(self):
        p = self.active_pane()
        if p is None:
            return
        self.path_stack.set_visible_child_name("entry")
        self.path_entry.set_text(p.location if p.source_kind == "dir" else "");
        self.path_entry.grab_focus()
        self.path_entry.select_region(0, -1)

    def _hide_path_entry(self):
        self.path_stack.set_visible_child_name("crumbs")

    def _submit_path(self, entry):
        text = entry.get_text().strip()
        if not text:
            self._hide_path_entry()
            return
        target = util.expand_path(text)
        self._hide_path_entry()
        self.navigate(target)

    # --------------------------------------------------------------- sidebar
    def sync_sidebar(self):
        p = self.active_pane()
        if p is not None:
            self.sidebar.set_location(p.location)

    def refresh_sidebar(self):
        self.sidebar.update_trash_count()
        self.sidebar._refresh_bookmarks()
        self.sync_sidebar()

    def add_bookmark(self):
        p = self.active_pane()
        if p is None:
            return
        path = p.first_selected() if p.selected_paths() else p.current_folder()
        if not os.path.isdir(path):
            path = os.path.dirname(path)
        self.prefs.add_bookmark(path)
        self.refresh_sidebar()
        self.toast("Bookmark added")

    def remove_bookmark(self):
        p = self.active_pane()
        if p is None:
            return
        path = p.current_folder()
        self.prefs.remove_bookmark(path)
        self.refresh_sidebar()
        self.toast("Bookmark removed")

    # ---------------------------------------------------------------- status
    def sync_status(self):
        p = self.active_pane()
        if p is None:
            return
        total, sel, size, known = p.status_counts()
        self.status_count.set_text(f"{total} item{'s' if total != 1 else ''}")
        if sel:
            extra = p.model.selected_count() - sum(
                1 for i in p.selected_infos() if model.size_of(i) >= 0)
            txt = f"{sel} selected \u00b7 {util.human_size(size)}"
            if extra:
                txt += f" + {extra} folder{'s' if extra != 1 else ''}"
            self.status_sel.set_text(txt)
        else:
            self.status_sel.set_text("")
        free, _total = util.free_space(p.current_folder())
        self.status_free.set_text(f"{util.human_size(free)} free")
        self.spinner.set_visible(bool(p.model and p.model.is_loading()))
        if p.model and p.model.is_loading():
            self.spinner.start()
        else:
            self.spinner.stop()
        try:
            self._sync_zoom(p.icon_size)
        except Exception:
            pass

    def _sync_zoom(self, value):
        self._suppress_zoom = True
        try:
            self.zoom.set_value(int(value))
        finally:
            self._suppress_zoom = False

    def _on_zoom(self, scale):
        if self._suppress_zoom:
            return
        value = int(scale.get_value())
        if self._zoom_timeout:
            GLib.source_remove(self._zoom_timeout)

        def apply():
            self._zoom_timeout = 0
            p = self.active_pane()
            if p is not None:
                p.set_icon_size(value)
            return False

        self._zoom_timeout = GLib.timeout_add(140, apply)

    def bump_zoom(self, delta):
        p = self.active_pane()
        if p is None:
            return
        p.set_icon_size(p.icon_size + delta)
        self._sync_zoom(p.icon_size)

    def toast(self, message):
        self.status_toast.set_text(util.elide_middle(message, 80))
        self.status_toast.set_visible(True)
        if self._toast_timeout:
            GLib.source_remove(self._toast_timeout)
        self._toast_timeout = GLib.timeout_add(3200, self._hide_toast)

    def _hide_toast(self):
        self.status_toast.set_visible(False)
        self._toast_timeout = 0
        return False

    # ------------------------------------------------------------------ views
    def set_view(self, mode):
        if self._suppress_view:
            return
        p = self.active_pane()
        if p is None:
            return
        p.set_view_mode(mode)
        self._sync_view_buttons()

    def _sync_view_buttons(self):
        p = self.active_pane()
        if p is None:
            return
        self._suppress_view = True
        try:
            for btn, mode in ((self.btn_grid, "grid"), (self.btn_list, "list"),
                              (self.btn_compact, "compact")):
                want = mode == p.view_mode
                if btn.get_active() != want:
                    btn.set_active(want)
        finally:
            self._suppress_view = False

    def _set_sort(self, key):
        p = self.active_pane()
        if p is None:
            return
        desc = p.sort_desc if p.sort_key == key else False
        p.set_sort(key, desc)
        self._sync_sort_menu()

    def set_sort_desc(self, desc):
        p = self.active_pane()
        if p is None:
            return
        p.set_sort(p.sort_key, bool(desc))
        self._sync_sort_menu()

    def _toggle_sort_desc(self):
        p = self.active_pane()
        if p is not None:
            p.set_sort(p.sort_key, not p.sort_desc)
            self._sync_sort_menu()

    def set_folders_first(self, on):
        p = self.active_pane()
        if p is None:
            return
        p.folders_first = bool(on)
        p.set_sort(p.sort_key, p.sort_desc, p.folders_first)
        self._sync_sort_menu()

    def _toggle_folders_first(self):
        p = self.active_pane()
        if p is not None:
            self.set_folders_first(not p.folders_first)

    def _sync_sort_menu(self):
        p = self.active_pane()
        pop = self.sort_btn.get_popover()
        if p is None or pop is None:
            return
        for child in pop._rows:
            if isinstance(child, Gtk.Button) and hasattr(child, "_mark"):
                key = getattr(child, "_key", None)
                child._mark.set_text("\u2713" if key == p.sort_key else "")
        pop._desc.set_active(p.sort_desc)
        pop._folders.set_active(p.folders_first)

    def toggle_hidden(self):
        p = self.active_pane()
        if p is not None:
            p.toggle_hidden()

    def toggle_preview(self):
        show = not bool(self.prefs.get("preview", False))
        self.prefs.set("preview", show)
        for tab in self.tabs:
            for p in tab.panes:
                p.set_preview(show)
        self.sync_status()

    def toggle_split(self):
        if self.active_tab is None:
            return
        if len(self.active_tab.panes) > 1:
            self.active_tab.remove_split()
        else:
            self.active_tab.add_split()
        self.sync_status()

    def _update_nav_buttons(self):
        p = self.active_pane()
        self.back_btn.set_sensitive(bool(p and p.hindex > 0))
        self.forward_btn.set_sensitive(bool(p and p.hindex < len(p.history) - 1))
        self.up_btn.set_sensitive(bool(p and (p.source_kind != "dir" or p.location != "/")))

    # ------------------------------------------------------------ selection ops
    def _selected_or_folder(self):
        p = self.active_pane()
        paths = p.selected_paths() if p else []
        return paths or ([p.current_folder()] if p else [])

    def _open_selected(self):
        p = self.active_pane()
        if p is None:
            return
        paths = p.selected_paths()
        for path in paths:
            if os.path.isdir(path):
                self.navigate(path)
                break
            self.open_path(path)
            break

    def select_all(self):
        p = self.active_pane()
        if p and p.model:
            p.model.selection.select_all()

    def invert_selection(self):
        p = self.active_pane()
        if not p or not p.model:
            return
        bits = p.model.selection.get_selection()
        for i in range(p.model.count()):
            if bits.contains(i):
                p.model.selection.unselect_item(i)
            else:
                p.model.selection.select_item(i, False)

    def copy_path(self):
        p = self.active_pane()
        if p is None:
            return
        paths = p.selected_paths() or [p.current_folder()]
        clip = dnd.clipboard()
        if clip:
            clip.set("\n".join(paths))
        self.toast("Path copied")

    def _set_clipboard(self, cut):
        p = self.active_pane()
        if p is None:
            return
        paths = p.selected_paths()
        if not paths:
            self.toast("Nothing selected")
            return
        dnd.set_clipboard(paths, cut)
        self._clip_cut = cut
        self.toast(f"{len(paths)} item{'s' if len(paths) != 1 else ''} {'cut' if cut else 'copied'}")

    def paste(self):
        dnd.read_clipboard(self._on_clipboard_read)

    def _on_clipboard_read(self, paths, cut):
        p = self.active_pane()
        if p is None:
            return
        if not paths:
            self.toast("Clipboard has no files")
            return
        dest = p.current_folder()
        if not os.path.isdir(dest):
            dest = util.HOME
        self.paste_paths(paths, dest, cut)

    def paste_paths(self, paths, dest, cut):
        if not paths or not dest:
            return
        paths = [p for p in paths if os.path.lexists(p)]
        if not paths:
            return
        mode = ops.MOVE if cut else ops.COPY
        dest_copy = dest

        def worker(job):
            def resolve(src, dst, is_dir, dst_is_dir):
                return self._resolve_conflict(job, src, dst, is_dir, dst_is_dir)

            cb = jobs.copy_progress(job)
            return ops.copy_move(paths, dest_copy, mode, resolve=resolve, progress=cb,
                                 cancel=job.cancel_event)

        def done(job, error):
            if job.status == "failed":
                self.toast(f"Operation failed: {job.error}")
                return
            if job.status == "cancelled":
                self.toast("Operation cancelled")
                return
            results = job.result or []
            if mode == ops.MOVE:
                self.undo_stack.push(undo_mod.MoveAction(results, "Move"))
            else:
                self.undo_stack.push(undo_mod.CopyAction(results))
            moved = sum(1 for r in results if r.get("outcome") in (ops.Outcome.MOVED,))
            copied = sum(1 for r in results if r.get("outcome") in (ops.Outcome.COPIED, ops.Outcome.REPLACED, ops.Outcome.MERGED))
            self.toast(f"{moved} moved, {copied} copied \u2192 {util.display_name(dest_copy)}")
            self.refresh_all()

        self.jobs.submit(("Moving" if mode == ops.MOVE else "Copying") +
                         f" {len(paths)} item{'s' if len(paths) != 1 else ''}",
                         worker, done)

    def _resolve_conflict(self, job, src, dst, is_dir, dst_is_dir):
        req = dialogs.ConflictRequest(src, dst, is_dir, dst_is_dir)

        def show():
            dialogs.conflict_dialog(self, req)
            return False

        GLib.idle_add(show)
        while not req.event.wait(0.2):
            if job.cancelled:
                return ops.SKIP
        return req.answer or ops.SKIP

    def do_rename(self, old, new_name):
        new = ops.rename(old, new_name)
        self.undo_stack.push(undo_mod.RenameAction([(old, new)]))
        self.refresh_all()
        return new

    def rename_selected(self):
        p = self.active_pane()
        if p is None:
            return
        path = p.first_selected()
        if path:
            p.begin_rename(path)

    def rename_dialog(self, path):
        dialogs.rename_dialog(self, path)

    def duplicate_selected(self):
        paths = self.active_pane().selected_paths() if self.active_pane() else []
        if not paths:
            return

        def worker(job):
            out = []
            for path in paths:
                job.set_progress(0.2, util.display_name(path))
                out.append(ops.duplicate(path, cancel=job.cancel_event))
            return out

        def done(job, error):
            if job.status == "done":
                self.toast(f"Duplicated {len(job.result)} item(s)")
                self.refresh_all()
            elif error:
                self.toast(str(error))

        self.jobs.submit("Duplicating", worker, done)

    def apply_batch_rename(self, pairs):
        def worker(job):
            actual = []
            for i, (old, new) in enumerate(pairs):
                if job.cancelled:
                    break
                parent = os.path.dirname(old)
                target = os.path.join(parent, new)
                if os.path.lexists(target) and not util.same_path(target, old):
                    target = util.unique_path(parent, new)
                try:
                    os.rename(old, target)
                    actual.append((old, target))
                except OSError as e:
                    job.set_progress(i / len(pairs), e.strerror or "")
            return actual

        def done(job, error):
            if job.result:
                self.undo_stack.push(undo_mod.RenameAction(job.result))
                self.toast(f"Renamed {len(job.result)} item(s)")
            if error:
                self.toast(str(error))
            self.refresh_all()

        self.jobs.submit("Batch rename", worker, done)

    # ------------------------------------------------------------------ trash
    def trash_selected(self):
        p = self.active_pane()
        if p is None or p.source_kind == "trash":
            return
        paths = p.selected_paths()
        if not paths:
            return

        def worker(job):
            return trash.trash(paths, progress=lambda f, name: job.set_progress(f, name))

        def done(job, error):
            if job.status == "done":
                self.undo_stack.push(undo_mod.TrashAction(job.result))
                self.toast(f"Moved {len(job.result)} item(s) to Trash")
                self.refresh_sidebar()
                self.refresh_all()
            elif error:
                self.toast(f"Trash failed: {error}")

        self.jobs.submit(f"Moving to Trash", worker, done)

    def delete_selected(self):
        p = self.active_pane()
        if p is None:
            return
        if p.source_kind == "trash":
            records = [p.trash_records[path] for path in p.selected_paths() if path in p.trash_records]
            if not records:
                return

            def confirm_purge():
                def worker(job):
                    return trash.purge(records)

                def done(job, error):
                    self.toast(f"Deleted {job.result or 0} item(s) permanently")
                    self.refresh_all()
                    self.refresh_sidebar()

                self.jobs.submit("Deleting permanently", worker, done)

            dialogs.confirm(self, "Delete permanently?",
                            f"{len(records)} item(s) will be gone for good.",
                            "Delete", confirm_purge,
                            "This cannot be undone.")
            return
        paths = p.selected_paths()
        if not paths:
            return

        def go():
            def worker(job):
                return ops.delete(paths, progress=lambda f, name: job.set_progress(f, name))

            def done(job, error):
                if job.status == "done":
                    self.toast(f"Deleted {len(paths)} item(s)")
                    self.refresh_all()
                elif error:
                    self.toast(str(error))

            self.jobs.submit("Deleting", worker, done)

        if self.prefs.get("confirm_delete", True):
            dialogs.confirm(self, "Delete permanently?",
                            f"{len(paths)} item(s) will be skipped by the Trash.",
                            "Delete", go, "This cannot be undone.")
        else:
            go()

    def restore_selected(self):
        p = self.active_pane()
        if p is None or p.source_kind != "trash":
            return
        records = [p.trash_records[path] for path in p.selected_paths() if path in p.trash_records]
        if not records:
            return

        def worker(job):
            return trash.restore(records)

        def done(job, error):
            if job.status == "done":
                self.toast(f"Restored {len(job.result or [])} item(s)")
                self.refresh_sidebar()
                self.refresh_all()
            elif error:
                self.toast(str(error))

        self.jobs.submit("Restoring from Trash", worker, done)

    def empty_trash(self):
        def go():
            def worker(job):
                return trash.empty(progress=lambda f, name: job.set_progress(f, name))

            def done(job, error):
                self.toast(f"Trash emptied ({job.result or 0} items)")
                self.refresh_sidebar()
                self.refresh_all()

            self.jobs.submit("Emptying Trash", worker, done)

        dialogs.confirm(self, "Empty the Trash?",
                        "Everything in the Trash will be deleted permanently.",
                        "Empty Trash", go, "This cannot be undone.")

    # -------------------------------------------------------------- create ops
    def new_folder(self):
        p = self.active_pane()
        if p is None:
            return
        folder = p.current_folder()
        if not os.path.isdir(folder):
            self.toast("Open a folder first")
            return
        try:
            path = ops.create_folder(folder, "New Folder")
        except OSError as e:
            self.toast(e.strerror or str(e))
            return
        self.undo_stack.push(undo_mod.CreateAction([path], "New Folder"))
        self.refresh_all()
        p._select_path_soon(path)
        GLib.timeout_add(220, lambda: (p.begin_rename(path), False)[1])

    def create_file(self, folder, name, content=b""):
        try:
            path = ops.create_file(folder, name, content)
        except OSError as e:
            self.toast(e.strerror or str(e))
            return
        self.undo_stack.push(undo_mod.CreateAction([path], "New File"))
        self.refresh_all()
        p = self.active_pane()
        if p:
            p._select_path_soon(path)

    def run_compress(self, paths, dest, fmt):
        def worker(job):
            return ops.compress(paths, dest, fmt, progress=lambda f, name, _: job.set_progress(f, name),
                                cancel=job.cancel_event)

        def done(job, error):
            if job.status == "done":
                self.toast(f"Created {os.path.basename(job.result)}")
                self.refresh_all()
            elif error:
                self.toast(f"Compress failed: {error}")

        self.jobs.submit("Compressing", worker, done)

    def extract_selected(self, ask_dest):
        p = self.active_pane()
        if p is None:
            return
        paths = p.selected_paths()
        if not paths:
            return
        archive = paths[0]
        if not ask_dest:
            self._start_extract(archive, None, True)
            return
        try:
            dlg = Gtk.FileDialog()
            dlg.set_title("Extract to\u2026")
            dlg.set_initial_folder(Gio.File.new_for_path(os.path.dirname(archive)))

            def chosen(d, res):
                try:
                    f = d.select_folder_finish(res)
                except GLib.Error:
                    return
                dest = f.get_path()
                if dest:
                    self._start_extract(archive, dest, False)

            dlg.select_folder(self, None, chosen)
        except Exception as e:
            self.toast(f"Cannot choose folder: {e}")

    def _start_extract(self, archive, dest, into_folder):
        def worker(job):
            return ops.extract(archive, dest, into_folder=into_folder,
                               progress=lambda f, name, _: job.set_progress(f, name),
                               cancel=job.cancel_event)

        def done(job, error):
            if job.status == "done":
                self.toast(f"Extracted to {util.display_name(job.result)}")
                self.refresh_all()
            elif error:
                self.toast(f"Extract failed: {error}")

        self.jobs.submit("Extracting", worker, done)

    # ------------------------------------------------------------- properties
    def show_properties(self, path=None):
        p = self.active_pane()
        if path is None and p:
            path = p.first_selected() or p.current_folder()
            if p.source_kind == "trash" and p.selected_paths():
                path = p.selected_paths()[0]
                rec = p.trash_records.get(path)
                if rec:
                    dialogs.properties_dialog(self, path, rec)
                    return
        if path:
            dialogs.properties_dialog(self, path)

    def star_toggle(self):
        p = self.active_pane()
        if p is None:
            return
        paths = p.selected_paths()
        if not paths:
            st = prefs_mod.load_stars()
            cur = p.current_folder()
            if cur in st:
                st.remove(cur)
                self.toast("Star removed")
            else:
                st.append(cur)
                self.toast("Starred")
            prefs_mod.save_stars(st)
            if p.source_kind == "starred":
                p.navigate("starred://")
            return
        st = prefs_mod.load_stars()
        added = 0
        for path in paths:
            if path in st:
                st.remove(path)
            else:
                st.append(path)
                added += 1
        prefs_mod.save_stars(st)
        self.toast(f"{added} starred, {len(paths) - added} unstarred")
        if p.source_kind == "starred":
            p.navigate("starred://")

    # ------------------------------------------------------------------ misc
    def connect_uri(self, uri):
        try:
            gfile = Gio.File.new_for_uri(uri)
        except Exception:
            self.toast("Invalid address")
            return
        self.toast(f"Connecting to {uri}\u2026")

        def mounted(f, res):
            try:
                f.mount_enclosing_volume_finish(res)
            except GLib.Error as e:
                self.toast(e.message)
                return
            self.open_uri_location(gfile)

        op = Gio.MountOperation()
        op.set_username("")
        try:
            gfile.mount_enclosing_volume(Gio.MountMountFlags.NONE, op, None, mounted)
        except Exception as e:
            self.toast(str(e))

    def open_uri_location(self, gfile):
        path = gfile.get_path()
        if path:
            self.navigate(path)
        else:
            self.toast("Mounted, but no local path is exposed")

    def refresh_all(self):
        for tab in self.tabs:
            for p in tab.panes:
                try:
                    p.refresh()
                except Exception:
                    pass
        self.sync_sidebar()
        self.sync_status()

    # ------------------------------------------------------------------ undo
    def _update_undo(self):
        act = self.lookup_action("undo")
        if act:
            act.set_enabled(self.undo_stack.can_undo())
        act = self.lookup_action("redo")
        if act:
            act.set_enabled(self.undo_stack.can_redo())

    def undo(self):
        action = self.undo_stack.undo()
        if action:
            self.toast(f"Undid: {action.label}")
            self.refresh_all()
            self.refresh_sidebar()

    def redo(self):
        action = self.undo_stack.redo()
        if action:
            self.toast(f"Redid: {action.label}")
            self.refresh_all()
            self.refresh_sidebar()

    # ------------------------------------------------------------------ jobs
    def _on_job_update(self, job):
        active = len(self.jobs.active_jobs())
        self.jobs_btn.set_tooltip_text(
            f"{active} running \u00b7 {len(self.jobs.jobs())} recent" if active else "File operations")
        self._rebuild_jobs_popover()

    def _rebuild_jobs_popover(self):
        box = getattr(self, "_jobs_box", None)
        if box is None:
            return
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt
        box.append(ui.label("File Operations", "title-strong small"))
        any_job = False
        for job in reversed(self.jobs.jobs()):
            any_job = True
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.append(ui.label(job.title, "job-title", ellipsize=2))
            head.append(ui.spacer())
            status = {"queued": "waiting", "running": "", "done": "done",
                      "failed": "failed", "cancelled": "cancelled",
                      "cancelling": "cancelling"}.get(job.status, job.status)
            if status:
                head.append(ui.label(status, "faint small"))
            if job.status in ("queued", "running"):
                cancel = ui.button(icon="process-stop-symbolic", tooltip="Cancel",
                                   css="job-cancel", size=12)
                cancel.connect("clicked", lambda _b, j=job: self.jobs.cancel(j))
                head.append(cancel)
            row.append(head)
            bar = Gtk.ProgressBar()
            bar.set_fraction(job.progress if job.status != "done" else 1.0)
            bar.set_show_text(False)
            row.append(bar)
            meta = []
            if job.status == "running":
                if job.text:
                    meta.append(util.elide_middle(job.text, 30))
                if job.speed:
                    meta.append(util.human_rate(job.speed))
                if job.eta:
                    meta.append("ETA " + util.human_eta(job.eta))
            elif job.status == "failed":
                meta.append(job.error or "failed")
            row.append(ui.label("  \u00b7  ".join(meta), "job-sub", ellipsize=2))
            box.append(row)
        if not any_job:
            box.append(ui.label("No operations yet", "faint small"))
        clear = Gtk.Button(label="Clear finished")
        clear.add_css_class("flat")
        clear.connect("clicked", lambda *_: self._clear_jobs())
        box.append(clear)

    def _clear_jobs(self):
        self.jobs._prune()
        self._rebuild_jobs_popover()

    # ---------------------------------------------------------------- quicklook
    def toggle_quicklook(self):
        p = self.active_pane()
        if p is None:
            return
        path = p.first_selected()
        if not path:
            return
        if self._quick is None:
            self._quick = quicklook.QuickLook(self)
        self._quick.present_path(path)

    def quicklook_step(self, delta):
        p = self.active_pane()
        if p is None or p.model is None:
            return
        bits = p.model.selection.get_selection()
        if not bits.get_size():
            return
        pos = bits.get_nth(0)
        new = max(0, min(p.model.count() - 1, pos + delta))
        p.model.selection.select_item(new, True)
        view = p.grid if p.view_mode == "grid" else p.list
        view.scroll_to(new, Gtk.ListScrollFlags.FOCUS, None)
        path = p.model.path_at(new)
        if path and self._quick is not None:
            self._quick.present_path(path)

    # ------------------------------------------------------------- info boxes
    def show_about(self):
        d = dialogs.GlassDialog(self, "About Glass Files", 460)
        d.body.append(ui.label("Glass Files", "dialog-title", xalign=0.5))
        d.body.append(ui.label(f"Version {util.VERSION}", "faint small", xalign=0.5))
        d.body.append(ui.label(
            "A glass file explorer for Hyprland.\n"
            "GTK4 \u00b7 Python \u00b7 freedesktop Trash \u00b7 FileManager1",
            "dialog-sub", xalign=0.5, wrap=True))
        d.body.append(ui.sep())
        d.body.append(ui.label(f"Home: {util.HOME}", "mono", selectable=True, wrap=True))
        d.add_button("Close", d.close, suggested=True)
        d.present()

    def show_shortcuts(self):
        d = dialogs.GlassDialog(self, "Keyboard Shortcuts", 560)
        rows = [
            ("Ctrl+T", "New tab"), ("Ctrl+W", "Close tab"), ("Ctrl+Tab", "Next tab"),
            ("Ctrl+Shift+T", "Reopen closed tab"), ("Ctrl+Shift+N", "New folder"),
            ("Ctrl+F", "Search"), ("Ctrl+L", "Edit location"), ("Ctrl+H", "Show hidden"),
            ("Ctrl+1/2/3", "Icons / List / Compact"), ("F5", "Refresh"),
            ("F2", "Rename"), ("F3", "Split view"), ("F11", "Preview pane"),
            ("Space", "Quick Look"), ("Del", "Move to Trash"),
            ("Shift+Del", "Delete permanently"), ("Ctrl+Z", "Undo"),
            ("Ctrl+Shift+Z", "Redo"), ("Ctrl+D", "Bookmark"),
            ("Alt+Left/Right", "Back / Forward"), ("Alt+Up", "Up"),
        ]
        grid = Gtk.Grid(row_spacing=4, column_spacing=24)
        for i, (keys, what) in enumerate(rows):
            grid.attach(ui.label(keys, "mono"), 0, i, 1, 1)
            grid.attach(ui.label(what, "small"), 1, i, 1, 1)
        d.body.append(grid)
        d.add_button("Close", d.close, suggested=True)
        d.present()

    # ---------------------------------------------------------------- lifecycle
    def on_pane_navigated(self, pane):
        if self.active_tab and pane is self.active_pane():
            self._last_location = pane.location
            self.sync_breadcrumb()
            self.sync_sidebar()
            self.sync_status()
            self._sync_view_buttons()
            self._sync_zoom(pane.icon_size)
            self._update_nav_buttons()
            self.tabstrip.rebuild()
            self.set_title("Glass Files")

    def on_pane_selection(self, pane):
        if self.active_tab and pane is self.active_pane():
            self.sync_status()

    def on_pane_title(self, pane):
        if pane is (self.active_pane() if self.active_tab else None):
            self.tabstrip.rebuild()

    def after_navigation(self, pane=None):
        self.on_pane_navigated(pane or self.active_pane())

    def _toggle_maximize(self):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def _on_close(self, *args):
        w, h = self.get_width(), self.get_height()
        if not self.is_maximized():
            self.prefs.data["window"] = {"width": w, "height": h,
                                        "maximized": False}
        else:
            self.prefs.data["window"]["maximized"] = True
        self.prefs.save()
        if (getattr(self.app, "_is_service", lambda: False)()
                and self is getattr(self.app, "_prewarm_win", None)):
            # Resident service: keep this window (and the app) alive in the
            # background; the next Super+E just shows it again.
            self.set_visible(False)
            return True
        try:
            self.thumbpool.shutdown()
            self.jobs.shutdown()
            if self._quick is not None:
                self._quick.close()
            if hasattr(self, "monitor") and self.monitor:
                self.monitor.cancel()
        except Exception:
            pass
        return False
