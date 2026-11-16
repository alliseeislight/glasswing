"""Glass dialogs: rename, batch rename, properties, open with, compress,
preferences, connect-to-server, new file, conflicts."""

from __future__ import annotations

import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import ops, prefs as prefs_mod, thumbs, ui, util

DIALOG_PREFIX = "Glass Files \u2014 "


class GlassDialog(Gtk.Window):
    def __init__(self, parent, title, width=440):
        super().__init__(transient_for=parent, modal=True, decorated=False,
                         destroy_with_parent=True)
        self.set_title(DIALOG_PREFIX + title)
        self.set_default_size(width, -1)
        self.add_css_class("dialog")
        self.add_css_class("glass-window")
        self.set_resizable(False)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("dialog-glass")
        handle = Gtk.WindowHandle()
        handle.set_child(root)
        self.set_child(handle)
        self.root = root
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.set_margin_start(18)
        head.set_margin_end(12)
        head.set_margin_top(14)
        head.set_margin_bottom(6)
        self.title_label = ui.label(title, "dialog-title")
        self.title_label.set_hexpand(True)
        head.append(self.title_label)
        close = ui.button(icon="window-close-symbolic", tooltip="Close", css="win-btn", size=13)
        close.connect("clicked", lambda *_: self.close())
        head.append(close)
        root.append(head)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.body.set_margin_start(18)
        self.body.set_margin_end(18)
        self.body.set_margin_bottom(14)
        root.append(self.body)
        self.buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.buttons.set_halign(Gtk.Align.END)
        self.buttons.set_margin_top(4)
        self.body.append(self.buttons)

    def add_button(self, text, fn, suggested=False, destructive=False):
        b = Gtk.Button(label=text)
        b.add_css_class("btn")
        if suggested:
            b.add_css_class("suggested")
        if destructive:
            b.add_css_class("destructive")
        b.connect("clicked", lambda _b: fn())
        self.buttons.append(b)
        return b

    def present(self):
        super().present()
        return self


def confirm(parent, title, message, destructive_word, on_confirm, subtitle=""):
    d = GlassDialog(parent, title, 420)
    d.body.append(ui.label(message, "dialog-sub", wrap=True))
    if subtitle:
        d.body.append(ui.label(subtitle, "faint small", wrap=True))
    d.add_button("Cancel", d.close)
    d.add_button(destructive_word, lambda: (on_confirm(), d.close()), destructive=True)
    return d.present()


# ------------------------------------------------------------------- rename --
def rename_dialog(window, path):
    d = GlassDialog(window, "Rename", 420)
    entry = Gtk.Entry()
    entry.add_css_class("field")
    entry.set_text(os.path.basename(path.rstrip(os.sep)))
    d.body.append(entry)
    err = ui.label("", "error small")
    d.body.append(err)

    def go():
        try:
            window.do_rename(path, entry.get_text())
        except Exception as e:
            err.set_text(str(e))
            return
        d.close()

    entry.connect("activate", lambda *_: go())
    d.add_button("Cancel", d.close)
    d.add_button("Rename", go, suggested=True)
    d.present()
    entry.grab_focus()
    entry.select_region(0, len(entry.get_text()))
    return d


