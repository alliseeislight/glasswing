"""List models: Gtk.DirectoryList for real folders, Gio.ListStore for synthetic views.

Items are Gio.FileInfo in both cases. A synthetic FileInfo carries the full path in
the "glass::path" attribute, so no side tables are needed.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib, GObject, Gtk

from . import util

ATTRS = ",".join([
    "standard::*", "unix::mode", "unix::uid", "unix::gid", "unix::nlink",
    "time::*", "access::*", "thumbnail::path", "thumbnail::failed",
    "id::file", "id::filesystem", "owner::*",
])

SORT_KEYS = ("name", "size", "modified", "type", "extension")

KINDS = {
    "folder": lambda mime, is_dir: is_dir,
    "image": lambda mime, is_dir: mime.startswith("image/"),
    "video": lambda mime, is_dir: mime.startswith("video/"),
    "audio": lambda mime, is_dir: mime.startswith("audio/"),
    "document": lambda mime, is_dir: mime.startswith("text/") or mime in (
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.oasis.opendocument.text",
    ),
    "archive": lambda mime, is_dir: mime in (
        "application/zip", "application/x-tar", "application/gzip",
        "application/x-7z-compressed", "application/x-compressed-tar",
        "application/x-xz", "application/zstd", "application/vnd.rar",
    ) or mime.endswith("compressed-tar"),
}


def path_of(item, base_path: str | None = None) -> str | None:
    if item is None:
        return None
    if isinstance(item, Gio.FileInfo):
        p = item.get_attribute_string("glass::path")
        if p:
            return p
        name = item.get_name()
        if base_path and name:
            return os.path.join(base_path, name)
    return None


def original_of(item) -> str | None:
    if isinstance(item, Gio.FileInfo):
        return item.get_attribute_string("glass::original") or None
    return None


def info_of(item) -> Gio.FileInfo | None:
    return item if isinstance(item, Gio.FileInfo) else None


def display_of(item, base_path=None) -> str:
    if isinstance(item, Gio.FileInfo):
        p = path_of(item, base_path)
        name = item.get_display_name() or item.get_name()
        return util.fsdec(name) if name else util.fsdec(os.path.basename(p or ""))
    return "?"


def is_dir(item) -> bool:
    try:
        return item.get_file_type() == Gio.FileType.DIRECTORY
    except Exception:
        return False


def is_link(item) -> bool:
    try:
        return item.get_is_symlink()
    except Exception:
        return False


def size_of(item) -> int:
    try:
        if item.get_file_type() == Gio.FileType.DIRECTORY:
            return -1
        return int(item.get_size())
    except Exception:
        return 0


def mtime_of(item) -> float:
    try:
        dt = item.get_modification_date_time()
        if dt:
            return dt.to_unix()
    except Exception:
        pass
    try:
        return float(item.get_attribute_uint64("time::modified"))
    except Exception:
        return 0.0


def mime_of(item) -> str:
    try:
        return item.get_content_type() or ""
    except Exception:
        return ""


def mode_of(item):
    try:
        return item.get_attribute_uint32("unix::mode")
    except Exception:
        return None


def uid_of(item):
    try:
        return item.get_attribute_uint32("unix::uid")
    except Exception:
        return None


def gid_of(item):
    try:
        return item.get_attribute_uint32("unix::gid")
    except Exception:
        return None


def thumb_of(item) -> str | None:
    try:
        p = item.get_attribute_byte_string("thumbnail::path")
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass
    return None


def make_info(path: str, *, display=None, mime=None, size=None, mtime=None,
              is_directory=None, original=None, icon=None,
              location=None) -> Gio.FileInfo:
    fi = Gio.FileInfo()
    name = os.path.basename(path.rstrip(os.sep)) or path
    if is_directory is None:
        try:
            is_directory = os.path.isdir(path) and not os.path.islink(path)
        except OSError:
            is_directory = False
    if display is None:
        display = util.fsdec(name)
    if mime is None:
        mime = "inode/directory" if is_directory else util.mime_type(path)
    if size is None:
        try:
            st = os.lstat(path)
            size = st.st_size
            if mtime is None:
                mtime = st.st_mtime
        except OSError:
            size = 0
    fi.set_attribute_string("glass::path", path)
    fi.set_attribute_string("standard::name", name)
    fi.set_attribute_string("standard::display-name", display)
    fi.set_attribute_string("standard::content-type", mime)
    fi.set_attribute_uint64("standard::size", int(size or 0))
    fi.set_attribute_uint64("time::modified", int(mtime or 0))
    fi.set_attribute_uint32("time::modified-usec", int(((mtime or 0) % 1) * 1_000_000))
    fi.set_file_type(Gio.FileType.DIRECTORY if is_directory else Gio.FileType.REGULAR)
    if original:
        fi.set_attribute_string("glass::original", original)
    if location is None:
        location = os.path.dirname(path)
    fi.set_attribute_string("glass::location", location)
    if icon is None:
        icon = Gio.content_type_get_icon(mime)
        if is_directory:
            icon = Gio.ThemedIcon.new("folder")
    fi.set_attribute_object("standard::icon", icon)
    return fi


def icon_for(item, fallback="text-x-generic"):
    try:
        ic = item.get_icon()
        if ic is not None:
            return ic
    except Exception:
        pass
    return Gio.ThemedIcon.new(fallback)


def _cmp(a, b):
    if a < b:
        return Gtk.Ordering.SMALLER
    if a > b:
        return Gtk.Ordering.LARGER
    return Gtk.Ordering.EQUAL


class PaneModel(GObject.Object):
    """Directory / synthetic list + filter + sort + selection, all live."""

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, base_path: str | None = None):
        super().__init__()
        self.base_path = base_path
        self.directory = None
        self.store = None
        self.filter_model = None
        self.sort_model = None
        self.selection = None
        self._filter = None
        self._sorter = None
        self._show_hidden = False
        self._query = ""
        self._kinds = None
        self._days = 0
        self._size_band = None
        self._sort_key = "name"
        self._sort_desc = False
        self._folders_first = True
        self._reset()

    # -- construction ------------------------------------------------------
    def _reset(self):
        old_sel = self.selection
        self._filter = Gtk.CustomFilter.new(self._match)
        self._sorter = Gtk.CustomSorter.new(self._compare)
        src = self.directory if self.directory is not None else self.store
        self.filter_model = Gtk.FilterListModel.new(src, self._filter)
        self.sort_model = Gtk.SortListModel.new(self.filter_model, self._sorter)
        self.selection = Gtk.MultiSelection.new(self.sort_model)
        self.selection.connect("selection-changed", lambda *_: self.emit("changed"))

    def use_directory(self, gfile: Gio.File):
        self.directory = Gtk.DirectoryList.new(ATTRS)
        self.directory.set_file(gfile)
        self.directory.set_monitored(True)
        self.directory.set_io_priority(GLib.PRIORITY_DEFAULT)
        self.base_path = gfile.get_path()
        self.store = None
        self.directory.connect("items-changed", lambda *_: self.emit("changed"))
        self.directory.connect("notify::loading", lambda *_: self.emit("changed"))
        self._reset()
        self.emit("changed")
        return self.selection

    def use_store(self, infos, base_path=None):
        self.store = Gio.ListStore.new(Gio.FileInfo)
        for info in infos:
            self.store.append(info)
        self.base_path = base_path
        self.directory = None
        self._reset()
        self.emit("changed")
        return self.selection

    def stop(self):
        if self.directory is not None:
            self.directory.set_monitored(False)
        self.directory = None
        self.store = None

    # -- filtering ---------------------------------------------------------
    def set_filter(self, *, show_hidden=None, query=None, kinds=None, days=None,
                   size_band=None):
        if show_hidden is not None:
            self._show_hidden = show_hidden
        if query is not None:
            self._query = query
        if kinds is not None:
            self._kinds = kinds or None
        if days is not None:
            self._days = days
        if size_band is not None:
            self._size_band = size_band
        if self._filter is not None:
            self._filter.changed(Gtk.FilterChange.DIFFERENT)
        self.emit("changed")

    def _match(self, item, *args) -> bool:
        name = display_of(item, self.base_path)
        if not self._show_hidden and name.startswith("."):
            return False
        q = self._query.casefold().strip()
        if q and q not in name.casefold():
            return False
        if self._kinds:
            mime = mime_of(item)
            d = is_dir(item)
            if not any(KINDS.get(k, lambda m, x: False)(mime, d) for k in self._kinds):
                return False
        if self._days:
            import time as _t

            if _t.time() - mtime_of(item) > self._days * 86400:
                return False
        if self._size_band:
            limit = size_of(item)
            if limit < 0:
                return False
            lo, hi = self._size_band
            if lo is not None and limit < lo:
                return False
            if hi is not None and limit > hi:
                return False
        return True

    # -- sorting -----------------------------------------------------------
    def set_sort(self, key: str, descending: bool, folders_first: bool = True):
        self._sort_key = key if key in SORT_KEYS else "name"
        self._sort_desc = bool(descending)
        self._folders_first = bool(folders_first)
        if self.sort_model is not None:
            # CustomSorter has no "changed"; swap in a fresh comparator.
            self._sorter = Gtk.CustomSorter.new(self._compare)
            self.sort_model.set_sorter(self._sorter)
        self.emit("changed")

    def sort_key(self):
        return self._sort_key

    def sort_desc(self):
        return self._sort_desc

    def _key(self, item):
        name = display_of(item, self.base_path)
        key = self._sort_key
        if key == "size":
            return (size_of(item), name.casefold())
        if key == "modified":
            return (mtime_of(item), name.casefold())
        if key == "type":
            return (mime_of(item), name.casefold())
        if key == "extension":
            return (os.path.splitext(name)[1].casefold(), name.casefold())
        return (util.entry_key(name),)

    def _compare(self, a, b, *args):
        if a is b:
            return Gtk.Ordering.EQUAL
        da, db = is_dir(a), is_dir(b)
        if self._folders_first and da != db:
            return Gtk.Ordering.SMALLER if da else Gtk.Ordering.LARGER
        ka, kb = self._key(a), self._key(b)
        res = _cmp(ka, kb)
        if res == Gtk.Ordering.EQUAL:
            res = _cmp(display_of(a, self.base_path).casefold(),
                       display_of(b, self.base_path).casefold())
        if self._sort_desc and res != Gtk.Ordering.EQUAL:
            res = Gtk.Ordering.LARGER if res == Gtk.Ordering.SMALLER else Gtk.Ordering.SMALLER
        return res

    # -- convenience -------------------------------------------------------
    def count(self) -> int:
        return self.sort_model.get_n_items() if self.sort_model else 0

    def item(self, pos: int):
        try:
            return self.sort_model.get_item(pos)
        except Exception:
            return None

    def selected_items(self) -> list:
        if self.selection is None:
            return []
        bits = self.selection.get_selection()
        out = []
        for i in range(bits.get_size()):
            pos = bits.get_nth(i)
            it = self.item(pos)
            if it is not None:
                out.append(it)
        return out

    def selected_count(self) -> int:
        return self.selection.get_selection().get_size() if self.selection else 0

    def path_at(self, pos: int):
        it = self.item(pos)
        return path_of(it, self.base_path) if it is not None else None

    def is_loading(self) -> bool:
        try:
            return bool(self.directory and self.directory.is_loading())
        except Exception:
            return False

    def error(self):
        try:
            return self.directory.get_error() if self.directory else None
        except Exception:
            return None


def build_recent_infos(limit: int = 80) -> list[Gio.FileInfo]:
    infos = []
    try:
        manager = Gtk.RecentManager.get_default()
        items = manager.get_items()
    except Exception:
        return infos
    for item in items[:limit]:
        try:
            uri = item.get_uri()
            path = util.uri_to_path(uri)
            if not path or not os.path.exists(path):
                continue
            mtime = 0
            try:
                mtime = item.get_modified().get_seconds() if item.get_modified() else 0
            except Exception:
                mtime = 0
            infos.append(make_info(
                path,
                display=item.get_display_name() or util.fsdec(os.path.basename(path)),
                mime=item.get_mime_type() or None,
                mtime=mtime or None,
            ))
        except Exception:
            continue
    return infos
