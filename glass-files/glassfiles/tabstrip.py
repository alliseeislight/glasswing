"""Glass tab strip: click, close, reorder by drag, move between windows."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from . import ui

TAB_MIME = "application/x-glass-tab"


class TabStrip(Gtk.Box):
    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.window = window
        self.add_css_class("tabstrip")
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_hexpand(True)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.scroller.set_child(self.rows)
        self.append(self.scroller)
        self.add_btn = ui.button(icon="list-add-symbolic", tooltip="New tab (Ctrl+T)",
                                 css="tab-add", size=14)
        self.add_btn.connect("clicked", lambda *_: self.window.new_tab())
        self.append(self.add_btn)
        self.set_size_request(-1, 38)

    def rebuild(self):
        child = self.rows.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.rows.remove(child)
            child = nxt
        for idx, tab in enumerate(self.window.tabs):
            btn = self._make_tab(tab, idx)
            self.rows.append(btn)
        self.add_btn.set_visible(True)

    def _make_tab(self, tab, idx):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.add_css_class("tab")
        if tab is self.window.active_tab:
            box.add_css_class("tab-active")
        box.set_tooltip_text(tab.tooltip())
        dot = ui.label("\u25cf", "tab-dot small")
        box.append(dot)
        title = ui.label(tab.title(), "tab-title", ellipsize=2)
        title.set_max_width_chars(22)
        box.append(title)
        close = Gtk.Button()
        close.add_css_class("tab-close")
        close.set_child(ui.image_icon("window-close-symbolic", 12))
        close.set_tooltip_text("Close tab")
        close.connect("clicked", lambda *_: self.window.close_tab(tab))
        box.append(close)

        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("pressed", lambda g, n, x, y, t=tab: self._on_tab_click(g, n, t))
        box.add_controller(click)

        right = Gtk.GestureClick.new()
        right.set_button(3)
        right.connect("pressed", lambda g, n, x, y, t=tab, b=box: self._on_tab_menu(g, t, b, x, y))
        box.add_controller(right)

        source = Gtk.DragSource.new()
        source.set_actions(Gdk.DragAction.MOVE)

        def prepare(src, x, y, t=tab):
            self.window._drag_tab = t
            return Gdk.ContentProvider.new_for_bytes(
                TAB_MIME, GLib.Bytes.new(str(id(t)).encode()))

        source.connect("prepare", prepare)
        box.add_controller(source)

        target = Gtk.DropTargetAsync.new(
            Gdk.ContentFormats.new([TAB_MIME]), Gdk.DragAction.MOVE)

        def accept(t, drop):
            return True

        def drag_enter(t, drop, x, y):
            return Gdk.DragAction.MOVE

        def drop(t, gdkdrop, x, y, dst=tab):
            src = getattr(self.window, "_drag_tab", None)
            if src is not None and src is not dst:
                self.window.move_tab(src, dst)
            self.window._drag_tab = None
            try:
                gdkdrop.finish(Gdk.DragAction.MOVE)
            except Exception:
                pass
            return True

        target.connect("accept", accept)
        target.connect("drag-enter", drag_enter)
        target.connect("drop", drop)
        box.add_controller(target)
        return box

    def _on_tab_click(self, gesture, n_press, tab):
        if gesture.get_current_button() == 1:
            self.window.activate_tab(tab)
            if n_press == 3:
                self.window.close_tab(tab)

    def _on_tab_menu(self, gesture, tab, widget, x, y):
        pop = Gtk.Popover()
        pop.set_has_arrow(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        def add(text, fn):
            b = Gtk.Button(label=text)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b: (pop.popdown(), fn()))
            box.append(b)

        add("Close Tab", lambda: self.window.close_tab(tab))
        add("Close Other Tabs", lambda: self.window.close_other_tabs(tab))
        add("Duplicate Tab", lambda: self.window.duplicate_tab(tab))
        box.append(ui.sep())
        add("Move to New Window", lambda: self.window.detach_tab(tab))
        pop.set_child(box)
        pop.set_parent(widget)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        pop.set_pointing_to(rect)
        pop.popup()