# -------------------------------------------------------------- batch rename --
def batch_rename_dialog(window, paths):
    paths = [p for p in paths if p]
    if not paths:
        return
    d = GlassDialog(window, f"Batch Rename ({len(paths)})", 560)
    grid = Gtk.Grid(row_spacing=8, column_spacing=10)
    grid.set_column_homogeneous(False)
    d.body.append(grid)

    def add_row(r, text, widget):
        grid.attach(ui.label(text, "dim"), 0, r, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, r, 1, 1)

    pattern = Gtk.Entry()
    pattern.add_css_class("field")
    pattern.set_text("{name}")
    pattern.set_tooltip_text("{name} original name, {ext} extension, {n} counter, {date}")
    add_row(0, "Pattern", pattern)
    find = Gtk.Entry()
    find.add_css_class("field")
    add_row(1, "Find", find)
    replace = Gtk.Entry()
    replace.add_css_class("field")
    add_row(2, "Replace", replace)
    start = Gtk.SpinButton.new_with_range(1, 99999, 1)
    start.set_value(1)
    start.add_css_class("field")
    add_row(3, "Start at", start)

    preview = Gtk.ListBox()
    preview.add_css_class("preview-list")
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_min_content_height(170)
    sw.set_child(preview)
    d.body.append(ui.label("Preview", "faint small"))
    d.body.append(sw)

    def compute():
        import datetime

        pat = pattern.get_text()
        f = find.get_text()
        r = replace.get_text()
        n = int(start.get_value())
        out = []
        for p in paths:
            base = os.path.basename(p.rstrip(os.sep))
            stem, ext = os.path.splitext(base)
            work = stem
            if f:
                work = work.replace(f, r)
            name = (pat.replace("{name}", work).replace("{ext}", ext.lstrip("."))
                       .replace("{n}", str(n)).replace("{date}", datetime.date.today().isoformat()))
            if "{ext}" not in pat and ext:
                name += ext
            out.append((p, name))
            n += 1
        return out

    def refresh(*_):
        child = preview.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            preview.remove(child)
            child = nxt
        for old, new in compute()[:60]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_margin_start(6)
            row.set_margin_end(6)
            old_l = ui.label(util.display_name(old), "faint small", ellipsize=2)
            old_l.set_hexpand(True)
            new_l = ui.label(new, "small", ellipsize=2)
            new_l.set_hexpand(True)
            row.append(old_l)
            row.append(ui.image_icon("go-next-symbolic", 11))
            row.append(new_l)
            preview.append(row)
        if len(compute()) > 60:
            preview.append(ui.label(f"\u2026 and {len(compute()) - 60} more", "faint small"))

    for w in (pattern, find, replace):
        w.connect("changed", refresh)
    start.connect("value-changed", refresh)
    refresh()

    def apply():
        pairs = compute()
        d.close()
        window.apply_batch_rename(pairs)

    d.add_button("Cancel", d.close)
    d.add_button("Rename", apply, suggested=True)
    d.present()


