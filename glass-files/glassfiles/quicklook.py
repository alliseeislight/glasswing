"""Quick Look: a floating glass preview on Space."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import ops, thumbs, ui, util

MAX_TEXT = 400_000


class QuickLook(Gtk.Window):
    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=False, decorated=False)
        self.parent_window = parent
        self.set_title("Glass Files \u2014 Quick Look")
        self.set_default_size(760, 580)
        self.add_css_class("dialog")
        self.add_css_class("glass-window")
        self._path = None
        self._serial = 0
        self._media = None

        handle = Gtk.WindowHandle()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.add_css_class("dialog-glass")
        root.add_css_class("ql")
        handle.set_child(root)
        self.set_child(handle)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.set_margin_start(18)
        head.set_margin_end(12)
        head.set_margin_top(12)
        self._title = ui.label("", "ql-title", ellipsize=2)
        self._title.set_hexpand(True)
        head.append(self._title)
        close = ui.button(icon="window-close-symbolic", tooltip="Close (Space)", css="win-btn", size=13)
        close.connect("clicked", lambda *_: self.hide())
        head.append(close)
        root.append(head)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(80)
        self.stack.set_vexpand(True)
        self.stack.set_margin_start(14)
        self.stack.set_margin_end(14)
        self.stack.set_hexpand(True)
        root.append(self.stack)

        pic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.picture = Gtk.Picture()
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.set_vexpand(True)
        pic_box.append(self.picture)
        self.stack.add_named(pic_box, "image")

        self.video = Gtk.Video()
        self.video.set_autoplay(True)
        self.video.set_vexpand(True)
        self.video.set_halign(Gtk.Align.FILL)
        self.stack.add_named(self.video, "video")

        self.text_scroll = Gtk.ScrolledWindow()
        self.text_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(False)
        self.text.add_css_class("ql-text")
        self.text.set_wrap_mode(Gtk.WrapMode.NONE)
        self.text_scroll.set_child(self.text)
        self.stack.add_named(self.text_scroll, "text")

        self.list_scroll = Gtk.ScrolledWindow()
        self.list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.archive_list = Gtk.ListBox()
        self.archive_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.archive_list.add_css_class("ql-text")
        self.list_scroll.set_child(self.archive_list)
        self.stack.add_named(self.list_scroll, "archive")

        other = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        other.set_valign(Gtk.Align.CENTER)
        other.set_halign(Gtk.Align.CENTER)
        self.other_icon = ui.image_icon("text-x-generic-symbolic", 72)
        other.append(self.other_icon)
        self.other_text = ui.label("", "empty-sub", wrap=True, xalign=0.5)
        other.append(self.other_text)
        self.stack.add_named(other, "other")

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        foot.set_margin_start(18)
        foot.set_margin_end(18)
        foot.set_margin_bottom(12)
        self.meta = ui.label("", "ql-meta", ellipsize=2)
        self.meta.set_hexpand(True)
        foot.append(self.meta)
        self.hint = ui.label("Space / Esc to close   \u2190 \u2192 next file", "ql-meta")
        foot.append(self.hint)
        root.append(foot)

        keys = Gtk.EventControllerKey.new()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_key(self, c, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        if keyval in (Gdk.KEY_space, Gdk.KEY_q):
            self.hide()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.parent_window.quicklook_step(-1 if keyval == Gdk.KEY_Left else 1)
            return True
        return False

    def present_path(self, path: str):
        if not path:
            return
        self._path = path
        self._serial += 1
        serial = self._serial
        name = util.display_name(path)
        self._title.set_text(name)
        self._title.set_tooltip_text(path)
        try:
            st = os.lstat(path)
            size = "\u2014" if os.path.isdir(path) else util.human_size(st.st_size)
            self.meta.set_text(
                f"{util.pretty_type(path)}   \u00b7   {size}   \u00b7   {util.format_time(st.st_mtime)}"
            )
        except OSError:
            self.meta.set_text("")
        self._title.set_text(name)

        is_dir = os.path.isdir(path)
        mime = "inode/directory" if is_dir else util.mime_type(path)
        ext = os.path.splitext(path)[1].lower()

        if is_dir:
            self.stack.set_visible_child_name("other")
            self.other_icon.set_from_icon_name("folder-symbolic")
            self.other_text.set_text("Folder")

            def count():
                try:
                    n = sum(1 for _ in os.scandir(path))
                except OSError:
                    n = 0

                def show():
                    if serial == self._serial:
                        self.other_text.set_text(
                            f"{n} item{'s' if n != 1 else ''}\n\n{path}")
                    return False

                GLib.idle_add(show)

            import threading

            threading.Thread(target=count, daemon=True).start()
        elif mime.startswith("image/"):
            self.stack.set_visible_child_name("image")
            self.picture.set_paintable(None)
            cache = thumbs.existing(path, "x-large") or thumbs.existing(path, "large")
            if cache:
                self.picture.set_paintable(thumbs.texture_from_file(cache))
                if serial == self._serial:
                    return
            self.parent_window.thumbpool.request(
                path, "x-large",
                lambda p, c: self._set_picture(c, serial))
        elif mime.startswith("video/"):
            self.stack.set_visible_child_name("video")
            try:
                media = Gtk.MediaFile.new_for_filename(path)
                self.video.set_media_stream(media)
                media.set_playing(True)
                self._media = media
            except Exception:
                self.stack.set_visible_child_name("other")
                self.other_icon.set_from_icon_name("video-x-generic-symbolic")
                self.other_text.set_text("Video")
        elif mime.startswith("audio/"):
            self.stack.set_visible_child_name("other")
            self.other_icon.set_from_icon_name("audio-x-generic-symbolic")
            self.other_text.set_text("Audio \u2014 use your player")
        elif ext == ".pdf" or mime == "application/pdf":
            self.stack.set_visible_child_name("image")
            self.picture.set_paintable(None)
            self.parent_window.thumbpool.request(
                path, "x-large",
                lambda p, c: self._set_picture(c, serial, "application-pdf-symbolic"))
        elif util.is_text_like(path, mime):
            self.stack.set_visible_child_name("text")
            self._load_text(path, serial)
        elif ext in (".zip", ".tar", ".gz", ".xz", ".zst", ".7z", ".bz2", ".rar", ".jar"):
            self.stack.set_visible_child_name("archive")
            self._load_archive(path, serial)
        else:
            self.stack.set_visible_child_name("other")
            icon = Gio.content_type_get_icon(mime)
            try:
                self.other_icon.set_from_gicon(icon)
            except Exception:
                self.other_icon.set_from_icon_name("text-x-generic-symbolic")
            self.other_text.set_text(util.pretty_type(path, mime))

        self.show()
        self.present()

    def _set_picture(self, cache, serial, fallback_icon=None):
        if serial != self._serial:
            return
        if cache:
            tex = thumbs.texture_from_file(cache)
            if tex:
                self.picture.set_paintable(tex)
                return
        self.stack.set_visible_child_name("other")
        self.other_icon.set_from_icon_name(fallback_icon or "image-x-generic-symbolic")
        self.other_text.set_text("No preview")

    def _load_text(self, path, serial):
        buf = self.text.get_buffer()
        buf.set_text("loading\u2026")

        def work():
            try:
                with open(path, "rb") as f:
                    data = f.read(MAX_TEXT)
                text = data.decode("utf-8", "replace")
            except OSError as e:
                text = f"Cannot read: {e.strerror}"

            def show():
                if serial != self._serial:
                    return False
                buf.set_text(text)
                return False

            GLib.idle_add(show)

        import threading

        threading.Thread(target=work, daemon=True).start()

    def _load_archive(self, path, serial):
        self._clear_list()
        self.archive_list.append(ui.label("reading archive\u2026", "faint small"))

        def work():
            try:
                names = ops.list_archive(path, limit=300)
                err = None
            except Exception as e:
                names, err = [], str(e)

            def show():
                if serial != self._serial:
                    return False
                self._clear_list()
                if err:
                    self.archive_list.append(ui.label(err, "error small", wrap=True))
                    return False
                for n in names:
                    lab = ui.label(util.fsdec(n), "small", ellipsize=Pango.EllipsizeMode.MIDDLE)
                    lab.set_margin_start(6)
                    lab.set_margin_end(6)
                    self.archive_list.append(lab)
                return False

            GLib.idle_add(show)

        import threading

        threading.Thread(target=work, daemon=True).start()

    def _clear_list(self):
        child = self.archive_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.archive_list.remove(child)
            child = nxt

    def close_media(self):
        try:
            if self._media is not None:
                self._media.set_playing(False)
        except Exception:
            pass
        self._media = None

    def hide(self):
        self.close_media()
        super().hide()
