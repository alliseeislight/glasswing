"""One navigation pane: views, selection, context menus, rename, preview.

A tab can hold one or two of these. All filesystem work is delegated to
ops/trash through the window's job queue; the pane never blocks.
"""

from __future__ import annotations

import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import dnd, model, prefs as prefs_mod, search, thumbs, trash, ui, util

THUMB_MIN = 4096


class Pane(Gtk.Box):
    __gsignals__ = {
        "navigated": (0, None, (str,)),
        "selection-changed": (0, None, ()),
        "title-changed": (0, None, (str,)),
        "focus-in": (0, None, ()),
        "toast": (0, None, (str,)),
    }

    def __init__(self, window, location=None, source_kind="dir"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.window = window
        self.prefs = window.prefs
        self.add_css_class("pane")
        self.source_kind = source_kind
        self.location = location or util.HOME
        self.base_path = self.location if source_kind == "dir" else None
        self.history: list[str] = []
        self.hindex = -1
        self.search_results: list[str] = []
        self.search_query = ""
        self.trash_records: dict[str, dict] = {}
        self.starred: list[str] = []
        self._type_buffer = ""
        self._type_timeout = 0
        self._menu_handled = False
        self._thumb_serial = 0

        st = self.prefs.folder_state(self.base_path or "")
        self.view_mode = st.get("view", "grid")
        self.icon_size = int(st.get("icon_size", 112) or 112)
        self.show_hidden = bool(st.get("show_hidden", False))
        self.sort_key = st.get("key", "name")
        self.sort_desc = bool(st.get("desc", False))
        self.folders_first = bool(st.get("folders_first", True))
        self.search_show_hidden = self.show_hidden

        self.set_can_focus(False)
        self.overlay = Gtk.Overlay()
        self.overlay.set_hexpand(True)
        self.overlay.set_vexpand(True)
        self.append(self.overlay)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_hexpand(True)
        self.scroller.set_vexpand(True)
        self.overlay.set_child(self.scroller)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(90)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.scroller.set_child(self.stack)

        self.empty = self._make_empty_state()
        self.empty.set_halign(Gtk.Align.CENTER)
        self.empty.set_valign(Gtk.Align.CENTER)
        self.empty.set_visible(False)
        self.overlay.add_overlay(self.empty)

        self.preview = self._make_preview()
        self.preview.set_visible(bool(self.prefs.get("preview", False)))
        self.append(self.preview)

        self.model = None
        self.grid = None
        self.list = None
        self._columns = []
        self._install_views()

        keys = Gtk.EventControllerKey.new()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        bg = Gtk.GestureClick.new()
        bg.set_button(3)
        bg.connect("pressed", self._on_background_menu)
        self.stack.add_controller(bg)

        self.navigate(self.location if source_kind == "dir" else
                      {"trash": "trash://", "recent": "recent://",
                       "starred": "starred://"}.get(source_kind, util.HOME),
                      add_history=False)

    # ------------------------------------------------------------------ build
    def _make_empty_state(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("empty")
        self._empty_icon = ui.image_icon("folder-open-symbolic", 44)
        self._empty_icon.add_css_class("empty-icon")
        box.append(self._empty_icon)
        self._empty_title = ui.label("", "empty-title", xalign=0.5)
        self._empty_sub = ui.label("", "empty-sub", xalign=0.5, wrap=True)
        self._empty_sub.set_justify(Gtk.Justification.CENTER)
        box.append(self._empty_title)
        box.append(self._empty_sub)
        return box

    def _make_preview(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("preview")
        box.set_size_request(252, -1)
        self._preview_pic = Gtk.Picture()
        self._preview_pic.set_can_shrink(True)
        self._preview_pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        self._preview_pic.set_size_request(220, 150)
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        wrap.append(self._preview_pic)
        box.append(wrap)
        self._preview_title = ui.label("", "preview-title", wrap=True)
        box.append(self._preview_title)
        self._preview_meta = ui.label("", "preview-meta", wrap=True)
        box.append(self._preview_meta)
        self._preview_more = ui.label("", "preview-meta", wrap=True)
        box.append(self._preview_more)
        box.append(ui.spacer())
        return box

    def _install_views(self):
        old_grid, old_list = self.grid, self.list
        self.grid = self._make_grid_view()
        self.list = self._make_list_view()
        for name, view in (("grid", self.grid), ("list", self.list)):
            if self.stack.get_child_by_name(name):
                self.stack.remove(self.stack.get_child_by_name(name))
        self.stack.add_named(self.grid, "grid")
        self.stack.add_named(self.list, "list")
        self._built_icon_size = self.icon_size
        if self.model is not None:
            self.grid.set_model(self.model.selection)
            self.list.set_model(self.model.selection)
        self._apply_view_mode()
        if old_grid is not None:
            old_grid.unparent()
        if old_list is not None:
            old_list.unparent()

    # --------------------------------------------------------------- grid view
    def _cell_width(self):
        return max(84, int(self.icon_size) + 34)

    def _make_grid_view(self):
        view = Gtk.GridView()
        view.set_enable_rubberband(True)
        view.set_single_click_activate(bool(self.prefs.get("single_click", False)))
        view.set_min_columns(1)
        view.add_css_class("glass-grid")
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._grid_setup)
        factory.connect("bind", self._grid_bind)
        factory.connect("unbind", self._grid_unbind)
        view.set_factory(factory)
        view.connect("activate", self._on_grid_activate)
        view.connect("notify::width", self._grid_resize)
        dnd.add_uri_drop_target(view, self._drop_on_background)
        dnd.add_file_drop_target(view, self._drop_on_background)
        return view

    def _grid_resize(self, view, _pspec=None):
        w = view.get_width()
        if w <= 0:
            return
        cols = max(1, int(w / self._cell_width()))
        if view.get_max_columns() != cols:
            view.set_max_columns(cols)

    def _grid_setup(self, factory, list_item):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("item")
        box.set_size_request(self._cell_width(), -1)
        stack = Gtk.Stack()
        stack.set_size_request(int(self.icon_size), int(self.icon_size))
        stack.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image()
        icon.set_pixel_size(max(28, int(self.icon_size * 0.62)))
        pic = Gtk.Picture()
        pic.set_can_shrink(True)
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        stack.add_named(icon, "icon")
        stack.add_named(pic, "thumb")
        stack.set_visible_child_name("icon")
        stack.add_css_class("item-icon")
        box.append(stack)
        lab = ui.label("", "item-label", xalign=0.5, ellipsize=Pango.EllipsizeMode.MIDDLE)
        lab.set_max_width_chars(16)
        lab.set_justify(Gtk.Justification.CENTER)
        box.append(lab)
        meta = ui.label("", "item-meta", xalign=0.5, ellipsize=Pango.EllipsizeMode.END)
        meta.set_visible(False)
        box.append(meta)
        list_item.set_child(box)
        box._glass = {"stack": stack, "icon": icon, "pic": pic, "label": lab, "meta": meta}
        click = Gtk.GestureClick.new()
        click.set_button(3)
        click.connect("pressed", self._on_item_secondary, list_item)
        box.add_controller(click)
        dnd.add_drag_source(box, lambda li=list_item: self._drag_paths(li))
        dnd.add_file_drop_target(box, lambda paths, cut, x, y, li=list_item: self._drop_on_item(li, paths, cut))
        dnd.add_uri_drop_target(box, lambda paths, cut, x, y, li=list_item: self._drop_on_item(li, paths, cut))

    def _grid_bind(self, factory, list_item):
        info = list_item.get_item()
        box = list_item.get_child()
        if info is None or box is None:
            return
        w = box._glass
        path = model.path_of(info, self.base_path)
        name = model.display_of(info, self.base_path)
        w["label"].set_text(name)
        w["label"].set_tooltip_text(name)
        w["icon"].set_from_gicon(model.icon_for(info))
        w["stack"].set_visible_child_name("icon")
        w["pic"].set_paintable(None)
        w["meta"].set_visible(self.view_mode == "compact")
        if self.view_mode == "compact":
            size = model.size_of(info)
            w["meta"].set_text("Folder" if model.is_dir(info) else util.human_size(size))
        thumbcache = model.thumb_of(info)
        if thumbcache:
            tex = thumbs.texture_from_file(thumbcache)
            if tex:
                w["pic"].set_paintable(tex)
                w["stack"].set_visible_child_name("thumb")
        elif path and thumbs.is_thumbnailable(path, model.mime_of(info)):
            try:
                big_enough = model.size_of(info) < 0 or model.size_of(info) > THUMB_MIN
            except Exception:
                big_enough = True
            if big_enough:
                token = (path, w["stack"])
                w["token"] = token
                gen = self._thumb_serial

                def done(p, cache, stack=w["stack"], pic=w["pic"], g=gen, token=token):
                    if g != self._thumb_serial or not stack.get_realized():
                        return
                    if cache and stack.get_visible_child_name() != "thumb":
                        tex = thumbs.texture_from_file(cache)
                        if tex:
                            pic.set_paintable(tex)
                            stack.set_visible_child_name("thumb")

                self.window.thumbpool.request(path, "large", done)
        box.set_tooltip_text(
            f"{name}\n{util.pretty_type(path or '', model.mime_of(info))}"
            + ("" if model.is_dir(info) else f" \u00b7 {util.human_size(model.size_of(info))}")
            + f"\n{util.format_time(model.mtime_of(info))}"
        )
        box._glass_path = path

    def _grid_unbind(self, factory, list_item):
        box = list_item.get_child()
        if box is None:
            return
        box._glass["pic"].set_paintable(None)

    def _drag_paths(self, list_item):
        info = list_item.get_item()
        if info is None:
            return []
        pos = list_item.get_position()
        sel = self.model.selected_items()
        if sel and info in sel:
            return [p for p in (model.path_of(i, self.base_path) for i in sel) if p]
        path = model.path_of(info, self.base_path)
        return [path] if path else []

    def _on_grid_activate(self, view, pos):
        self._activate_pos(pos)

    # --------------------------------------------------------------- list view
    LIST_COLUMNS = [
        ("name", "Name", 260, 0.0, True),
        ("size", "Size", 92, 1.0, False),
        ("modified", "Modified", 150, 0.0, False),
        ("type", "Type", 138, 0.0, False),
        ("permissions", "Permissions", 108, 0.0, False),
        ("owner", "Owner", 108, 0.0, False),
        ("location", "Location", 190, 0.0, False),
    ]

    def _make_list_view(self):
        view = Gtk.ColumnView()
        view.set_show_row_separators(False)
        view.set_show_column_separators(False)
        view.set_reorderable(False)
        view.set_enable_rubberband(True)
        view.connect("activate", lambda v, pos: self._activate_pos(pos))
        view.add_css_class("glass-list")
        self._columns = []
        for key, title, width, xalign, expand in self.LIST_COLUMNS:
            col = Gtk.ColumnViewColumn.new(title, self._make_cell_factory(key, xalign))
            col.set_expand(expand)
            if not expand:
                col.set_fixed_width(width)
            col.set_resizable(True)
            view.append_column(col)
            self._columns.append((col, key))
        header = Gtk.GestureClick.new()
        header.set_button(1)
        header.connect("pressed", self._on_header_click)
        view.add_controller(header)
        dnd.add_uri_drop_target(view, self._drop_on_background)
        dnd.add_file_drop_target(view, self._drop_on_background)
        return view

    def _make_cell_factory(self, key, xalign):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._cell_setup, key, xalign)
        factory.connect("bind", self._cell_bind, key)
        factory.connect("unbind", self._cell_unbind, key)
        return factory

    def _cell_setup(self, factory, list_item, key, xalign):
        if key == "name":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            box.add_css_class("row-cell")
            img = Gtk.Image()
            img.set_pixel_size(18)
            img.add_css_class("row-icon")
            lab = ui.label("", "row-name", xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
            lab.set_hexpand(True)
            box.append(img)
            box.append(lab)
            list_item.set_child(box)
            box._glass = {"icon": img, "label": lab}
            click = Gtk.GestureClick.new()
            click.set_button(3)
            click.connect("pressed", self._on_item_secondary, list_item)
            box.add_controller(click)
            dnd.add_drag_source(box, lambda li=list_item: self._drag_paths(li))
            dnd.add_file_drop_target(box, lambda paths, cut, x, y, li=list_item: self._drop_on_item(li, paths, cut))
            dnd.add_uri_drop_target(box, lambda paths, cut, x, y, li=list_item: self._drop_on_item(li, paths, cut))
        else:
            lab = ui.label("", "row-cell", xalign=xalign, ellipsize=Pango.EllipsizeMode.END)
            if key == "permissions":
                lab.add_css_class("mono")
            list_item.set_child(lab)

    def _cell_bind(self, factory, list_item, key):
        info = list_item.get_item()
        child = list_item.get_child()
        if info is None or child is None:
            return
        path = model.path_of(info, self.base_path)
        if key == "name":
            child._glass["label"].set_text(model.display_of(info, self.base_path))
            child._glass["icon"].set_from_gicon(model.icon_for(info))
            child._glass_path = path
            thumbcache = model.thumb_of(info)
            if thumbcache:
                tex = thumbs.texture_from_file(thumbcache)
                if tex:
                    child._glass["icon"].set_from_paintable(tex)
        elif key == "size":
            if model.is_dir(info):
                child.set_text("\u2014")
            else:
                child.set_text(util.human_size(model.size_of(info)))
        elif key == "modified":
            child.set_text(util.format_time(model.mtime_of(info)))
        elif key == "type":
            child.set_text(util.pretty_type(path or "", model.mime_of(info)))
        elif key == "permissions":
            mode = model.mode_of(info)
            child.set_text(util.perm_string(mode) if mode is not None else "\u2014")
        elif key == "owner":
            uid = model.uid_of(info)
            gid = model.gid_of(info)
            if uid is None:
                child.set_text("\u2014")
            else:
                child.set_text(f"{util.user_name(uid)}:{util.group_name(gid) if gid is not None else '?'}")
        elif key == "location":
            loc = info.get_attribute_string("glass::location") if isinstance(info, Gio.FileInfo) else None
            child.set_text(util.fsdec(loc or "\u2014"))
            child.set_tooltip_text(loc or "")

    def _cell_unbind(self, factory, list_item, key):
        # No per-row state to release here; the item is reused by the factory.
        return

    def _on_header_click(self, gesture, n_press, x, y):
        if y > 34 or not self._columns:
            return
        fixed = sum((c.get_fixed_width() or 0) for c, k in self._columns if c.get_visible() and not c.get_expand())
        expand_count = sum(1 for c, k in self._columns if c.get_visible() and c.get_expand()) or 1
        remaining = max(120, self.list.get_width() - fixed)
        acc = 0.0
        for col, key in self._columns:
            if not col.get_visible():
                continue
            w = remaining / expand_count if col.get_expand() else (col.get_fixed_width() or 120)
            if x < acc + w:
                if self.sort_key == key:
                    self.sort_desc = not self.sort_desc
                else:
                    self.sort_key = key
                    self.sort_desc = False
                self._apply_sort()
                return
            acc += w

    def _update_column_titles(self):
        for col, key in self._columns:
            title = dict((k, t) for k, t, *_ in self.LIST_COLUMNS)[key]
            if key == self.sort_key:
                title += " \u2193" if self.sort_desc else " \u2191"
            col.set_title(title)
        show_loc = self.source_kind in ("search", "trash")
        for col, key in self._columns:
            if key == "location":
                col.set_visible(show_loc)

    # ------------------------------------------------------------------ model
    def _connect_model(self):
        if self.model is None:
            return
        self.model.connect("changed", self._on_model_changed)

    def _load(self, location, keep_history=True):
        self._thumb_serial += 1
        if self.model is not None:
            self.model.stop()
        direct = location
        self.source_kind = "dir"
        self.base_path = direct
        self.search_query = ""
        self.search_results = []
        self.trash_records = {}

        if location == "trash://":
            self.source_kind = "trash"
            self.base_path = None
            recs = trash.list_trash()
            infos = []
            for rec in recs:
                self.trash_records[rec["trashed"]] = rec
                infos.append(model.make_info(
                    rec["trashed"], display=rec["display"], mtime=rec["date"],
                    size=rec["size"] or 0, is_directory=rec["is_dir"],
                    original=rec["original"],
                    location=os.path.dirname(rec["original"]) or "/",
                ))
            self.model = model.PaneModel(None)
            self.model.use_store(infos)
        elif location == "recent://":
            self.source_kind = "recent"
            self.base_path = None
            self.model = model.PaneModel(None)
            self.model.use_store(model.build_recent_infos())
        elif location == "starred://":
            self.source_kind = "starred"
            self.base_path = None
            self.starred = [p for p in prefs_mod.load_stars() if os.path.exists(p)]
            infos = [model.make_info(p) for p in self.starred]
            self.model = model.PaneModel(None)
            self.model.use_store(infos)
        else:
            try:
                gfile = Gio.File.new_for_path(location)
            except Exception:
                gfile = Gio.File.new_for_path(util.HOME)
            self.model = model.PaneModel(location)
            self.model.use_directory(gfile)

        self.location = location
        if self.source_kind == "dir":
            st = self.prefs.folder_state(location)
            self.view_mode = st.get("view", "grid")
            self.icon_size = int(st.get("icon_size", 112) or 112)
            self.show_hidden = bool(st.get("show_hidden", False))
            self.sort_key = st.get("key", "name")
            self.sort_desc = bool(st.get("desc", False))
            self.folders_first = bool(st.get("folders_first", True))
            self._install_views()

        self.model.set_filter(show_hidden=self.show_hidden, query="")
        self.model.set_sort(self.sort_key, self.sort_desc, self.folders_first)
        self._connect_model()
        if self.grid is not None:
            self.grid.set_model(self.model.selection)
        if self.list is not None:
            self.list.set_model(self.model.selection)
        self._update_column_titles()
        self._apply_view_mode()
        self._on_model_changed()
        self._update_preview()
        self.emit("navigated", self.location)
        self.emit("title-changed", self.title())

    def navigate(self, location, add_history=True):
        if isinstance(location, Gio.File):
            p = location.get_path()
            if not p:
                p = util.HOME
            location = p
        location = location or util.HOME
        if location.startswith("file://"):
            location = util.uri_to_path(location) or util.HOME
        if location not in ("trash://", "recent://", "starred://"):
            location = util.expand_path(location)
            if not os.path.exists(location):
                self.emit("toast", f"Not found: {util.elide_middle(location, 70)}")
                return
            if os.path.isfile(location):
                self.window.open_path(location)
                return
        self._load(location)
        if add_history:
            if self.hindex < len(self.history) - 1:
                self.history = self.history[: self.hindex + 1]
            if not self.history or self.history[-1] != location:
                self.history.append(location)
            self.hindex = len(self.history) - 1
        self.window.after_navigation(self)

    def back(self):
        if self.hindex > 0:
            self.hindex -= 1
            self._load(self.history[self.hindex])
            self.window.after_navigation(self)

    def forward(self):
        if self.hindex < len(self.history) - 1:
            self.hindex += 1
            self._load(self.history[self.hindex])
            self.window.after_navigation(self)

    def up(self):
        if self.source_kind != "dir":
            self.navigate(util.HOME)
            return
        parent = os.path.dirname(self.location.rstrip(os.sep)) or "/"
        if parent != self.location:
            self.navigate(parent)

    def refresh(self):
        loc = self.location
        self._load(loc)

    def title(self):
        if self.source_kind == "trash":
            return "Trash"
        if self.source_kind == "recent":
            return "Recent"
        if self.source_kind == "starred":
            return "Starred"
        base = os.path.basename(self.location.rstrip(os.sep))
        if self.location == util.HOME:
            return "Home"
        return util.fsdec(base or "/")

    # --------------------------------------------------------------- handlers
    def _on_model_changed(self, *args):
        self._update_empty()
        self._update_selection_status()
        self.emit("selection-changed")

    def _update_empty(self):
        if self.model is None:
            return
        n = self.model.count()
        loading = self.model.is_loading()
        err = self.model.error()
        if err is not None:
            self._empty_title.set_text("Can't open this folder")
            self._empty_sub.set_text(err.message if hasattr(err, "message") else str(err))
            self.empty.set_visible(True)
            return
        if n == 0 and not loading:
            if self.search_query:
                self._empty_title.set_text(f"No results for \u201c{self.search_query}\u201d")
                self._empty_sub.set_text("Try a different name or a wider search.")
                self._empty_icon.set_from_icon_name("edit-find-symbolic")
            elif self.source_kind == "trash":
                self._empty_title.set_text("Trash is empty")
                self._empty_sub.set_text("Things you delete land here first.")
                self._empty_icon.set_from_icon_name("user-trash-symbolic")
            elif self.source_kind == "starred":
                self._empty_title.set_text("Nothing starred yet")
                self._empty_sub.set_text("Select a file and press Ctrl+D.")
                self._empty_icon.set_from_icon_name("starred-symbolic")
            else:
                self._empty_title.set_text("This folder is empty")
                self._empty_sub.set_text("Drop files here, or press Ctrl+Shift+N.")
                self._empty_icon.set_from_icon_name("folder-open-symbolic")
            self.empty.set_visible(True)
        else:
            self.empty.set_visible(False)

    def _update_selection_status(self):
        self._update_preview()

    # ------------------------------------------------------------- view mode
    def set_view_mode(self, mode: str):
        if mode not in ("grid", "list", "compact"):
            return
        self.view_mode = mode
        self._apply_view_mode()
        if self.source_kind == "dir":
            self.prefs.remember_folder(self.location, view=mode)
        self.prefs.set("view", mode)

    def _apply_view_mode(self):
        if self.stack is None:
            return
        if self.view_mode == "grid":
            self.stack.set_visible_child_name("grid")
        else:
            self.stack.set_visible_child_name("list")
            compact = self.view_mode == "compact"
            for col, key in self._columns:
                if key in ("name", "modified", "location"):
                    col.set_visible(key != "location" or self.source_kind in ("search", "trash"))
                else:
                    col.set_visible(not compact)
            self._update_column_titles()

    def set_icon_size(self, px: int):
        px = max(56, min(256, int(px)))
        if px == self.icon_size:
            return
        self.icon_size = px
        if self.source_kind == "dir":
            self.prefs.remember_folder(self.location, icon_size=px)
        self.prefs.set("icon_size", px)
        if self.view_mode == "grid":
            self._install_views()

    def set_show_hidden(self, show: bool):
        self.show_hidden = bool(show)
        if self.model is not None:
            self.model.set_filter(show_hidden=self.show_hidden)
        if self.source_kind == "dir":
            self.prefs.remember_folder(self.location, show_hidden=self.show_hidden)
        self.prefs.set("show_hidden", self.show_hidden)

    def toggle_hidden(self):
        self.set_show_hidden(not self.show_hidden)

    def set_sort(self, key: str, desc=None, folders_first=None):
        if key not in model.SORT_KEYS:
            return
        if desc is None:
            desc = self.sort_desc if key == self.sort_key else False
        if folders_first is not None:
            self.folders_first = bool(folders_first)
        if key == self.sort_key and desc == self.sort_desc:
            # still persist, click handlers flip explicitly
            pass
        self.sort_key = key
        self.sort_desc = bool(desc)
        self._apply_sort()

    def _apply_sort(self):
        if self.model is not None:
            self.model.set_sort(self.sort_key, self.sort_desc, self.folders_first)
        self._update_column_titles()
        if self.source_kind == "dir":
            self.prefs.remember_folder(self.location, key=self.sort_key,
                                       desc=self.sort_desc,
                                       folders_first=self.folders_first)

    def set_preview(self, show: bool):
        self.preview.set_visible(bool(show))

    # -------------------------------------------------------------- selection
    def selected_infos(self):
        return self.model.selected_items() if self.model else []

    def selected_paths(self):
        if not self.model:
            return []
        return [p for p in (model.path_of(i, self.base_path) for i in self.model.selected_items()) if p]

    def first_selected(self):
        paths = self.selected_paths()
        return paths[0] if paths else None

    def current_folder(self):
        if self.source_kind == "dir":
            return self.location
        return self.base_path or util.HOME

    def _activate_pos(self, pos):
        info = self.model.item(pos) if self.model else None
        if info is None:
            return
        path = model.path_of(info, self.base_path)
        if not path:
            return
        if self.source_kind == "trash":
            self.window.show_properties(path)
            return
        if model.is_dir(info):
            self.navigate(path)
        else:
            self.window.open_path(path)

    # ------------------------------------------------------------------- keys
    def _on_key(self, controller, keyval, keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not (state & Gdk.ModifierType.CONTROL_MASK):
            sel = self.model.selection.get_selection() if self.model else None
            if sel is not None and sel.get_size() == 1:
                self._activate_pos(sel.get_nth(0))
                return True
        if keyval == Gdk.KEY_F2:
            self.begin_rename()
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right,
                      Gdk.KEY_Home, Gdk.KEY_End, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            return False
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK |
                    Gdk.ModifierType.SUPER_MASK):
            return False
        try:
            ch = chr(Gdk.keyval_to_unicode(keyval))
        except Exception:
            return False
        if not ch or not ch.isprintable():
            return False
        now = time.monotonic()
        if now - getattr(self, "_type_last", 0) > 0.9:
            self._type_buffer = ""
        self._type_last = now
        self._type_buffer += ch.casefold()
        if self.model:
            for i in range(self.model.count()):
                name = model.display_of(self.model.item(i), self.base_path).casefold()
                if name.startswith(self._type_buffer):
                    self.model.selection.select_item(i, True)
                    view = self.grid if self.view_mode == "grid" else self.list
                    view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
                    return True
        return False

    # ------------------------------------------------------------------ menus
    def _mark_handled(self):
        self._menu_handled = True
        GLib.timeout_add(120, self._clear_handled)

    def _clear_handled(self):
        self._menu_handled = False
        return False

    def _paths_for_menu(self):
        infos = self.selected_infos()
        paths = [p for p in (model.path_of(i, self.base_path) for i in infos) if p]
        return paths, infos

    def _on_item_secondary(self, gesture, n_press, x, y, list_item):
        self._mark_handled()
        pos = list_item.get_position()
        if self.model and pos >= 0:
            bits = self.model.selection.get_selection()
            if not bits.contains(pos):
                self.model.selection.select_item(pos, True)
        self.show_item_menu(x, y, list_item.get_child())

    def _on_background_menu(self, gesture, n_press, x, y):
        if self._menu_handled:
            self._clear_handled()
            return
        if self.model and self.model.selected_count() and (gesture.get_current_event() is not None):
            # A right click on empty space clears the selection, like a real file manager.
            self.model.selection.unselect_all()
        self.show_background_menu(x, y)

    def show_item_menu(self, x, y, widget=None):
        paths, infos = self._paths_for_menu()
        if not paths:
            return
        many = len(paths) > 1
        entries = []
        if not many:
            entries += [("Open", "win.open"), ("Open With\u2026", "win.open-with")]
            entries += [("Open in New Tab", "win.open-tab"),
                        ("Open in New Window", "win.open-window")]
            if os.path.isdir(paths[0]):
                entries += [("Open in Terminal", "win.open-terminal")]
            entries += [None]
        entries += [("Cut", "win.cut"), ("Copy", "win.copy"), ("Duplicate", "win.duplicate")]
        entries += [None]
        if not many:
            entries += [("Rename", "win.rename")]
        entries += [("Batch Rename\u2026", "win.batch-rename")]
        entries += [None]
        if self.source_kind == "trash":
            entries += [("Restore", "win.restore"), ("Delete Permanently", "win.delete")]
        else:
            entries += [("Move to Trash", "win.trash")]
        if not many:
            ext = os.path.splitext(paths[0])[1].lower()
            if ext in (".zip", ".tar", ".gz", ".xz", ".zst", ".7z", ".bz2", ".rar"):
                entries += [("Extract Here", "win.extract"), ("Extract To\u2026", "win.extract-to")]
            entries += [("Compress\u2026", "win.compress")]
        if self.source_kind != "trash" and any(thumbs.can_rotate(p) for p in paths):
            entries += [None, ("Rotate Left", "win.rotate-left"),
                        ("Rotate Right", "win.rotate-right")]
        entries += [None, ("Copy Path", "win.copy-path"), ("Properties", "win.properties")]
        if self.source_kind == "starred":
            entries += [("Remove Star", "win.star-toggle")]
        else:
            entries += [("Add Star", "win.star-toggle")]
        ui.show_menu(ui.item_menu(entries), self, x, y)

    def show_background_menu(self, x, y):
        entries = [("New Folder", "win.new-folder"), ("New File\u2026", "win.new-file"),
                   ("Paste", "win.paste")]
        if self.source_kind == "trash":
            entries = [("Empty Trash", "win.empty-trash")]
        entries += [(None, None)]
        select_sub = ui.item_menu([
            ("All", "win.select-all"),
            ("Images", "win.select-images"),
            ("Folders", "win.select-folders"),
            ("Files", "win.select-files"),
            (None, None),
            ("Invert Selection", "win.invert-selection"),
        ])
        view_sub = ui.item_menu([("Icons", "win.view-grid"), ("List", "win.view-list"),
                                 ("Compact", "win.view-compact")])
        sort_sub = ui.item_menu([("Name", "win.sort-name"), ("Size", "win.sort-size"),
                                 ("Modified", "win.sort-modified"), ("Type", "win.sort-type"),
                                 ("Extension", "win.sort-extension"), (None, None),
                                 ("Descending", "win.sort-desc-toggle"),
                                 ("Folders First", "win.folders-first-toggle")])
        menu = Gio.Menu()
        sec = Gio.Menu()
        for text, action in entries:
            if action == (None, None):
                menu.append_section(None, sec)
                sec = Gio.Menu()
            else:
                sec.append(text, action)
        menu.append_section(None, sec)
        menu.append_submenu("Select", select_sub)
        menu.append_submenu("View", view_sub)
        menu.append_submenu("Sort", sort_sub)
        menu.append("Show Hidden Files", "win.show-hidden-toggle")
        menu.append("Open Terminal Here", "win.open-terminal-here")
        menu.append("Refresh", "win.refresh")
        menu.append("Properties", "win.properties")
        ui.show_menu(menu, self, x, y)

    # -------------------------------------------------------------- rename
    def begin_rename(self, path=None):
        path = path or self.first_selected()
        if path:
            # The rename dialog is intentionally used for every view. Inline
            # editors inside Gtk.GridView/ColumnView items cannot reliably take
            # keyboard focus, and a failed focus grab made rename look broken.
            self.window.rename_dialog(path)

    def _select_path_soon(self, path):
        def do():
            if self.source_kind == "dir" and os.path.dirname(path) != self.location:
                self.navigate(os.path.dirname(path))
            if self.model:
                for i in range(self.model.count()):
                    if model.path_of(self.model.item(i), self.base_path) == path:
                        self.model.selection.select_item(i, True)
                        view = self.grid if self.view_mode == "grid" else self.list
                        view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)
                        break
            return False

        GLib.timeout_add(160, do)

    # ---------------------------------------------------------------- preview
    def _update_preview(self, path=None):
        if not self.preview.get_visible():
            return
        paths = self.selected_paths()
        if path:
            paths = [path]
        if not paths:
            self._preview_title.set_text("No selection")
            self._preview_meta.set_text("")
            self._preview_more.set_text("")
            self._preview_pic.set_paintable(None)
            return
        if len(paths) > 1:
            total = 0
            folders = 0
            for p in paths:
                if os.path.isdir(p):
                    folders += 1
                else:
                    try:
                        total += os.path.getsize(p)
                    except OSError:
                        pass
            self._preview_title.set_text(f"{len(paths)} items selected")
            self._preview_meta.set_text(f"{folders} folder{'s' if folders != 1 else ''} \u00b7 {util.human_size(total)}")
            self._preview_more.set_text("")
            self._preview_pic.set_paintable(None)
            return
        p = paths[0]
        self._preview_title.set_text(util.display_name(p))
        try:
            st = os.lstat(p)
            mime = util.mime_type(p)
            kind = util.pretty_type(p, mime)
            size = "\u2014" if os.path.isdir(p) else util.human_size(st.st_size)
            self._preview_meta.set_text(f"{kind}\n{size} \u00b7 {util.format_time(st.st_mtime)}")
            self._preview_more.set_text(
                f"{util.perm_string(st.st_mode)} \u00b7 {util.user_name(st.st_uid)}\n"
                f"{os.path.dirname(p)}"
            )
        except OSError:
            self._preview_meta.set_text("Unreadable")
            self._preview_more.set_text("")
        tex = None
        cache = thumbs.existing(p, "large")
        if cache:
            tex = thumbs.texture_from_file(cache)
        if tex is None and thumbs.is_thumbnailable(p):
            def done(pp, cc):
                if cc and self.preview.get_visible():
                    t = thumbs.texture_from_file(cc)
                    if t:
                        self._preview_pic.set_paintable(t)

            self.window.thumbpool.request(p, "large", done)
        self._preview_pic.set_paintable(tex)

    # ------------------------------------------------------------ drag & drop
    def _drop_on_item(self, li, paths, cut, x, y):
        info = li.get_item()
        if info is None:
            return False
        target = model.path_of(info, self.base_path)
        if target and model.is_dir(info):
            self.window.paste_paths(paths, target, cut)
            return True
        return False

    def _drop_on_background(self, paths, cut, x, y):
        if self.source_kind != "dir":
            return False
        self.window.paste_paths(paths, self.location, cut)
        return True

    # ------------------------------------------------------------------ search
    def set_query(self, query: str):
        self.search_query = (query or "").strip()
        if self.source_kind != "dir":
            self._load(self.location)
        if self.model:
            self.model.set_filter(query=self.search_query)
        self._update_empty()

    def run_recursive_search(self, query: str, kinds=None, days=0, size_band=None):
        query = (query or "").strip()
        if not query:
            return
        self.search_query = query
        base = self.current_folder()

        def worker(job):
            paths = search.search(base, query, limit=3000,
                                  show_hidden=self.search_show_hidden,
                                  cancel=job.cancel_event)
            out = []
            for i, p in enumerate(paths):
                if job.cancelled:
                    break
                if search.matches(p, kinds=kinds, days=days, size_band=size_band):
                    out.append(p)
                if i % 200 == 0:
                    job.set_progress((i + 1) / max(1, len(paths)), "searching\u2026")
            return out

        def done(job, error):
            if self.search_query != query:
                return
            if job.status != "done":
                return
            self.show_search_results(job.result or [], query, base)

        self.window.jobs.submit(f"Search \u201c{query}\u201d", worker, done)

    def show_search_results(self, paths, query, base=None):
        self.source_kind = "search"
        self.base_path = None
        self.search_query = query
        self.search_results = list(paths)
        infos = []
        for p in paths:
            try:
                infos.append(model.make_info(p, location=os.path.dirname(p)))
            except Exception:
                continue
        self.model = model.PaneModel(None)
        self.model.use_store(infos)
        self.model.set_filter(show_hidden=True)
        self.model.set_sort(self.sort_key, self.sort_desc, self.folders_first)
        self._connect_model()
        self.grid.set_model(self.model.selection)
        self.list.set_model(self.model.selection)
        self._update_column_titles()
        self._apply_view_mode()
        self._on_model_changed()
        self.emit("title-changed", self.title())
        self.emit("navigated", self.location)

    # -------------------------------------------------------------- utilities
    def set_active(self, active: bool):
        if active:
            self.remove_css_class("pane-inactive")
        else:
            self.add_css_class("pane-inactive")

    def focus_view(self):
        view = self.grid if self.view_mode == "grid" else self.list
        if view:
            view.grab_focus()

    def status_counts(self):
        total = self.model.count() if self.model else 0
        sel = self.model.selected_count() if self.model else 0
        size = 0
        known = True
        for info in self.selected_infos() if self.model else []:
            s = model.size_of(info)
            if s < 0:
                known = False
            else:
                size += s
        return total, sel, size, known