# ---------------------------------------------------------------- properties --
def properties_dialog(window, path, trash_record=None):
    d = GlassDialog(window, "Properties", 500)
    name = os.path.basename(path.rstrip(os.sep)) or path
    body = d.body

    head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    icon = Gtk.Image()
    icon.set_pixel_size(42)
    head.append(icon)
    namebox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    title = ui.label(util.fsdec(name), "dialog-title", ellipsize=2, wrap=False)
    mime = util.mime_type(path) if not os.path.isdir(path) else "inode/directory"
    namebox.append(title)
    sub = ui.label(util.pretty_type(path, mime) + (" \u00b7 in Trash" if trash_record else ""),
                   "faint small")
    namebox.append(sub)
    head.append(namebox)
    body.append(head)

    try:
        fi = Gio.File.new_for_path(path).query_info(
            "standard::icon,standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
        icon.set_from_gicon(fi.get_icon())
    except Exception:
        icon.set_from_icon_name("text-x-generic-symbolic")

    info_grid = Gtk.Grid(row_spacing=6, column_spacing=14)
    info_grid.set_margin_top(6)
    body.append(info_grid)

    def add_info(row, key, value, wrap=True):
        info_grid.attach(ui.label(key, "faint small"), 0, row, 1, 1)
        lab = ui.label(value, "small", wrap=wrap, ellipsize=Pango.EllipsizeMode.MIDDLE)
        lab.set_selectable(True)
        info_grid.attach(lab, 1, row, 1, 1)
        return lab

    add_info(0, "Location", os.path.dirname(path) if not trash_record else (trash_record.get("original") or ""))
    size_label = add_info(1, "Size", "\u2026" if os.path.isdir(path) else util.human_size(os.path.getsize(path)))
    try:
        st = os.lstat(path)
        add_info(2, "Permissions", f"{util.perm_string(st.st_mode)} ({util.octal_mode(st.st_mode)})")
        add_info(3, "Owner", f"{util.user_name(st.st_uid)} : {util.group_name(st.st_gid)}")
        add_info(4, "Modified", util.format_date_full(st.st_mtime))
        add_info(5, "Accessed", util.format_date_full(st.st_atime))
        add_info(6, "Created / changed", util.format_date_full(st.st_ctime))
    except OSError:
        st = None
    if os.path.isdir(path):
        def work(job):
            return util.dir_size(path, cancel=job.cancel_event)

        def done(job, error):
            if job.status == "done":
                size_label.set_text(util.human_size(job.result))
            elif error:
                size_label.set_text("\u2014")

        window.jobs.submit(f"Size of {name}", work, done)

    if mime.startswith("image/") and os.path.isfile(path):
        try:
            from PIL import Image

            with Image.open(path) as im:
                add_info(7, "Dimensions",
                         f"{im.width} \u00d7 {im.height} px")
        except Exception:
            pass

    if st is not None and not os.path.islink(path):
        body.append(ui.sep())
        body.append(ui.label("Permissions", "title-strong small"))
        perm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        boxes = {}
        for who in ("user", "group", "other"):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.append(ui.label(who.capitalize(), "faint small"))
            for bit, letter in ((0o400, "r"), (0o200, "w"), (0o100, "x")):
                shift = {"user": 6, "group": 3, "other": 0}[who]
                flag = bit >> shift
                check = Gtk.CheckButton(label=letter)
                check.add_css_class("small")
                check.set_active(bool(st.st_mode & flag))
                boxes[(who, flag)] = check
                col.append(check)
            perm_box.append(col)
        body.append(perm_box)
        oct_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        oct_row.append(ui.label("Octal", "faint small"))
        oct_entry = Gtk.Entry()
        oct_entry.add_css_class("field")
        oct_entry.set_width_chars(6)
        oct_entry.set_text(util.octal_mode(st.st_mode))
        oct_row.append(oct_entry)
        body.append(oct_row)

        def apply_mode():
            mode = util.parse_octal(oct_entry.get_text())
            if mode is None:
                mode = 0
                for (who, flag), check in boxes.items():
                    if check.get_active():
                        mode |= flag
            try:
                ops.chmod(path, mode)
                oct_entry.set_text(util.octal_mode(mode))
                window.toast("Permissions updated")
            except OSError as e:
                window.toast(f"chmod failed: {e.strerror}")

        d.add_button("Apply Permissions", apply_mode)

    body.append(ui.sep())
    checks = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    combo = Gtk.DropDown.new_from_strings(["SHA-256", "SHA-1", "MD5"])
    checks.append(combo)
    result = ui.label("", "mono", ellipsize=2)
    result.set_hexpand(True)
    checks.append(result)

    def do_checksum():
        algo = ["sha256", "sha1", "md5"][combo.get_selected()]
        result.set_text("hashing\u2026")
        if not os.path.isfile(path):
            result.set_text("not a file")
            return

        def work(job):
            return ops.checksum(path, algo, cancel=job.cancel_event)

        def done(job, error):
            result.set_text(job.result if job.status == "done" else "\u2014")

        if window.jobs:
            window.jobs.submit("Checksum", work, done)
        else:
            result.set_text(ops.checksum(path, algo))

    d.add_button("Checksum", do_checksum)
    d.add_button("Close", d.close, suggested=True)
    return d.present()


# ---------------------------------------------------------------- open with --
def open_with_dialog(window, paths):
    if not paths:
        return
    first = paths[0]
    mime = util.mime_type(first)
    d = GlassDialog(window, "Open With", 470)
    d.body.append(ui.label(util.display_name(first), "small", ellipsize=2))
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_min_content_height(260)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    sw.set_child(listbox)
    d.body.append(sw)

    default = None
    try:
        default = Gio.AppInfo.get_default_for_type(mime, False)
    except Exception:
        pass
    try:
        apps = Gio.AppInfo.get_all_for_type(mime)
    except Exception:
        apps = []
    apps = sorted(apps, key=lambda a: (a.get_name() or "").casefold())
    if not apps:
        listbox.append(ui.label("No applications registered for this type.", "faint", wrap=True))

    def launch(app):
        try:
            files = [Gio.File.new_for_path(p) for p in paths]
            app.launch(files, None)
            d.close()
        except GLib.Error as e:
            window.toast(f"Could not launch: {e.message}")

    for app in apps[:60]:
        row = Gtk.Button()
        row.add_css_class("flat")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        img = Gtk.Image.new_from_gicon(app.get_icon()) if app.get_icon() else ui.image_icon("application-x-executable-symbolic")
        img.set_pixel_size(22)
        box.append(img)
        nm = ui.label(app.get_name() or app.get_id(), ellipsize=2)
        nm.set_hexpand(True)
        box.append(nm)
        if default is not None and app.get_id() == default.get_id():
            box.append(ui.label("default", "tag"))
        row.set_child(box)
        row.connect("clicked", lambda _b, a=app: launch(a))
        listbox.append(row)

    d.add_button("Cancel", d.close, suggested=True)
    return d.present()


# ----------------------------------------------------------------- compress --
def compress_dialog(window, paths):
    if not paths:
        return
    fmts = ["zip", "tar.gz", "tar.zst", "7z"]
    d = GlassDialog(window, "Compress", 430)
    name = Gtk.Entry()
    name.add_css_class("field")
    name.set_text(ops.archive_name_for(paths, "zip"))
    d.body.append(ui.label(f"{len(paths)} item(s)", "faint small"))
    d.body.append(name)
    combo = Gtk.DropDown.new_from_strings(["ZIP (.zip)", "TAR + GZip (.tar.gz)",
                                           "TAR + Zstd (.tar.zst)", "7-Zip (.7z)"])
    combo.set_selected(0)
    d.body.append(combo)

    def apply():
        fmt = fmts[combo.get_selected()]
        target = name.get_text().strip() or ops.archive_name_for(paths, fmt)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(paths[0]) if not os.path.isdir(paths[0]) else paths[0], target)
        d.close()
        window.run_compress(paths, target, fmt)

    name.connect("activate", lambda *_: apply())
    d.add_button("Cancel", d.close)
    d.add_button("Compress", apply, suggested=True)
    return d.present()


