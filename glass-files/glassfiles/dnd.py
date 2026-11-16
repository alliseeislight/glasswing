"""Clipboard and drag-and-drop plumbing (GDK only)."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk

from . import util

GNOME_COPIED = "x-special/gnome-copied-files"

# Internal drags remember their own mode; external drops are copies.
_drag_payload = {"paths": [], "cut": False}


def uri_payload(paths, cut=False):
    lines = "\r\n".join(util.path_to_uri(p) for p in paths) + "\r\n"
    text = ("cut\n" if cut else "copy\n") + lines
    return lines, text


def provider_for(paths, cut=False):
    lines, text = uri_payload(paths, cut)
    files = Gdk.FileList.new_from_array([Gio.File.new_for_path(p) for p in paths])
    providers = [
        Gdk.ContentProvider.new_for_value(files),
        Gdk.ContentProvider.new_for_bytes(GNOME_COPIED, GLib.Bytes.new(text.encode("utf-8"))),
        Gdk.ContentProvider.new_for_bytes("text/uri-list", GLib.Bytes.new(lines.encode("utf-8"))),
        Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8",
                                          GLib.Bytes.new(lines.encode("utf-8"))),
    ]
    return Gdk.ContentProvider.new_union(providers)


def clipboard():
    display = Gdk.Display.get_default()
    return display.get_clipboard() if display else None


def set_clipboard(paths, cut=False):
    clip = clipboard()
    if not clip or not paths:
        return
    clip.set_content(provider_for(paths, cut))


def _parse_payload(data: bytes):
    text = data.decode("utf-8", "replace")
    cut = False
    uris = []
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low in ("copy", "cut"):
            cut = low == "cut"
            continue
        if s.startswith("file://") or s.startswith("/"):
            p = util.uri_to_path(s) if s.startswith("file://") else s
            if p:
                uris.append(p)
    return uris, cut


def read_clipboard(callback):
    """callback(paths, cut) on the main loop."""
    clip = clipboard()
    if clip is None:
        callback([], False)
        return
    formats = clip.get_formats()
    mimes = [GNOME_COPIED, "text/uri-list", "text/plain"]
    mimes = [m for m in mimes if formats.contain_mime_type(m)]
    if not mimes:
        callback([], False)
        return

    def got_stream(clip_, result):
        try:
            stream, _mime_type = clip_.read_finish(result)
        except GLib.Error:
            callback([], False)
            return

        def got_bytes(stream_, result_):
            try:
                gbytes = stream_.read_bytes_finish(result_)
                data = gbytes.get_data() if gbytes else b""
            except GLib.Error:
                data = b""
            callback(*_parse_payload(data or b""))

        stream.read_bytes_async(65536, GLib.PRIORITY_DEFAULT, None, got_bytes)

    try:
        clip.read_async(mimes, GLib.PRIORITY_DEFAULT, None, got_stream)
    except Exception:
        callback([], False)


def add_drag_source(widget: Gtk.Widget, get_paths, get_cut=None, on_begin=None):
    """Make a widget draggable. get_paths() -> list[str]."""
    source = Gtk.DragSource.new()
    source.set_actions(Gdk.DragAction.COPY | Gdk.DragAction.MOVE | Gdk.DragAction.LINK)

    def prepare(src, x, y):
        paths = [p for p in (get_paths() or []) if p]
        # Drop our own bookkeeping from any previous drag.
        _drag_payload["paths"] = list(paths)
        _drag_payload["cut"] = bool(get_cut()) if get_cut else False
        if not paths:
            return None
        return provider_for(paths, _drag_payload["cut"])

    def begin(src, drag):
        if on_begin:
            on_begin(drag)

    source.connect("prepare", prepare)
    source.connect("drag-begin", begin)
    widget.add_controller(source)
    return source


def internal_payload():
    return dict(_drag_payload)


def add_file_drop_target(widget: Gtk.Widget, on_drop):
    """on_drop(paths, cut, x, y) -> bool. Accepts files from any app."""
    target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY | Gdk.DragAction.MOVE |
                                Gdk.DragAction.LINK)

    def drop(t, value, x, y):
        try:
            files = value.get_files()
            paths = [f.get_path() for f in files if f.get_path()]
        except Exception:
            paths = []
        if not paths:
            return False
        internal = internal_payload()
        cut = bool(internal.get("cut")) and set(internal.get("paths", [])) == set(paths)
        try:
            return bool(on_drop(paths, cut, x, y))
        except Exception:
            return False

    def motion(t, x, y):
        return Gdk.DragAction.COPY

    target.connect("drop", drop)
    target.connect("motion", motion)
    widget.add_controller(target)
    return target


def add_uri_drop_target(widget: Gtk.Widget, on_drop):
    """Second chance target: some apps only offer text/uri-list."""
    target = Gtk.DropTarget.new(str, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)

    def drop(t, value, x, y):
        paths, cut = _parse_payload(str(value).encode("utf-8"))
        if not paths:
            return False
        try:
            return bool(on_drop(paths, cut, x, y))
        except Exception:
            return False

    target.connect("drop", drop)
    widget.add_controller(target)
    return target