# ------------------------------------------------------------- new file/tmpl --
def new_file_dialog(window, folder):
    d = GlassDialog(window, "New File", 430)
    name = Gtk.Entry()
    name.add_css_class("field")
    name.set_text("Untitled.txt")
    d.body.append(name)
    templates = []
    tdir = util.dirs_from_xdg().get("TEMPLATES") or ""
    if os.path.isdir(tdir):
        try:
            templates = [os.path.join(tdir, n) for n in sorted(os.listdir(tdir))
                         if os.path.isfile(os.path.join(tdir, n))]
        except OSError:
            templates = []
    labels = ["Empty file"] + [os.path.basename(t) for t in templates]
    combo = Gtk.DropDown.new_from_strings(labels)
    d.body.append(combo)

    def apply():
        nm = name.get_text().strip()
        if not nm:
            return
        idx = combo.get_selected()
        content = b""
        if idx > 0 and idx - 1 < len(templates):
            try:
                with open(templates[idx - 1], "rb") as f:
                    content = f.read()
                if nm == "Untitled.txt":
                    nm = os.path.basename(templates[idx - 1])
            except OSError:
                pass
        d.close()
        window.create_file(folder, nm, content)

    name.connect("activate", lambda *_: apply())
    d.add_button("Cancel", d.close)
    d.add_button("Create", apply, suggested=True)
    d.present()
    name.grab_focus()
    name.select_region(0, len(name.get_text()))


# -------------------------------------------------------------- preferences --
def preferences_dialog(window):
    p = window.prefs
    d = GlassDialog(window, "Preferences", 480)
    grid = Gtk.Grid(row_spacing=10, column_spacing=14)
    d.body.append(grid)

    def row(r, text, widget, hint=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.append(ui.label(text, "small"))
        if hint:
            box.append(ui.label(hint, "faint small"))
        grid.attach(box, 0, r, 1, 1)
        widget.set_halign(Gtk.Align.END)
        grid.attach(widget, 1, r, 1, 1)

    view = Gtk.DropDown.new_from_strings(["Icons", "List", "Compact"])
    view.set_selected({"grid": 0, "list": 1, "compact": 2}.get(p.get("view"), 0))
    row(0, "Default view", view)

    hidden = Gtk.Switch()
    hidden.set_active(bool(p.get("show_hidden")))
    row(1, "Show hidden files", hidden)

    sort = Gtk.DropDown.new_from_strings(["Name", "Size", "Modified", "Type", "Extension"])
    keys = ["name", "size", "modified", "type", "extension"]
    sort.set_selected(keys.index(p.get("sort", {}).get("key", "name")))
    row(2, "Default sort", sort)

    single = Gtk.Switch()
    single.set_active(bool(p.get("single_click")))
    row(3, "Open with a single click", single)

    confirm_del = Gtk.Switch()
    confirm_del.set_active(bool(p.get("confirm_delete")))
    row(4, "Confirm permanent delete", confirm_del)

    terminal = Gtk.Entry()
    terminal.add_css_class("field")
    terminal.set_text(p.get("terminal", "kitty"))
    terminal.set_width_chars(14)
    row(5, "Terminal command", terminal)

    thumb_limit = Gtk.SpinButton.new_with_range(4, 512, 4)
    thumb_limit.set_value(int(p.get("thumbnail_limit_mb", 32)))
    thumb_limit.add_css_class("field")
    row(6, "Thumbnail cache limit (MB)", thumb_limit)

    theme = Gtk.DropDown.new_from_strings(["Auto (wallpaper)", "Smoked glass", "Bright glass"])
    theme.set_selected({"auto": 0, "dark": 1, "light": 2}.get(p.get("theme", "auto"), 0))
    row(7, "Glass style", theme)

    def save():
        p.data["view"] = ["grid", "list", "compact"][view.get_selected()]
        p.data["show_hidden"] = hidden.get_active()
        p.data["sort"]["key"] = keys[sort.get_selected()]
        p.data["single_click"] = single.get_active()
        p.data["confirm_delete"] = confirm_del.get_active()
        p.data["terminal"] = terminal.get_text().strip() or "kitty"
        p.data["thumbnail_limit_mb"] = int(thumb_limit.get_value())
        p.data["theme"] = ["auto", "dark", "light"][theme.get_selected()]
        p.save()
        d.close()
        window.apply_preferences()

    d.add_button("Cancel", d.close)
    d.add_button("Save", save, suggested=True)
    return d.present()


# --------------------------------------------------------- connect to server --
def connect_server(window):
    d = GlassDialog(window, "Connect to Server", 460)
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    scheme = Gtk.DropDown.new_from_strings(["smb://", "sftp://", "ftp://", "dav://", "davs://"])
    scheme.set_selected(0)
    entry = Gtk.Entry()
    entry.add_css_class("field")
    entry.set_placeholder_text("server/share")
    entry.set_hexpand(True)
    box.append(scheme)
    box.append(entry)
    d.body.append(box)
    d.body.append(ui.label("Needs GVfs. You may be asked for a password.",
                           "faint small", wrap=True))

    def go():
        uri = ["smb://", "sftp://", "ftp://", "dav://", "davs://"][scheme.get_selected()] + entry.get_text().strip()
        d.close()
        window.connect_uri(uri)

    entry.connect("activate", lambda *_: go())
    d.add_button("Cancel", d.close)
    d.add_button("Connect", go, suggested=True)
    d.present()
    entry.grab_focus()


# ------------------------------------------------------------------ conflict --
class ConflictRequest:
    def __init__(self, src, dst, is_dir, dst_is_dir):
        self.src = src
        self.dst = dst
        self.is_dir = is_dir
        self.dst_is_dir = dst_is_dir
        self.answer = None
        self.apply_all = False
        self.event = threading.Event()
        self.cancelled = False


def conflict_dialog(window, req: ConflictRequest):
    d = GlassDialog(window, "An item already exists", 480)
    d.body.append(ui.label(os.path.basename(req.src), "title-strong", ellipsize=2))
    d.body.append(ui.label(
        f"\u201c{os.path.basename(req.dst)}\u201d exists in this folder. "
        + ("Both are folders." if req.is_dir and req.dst_is_dir else "What should happen?"),
        "dialog-sub", wrap=True))
    apply_all = Gtk.CheckButton(label="Apply to all remaining conflicts")
    apply_all.add_css_class("small")
    d.body.append(apply_all)

    def answer(mode):
        req.answer = mode
        req.apply_all = apply_all.get_active()
        req.event.set()
        d.close()

    d.add_button("Skip", lambda: answer(ops.SKIP))
    if req.is_dir and req.dst_is_dir:
        d.add_button("Merge", lambda: answer(ops.MERGE))
    d.add_button("Keep Both", lambda: answer(ops.KEEP_BOTH))
    d.add_button("Replace", lambda: answer(ops.REPLACE), destructive=True)
    d.connect("close-request", lambda *_: (answer(ops.SKIP) if not req.event.is_set() else None) or False)
    return d.present()
