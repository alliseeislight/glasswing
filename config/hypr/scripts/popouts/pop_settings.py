import json
import os
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import GdkPixbuf, Pango

from glass import *
import settings_logic as L
import shell_cfg as SC

HOME = os.path.expanduser("~")
KITTY = shutil.which("kitty") or "kitty"

# App installer cache
APP_CACHE_FILE = os.path.join(HOME, ".cache", "glass-app-cache.json")
APP_CACHE_TTL = 86400  # 24 hours


def hypr_get(keys):
    out = {}
    for k in keys:
        try:
            d = json.loads(run("hyprctl", "getoption", k, "-j"))
            for t in ("int", "float"):
                if t in d:
                    out[k] = d[t]
                    break
        except Exception:
            pass
    return out


def apply_palette_files(path):
    """Re-run wallust on a wallpaper (video -> one frame first), then reload everything that reads it."""
    src = path
    if path.lower().endswith(L.VID):
        src = "/tmp/glass-wall-frame.png"
        run_rc("ffmpeg", "-y", "-ss", "1", "-i", path, "-frames:v", "1", src, timeout=30)
    rc, text = run_rc("wallust", "run", src, timeout=60)
    run("pkill", "-USR1", "kitty")
    run("pkill", "-SIGUSR2", "waybar")
    run("swaync-client", "-rs")
    run("hyprctl", "reload")
    return rc, text


# ---------------------------------------------------------------- pages
class Page:
    def __init__(self, owner):
        self.owner = owner
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.status = label("", "dimtext")
        self.build()
        self.box.append(self.status)

    def say(self, text):
        self.status.set_text(text)

    def build(self):
        pass

    def on_show(self):
        pass


def sec(text):
    return label(text.upper(), "sec")


class SliderRow:
    def __init__(self, page, title, key, lo, hi):
        self.page, self.key, self.guard = page, key, False
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        t = label(title, "plain")
        t.set_size_request(140, -1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.val = label("", "pct", xalign=1.0)
        self.box.append(t)
        self.box.append(self.scale)
        self.box.append(self.val)
        self.scale.connect("value-changed", self.changed)

    def set(self, v):
        self.guard = True
        self.scale.set_value(v)
        self.guard = False
        self.val.set_text(str(int(round(v))))

    def changed(self, scale):
        if self.guard:
            return
        v = int(round(scale.get_value()))
        self.val.set_text(str(v))
        self.page.queue(self.key, v)


class LookPage(Page):
    SLIDERS = [
        ("Blur size", "decoration:blur:size", 1, 20),
        ("Blur passes", "decoration:blur:passes", 1, 6),
        ("Corner rounding", "decoration:rounding", 0, 32),
        ("Gaps between windows", "general:gaps_in", 0, 20),
        ("Gaps to screen edge", "general:gaps_out", 0, 40),
    ]

    def build(self):
        self.timer = None
        self.rows = []
        self.box.append(sec("Accent colour"))
        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.auto_btn = Gtk.Button(label="Follow wallpaper")
        self.auto_btn.add_css_class("chip")
        self.auto_btn.connect("clicked", lambda _b: self.set_accent("auto"))
        modes.append(self.auto_btn)
        self.box.append(modes)
        sw = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sw.set_margin_top(4)
        self.swatches = []
        for i, hexv in enumerate(L.SWATCHES):
            b = Gtk.Button()
            b.add_css_class("swatch")
            b.add_css_class(f"sw{i}")
            b.connect("clicked", lambda _b, h=hexv: self.set_accent("manual", h))
            sw.append(b)
            self.swatches.append((b, hexv))
        self.box.append(sw)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Glass & layout"))
        for title, key, lo, hi in self.SLIDERS:
            r = SliderRow(self, title, key, lo, hi)
            self.rows.append(r)
            self.box.append(r.box)
        reset = Gtk.Button(label="Reset to defaults")
        reset.add_css_class("chip")
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", lambda _b: self.reset())
        self.box.append(reset)

    def on_show(self):
        self.mark_accent()
        keys = [r.key for r in self.rows]
        bg(lambda: hypr_get(keys), self.fill)

    def fill(self, vals):
        for r in self.rows:
            if r.key in vals:
                r.set(vals[r.key])

    def mark_accent(self):
        st = L.load_settings()
        manual = st.get("accent_mode") == "manual"
        cur = (st.get("accent") or "").lower()
        (self.auto_btn.remove_css_class if manual else self.auto_btn.add_css_class)("current")
        for b, hexv in self.swatches:
            (b.add_css_class if manual and hexv == cur else b.remove_css_class)("on")

    def set_accent(self, mode, hexv=None):
        st = L.load_settings()
        st["accent_mode"] = mode
        if hexv:
            st["accent"] = hexv
        L.save_settings(st)
        self.mark_accent()
        self.owner.app.refresh_accent()
        self.say("Accent follows your wallpaper" if mode == "auto" else "Accent set")

    def queue(self, key, value):
        st = L.load_settings()
        st.setdefault("hypr", {})[key] = value
        L.save_settings(st)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(500, self.apply)

    def apply(self):
        self.timer = None

        def work():
            L.write_atomic(L.USER_LUA, L.lua_text(L.load_settings().get("hypr", {})))
            run("hyprctl", "reload")
            return run("hyprctl", "configerrors").strip()

        def done(err):
            self.say("Applied" if not err else "Hyprland rejected a value: " + err.splitlines()[0][:110])

        self.say("Applying…")
        bg(work, done)
        return False

    def reset(self):
        st = L.load_settings()
        st["hypr"] = {}
        L.save_settings(st)
        self.say("Resetting…")

        def work():
            L.write_atomic(L.USER_LUA, L.lua_text({}))
            run("hyprctl", "reload")
            return hypr_get([r.key for r in self.rows])

        def done(vals):
            self.fill(vals)
            self.say("Back to defaults")

        bg(work, done)


class WallpaperPage(Page):
    def build(self):
        self.thumbs = {}
        self.buttons = {}
        self.cur = ""
        self.box.append(sec("Wallpaper"))
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(3)
        self.flow.set_min_children_per_line(2)
        self.flow.set_column_spacing(8)
        self.flow.set_row_spacing(8)
        self.flow.set_homogeneous(True)
        self.box.append(self.flow)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nxt = Gtk.Button(label="Next wallpaper")
        nxt.add_css_class("chip")
        nxt.connect("clicked", lambda _b: self.next_wall())
        row.append(nxt)
        if shutil.which("waypaper"):
            wp = Gtk.Button(label="Open Waypaper")
            wp.add_css_class("chip")
            wp.connect("clicked", lambda _b: (fire("waypaper"), self.owner.hide()))
            row.append(wp)
        self.box.append(row)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Colour style"))
        self.pal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pal_btns = {}
        for name in L.PALETTES:
            b = Gtk.Button(label=name)
            b.add_css_class("chip")
            b.connect("clicked", lambda _b, n=name: self.set_palette(n))
            self.pal_row.append(b)
            self.pal_btns[name] = b
        self.box.append(self.pal_row)

    def on_show(self):
        self.cur = L.current_wallpaper()
        if not self.buttons:
            self.fill_grid()
        self.mark()
        pal = L.palette_get()
        for n, b in self.pal_btns.items():
            (b.add_css_class if n == pal else b.remove_css_class)("current")

    def fill_grid(self):
        walls = L.wallpapers()
        if not walls:
            self.flow.append(label("Put images or videos in ~/Pictures/wallpapers", "dimtext"))
            return
        for path, is_video in walls:
            btn = Gtk.Button()
            btn.add_css_class("thumbbtn")
            if is_video:
                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                inner.set_size_request(172, 97)
                inner.add_css_class("thumb")
                inner.set_overflow(Gtk.Overflow.HIDDEN)
                inner.append(label("󰕧", "big", xalign=0.5, hexpand=True))
                inner.append(label(os.path.basename(path)[:22], "dimtext", xalign=0.5))
                btn.set_child(inner)
            else:
                pic = Gtk.Picture()
                pic.set_size_request(172, 97)
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.add_css_class("thumb")
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                btn.set_child(pic)
                bg(lambda p=path: self.load_thumb(p), lambda pix, pc=pic: self.set_thumb(pc, pix))
            btn.connect("clicked", lambda _b, p=path: self.apply_wall(p))
            self.flow.append(btn)
            self.buttons[path] = btn

    TW, TH = 172, 97

    @staticmethod
    def load_thumb(path):
        try:
            tw, th = WallpaperPage.TW, WallpaperPage.TH
            info = GdkPixbuf.Pixbuf.get_file_info(path)
            w, h = info[1], info[2]
            k = max(tw / w, th / h)
            sw, sh = max(tw, int(w * k + 0.5)), max(th, int(h * k + 0.5))
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
            return pix.new_subpixbuf((sw - tw) // 2, (sh - th) // 2, tw, th)
        except Exception:
            return None

    @staticmethod
    def set_thumb(pic, pix):
        if pix is not None:
            pic.set_paintable(Gdk.Texture.new_for_pixbuf(pix))

    def mark(self):
        for p, b in self.buttons.items():
            (b.add_css_class if p == self.cur else b.remove_css_class)("on")

    def apply_wall(self, path):
        self.say("Applying wallpaper…")

        def work():
            rc, _t = run_rc("waypaper", "--wallpaper", path, timeout=40)
            if rc != 0:
                return rc
            apply_palette_files(path)
            return 0

        def done(rc):
            if rc == 0:
                self.cur = path
                self.mark()
                self.say("Wallpaper and colours updated")
            else:
                self.say("waypaper couldn't set it — is it installed and configured?")

        bg(work, done)

    def next_wall(self):
        script = os.path.join(L.HYPR, "scripts", "cycle_wall.sh")
        if os.path.exists(script):
            fire(script)
            self.say("Cycling wallpaper…")
            GLib.timeout_add(2500, lambda: (self.on_show(), False)[1])
        else:
            self.say("cycle_wall.sh not found")

    def set_palette(self, name):
        if not L.palette_set(name):
            self.say("Couldn't find the palette line in wallust.toml")
            return
        self.say("Regenerating colours…")
        wall = self.cur or L.current_wallpaper()
        if not wall:
            self.say("Palette saved — pick a wallpaper to apply it")
            return
        bg(lambda: apply_palette_files(wall), lambda _r: (self.say("Colour style applied"), self.on_show()))


class LinksPage(Page):
    LINKS = [
        ("󰖩", "Wi-Fi & networks", "nm-connection-editor", "networkmanager"),
        ("󰂯", "Bluetooth devices", "blueman-manager", "blueman"),
        ("󰕾", "Sound & audio", "pavucontrol", "pavucontrol"),
        ("󰍹", "Display & monitors", "hyprmod", "hyprmod"),
        ("󰃟", "GTK theme & cursor", "nwg-look", "nwg-look"),
        ("󰒓", "Hyprland (advanced)", "hyprmod", "hyprmod"),
    ]

    def build(self):
        self.box.append(sec("Open settings for"))
        for icon, title, cmd, pkg in self.LINKS:
            have = shutil.which(cmd) is not None
            hint = "" if have else f"yay -S {pkg}"
            btn = item(icon, title, hint, False, (lambda c=cmd: (fire(c), self.owner.hide())) if have else None)
            if not have:
                btn.set_sensitive(False)
            self.box.append(btn)
        self.box.append(Gtk.Separator())
        self.box.append(sec("Displays"))
        self.mon = label("Loading…", "dimtext")
        self.box.append(self.mon)

    def on_show(self):
        def fetch():
            try:
                return L.monitors_summary(json.loads(run("hyprctl", "monitors", "-j")))
            except Exception:
                return []

        bg(fetch, lambda m: self.mon.set_text("\n".join(m) or "No display info"))


class KeybindsPage(Page):
    def build(self):
        self.rows = []
        self.box.append(sec("Keybinds"))
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search keys or actions")
        self.entry.connect("changed", lambda _e: self.render())
        self.box.append(self.entry)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.append(self.list)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        edit = Gtk.Button(label="Edit binds.lua")
        edit.add_css_class("chip")
        edit.connect("clicked", lambda _b: self.edit())
        rel = Gtk.Button(label="Reload Hyprland")
        rel.add_css_class("chip")
        rel.connect("clicked", lambda _b: (fire("hyprctl", "reload"), self.say("Reloaded")))
        row.append(edit)
        row.append(rel)
        self.box.append(row)

    def path(self):
        return os.path.join(L.HYPR, "components", "binds.lua")

    def on_show(self):
        self.entry.set_text("")
        bg(lambda: L.parse_binds(L.read(self.path())), self.set_rows)

    def set_rows(self, rows):
        self.rows = rows
        self.render()

    def render(self):
        clear(self.list)
        q = self.entry.get_text().strip().lower()
        shown = [r for r in self.rows if q in (r[0] + " " + r[1]).lower()][:60]
        if not shown:
            self.list.append(label("No keybinds found", "dimtext"))
            return
        for keys, act in shown:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            k = label(keys, "plain")
            k.set_size_request(190, -1)
            a = label(act, "dimtext", hexpand=True)
            a.set_ellipsize(Pango.EllipsizeMode.END)
            row.append(k)
            row.append(a)
            self.list.append(row)

    def edit(self):
        fire(KITTY, "-e", "micro", self.path())
        self.owner.hide()


class StartupPage(Page):
    def build(self):
        self.box.append(sec("Runs at login"))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.append(self.list)
        self.box.append(label("Changes apply the next time you log in.", "dimtext"))

    def path(self):
        return os.path.join(L.HYPR, "components", "autostart.lua")

    def on_show(self):
        bg(lambda: L.parse_autostart(L.read(self.path())), self.render)

    def render(self, items):
        clear(self.list)
        if not items:
            self.list.append(label("No simple autostart entries found", "dimtext"))
            return
        for it in items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            name = label(it["text"], "plain", hexpand=True)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(it["enabled"])
            if it["protected"]:
                sw.set_sensitive(False)
                name.set_text(it["text"] + "  (needed by the popups)")
            sw.connect("state-set", lambda _s, state, i=it["idx"]: self.toggle(i, state))
            row.append(name)
            row.append(sw)
            self.list.append(row)

    def toggle(self, idx, state):
        p = self.path()
        L.backup_once(p)
        L.write_atomic(p, L.set_autostart(L.read(p), idx, state))
        self.say("Saved — takes effect next login")
        return False


class AppUninstallerPage(Page):
    def build(self):
        self.box.append(sec("App Uninstaller"))

        # Search entry
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search installed packages...")
        self.search_entry.connect("changed", self.on_search_changed)
        self.search_entry.connect("activate", self.on_search_activate)
        self.box.append(self.search_entry)

        # Status label
        self.status_label = label("", "dimtext")
        self.box.append(self.status_label)

        # Results list
        self.results_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(420)
        scrolled.set_child(self.results_list)
        self.box.append(scrolled)

        # Action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button(label="Refresh installed list")
        refresh.add_css_class("chip")
        refresh.connect("clicked", self.refresh_packages)
        btn_row.append(refresh)

        orphan = Gtk.Button(label="Remove orphans")
        orphan.add_css_class("chip")
        orphan.connect("clicked", self.remove_orphans)
        btn_row.append(orphan)

        self.box.append(btn_row)

        # State
        self.packages = []  # list of dicts: {name, size, description}
        self.search_timer = None
        self.removing = set()

    def on_show(self):
        self.search_entry.set_text("")
        self.refresh_packages()

    def refresh_packages(self, _btn=None):
        self.say("Fetching installed packages...")

        def work():
            # Get explicitly installed packages with sizes
            out = run("pacman", "-Qqe", timeout=30)
            pkgs = [line.strip() for line in out.splitlines() if line.strip()]

            # Get size info for each package
            detailed = []
            for pkg in pkgs:
                try:
                    # Get package info including size
                    info_out = run("pacman", "-Qi", pkg, timeout=10)
                    size = "?"
                    desc = ""
                    for line in info_out.splitlines():
                        if line.startswith("Installed Size"):
                            size = line.split(":", 1)[1].strip()
                        elif line.startswith("Description"):
                            desc = line.split(":", 1)[1].strip()
                    detailed.append({"name": pkg, "size": size, "desc": desc})
                except Exception:
                    detailed.append({"name": pkg, "size": "?", "desc": ""})
            return detailed

        def done(result):
            if isinstance(result, list):
                self.packages = result
                self.say(f"Found {len(self.packages)} installed packages")
                self.render_results()
            else:
                self.say("Failed to fetch packages")

        bg(work, done)

    def on_search_changed(self, entry):
        if self.search_timer:
            GLib.source_remove(self.search_timer)
            self.search_timer = None
        self.search_timer = GLib.timeout_add(200, self._render_later)

    def _render_later(self):
        self.search_timer = None
        self.render_results()
        return False

    def on_search_activate(self, entry):
        self.render_results()

    def render_results(self):
        clear(self.results_list)
        query = self.search_entry.get_text().strip().lower()

        if not query:
            self.results_list.append(label("Type to search installed packages...", "dimtext"))
            return

        # Filter packages
        matches = [p for p in self.packages if query in p["name"].lower()][:50]

        if not matches:
            self.results_list.append(label(f"No installed packages matching '{query}'", "dimtext"))
            return

        for pkg in matches:
            is_removing = pkg["name"] in self.removing

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_margin_top(4)
            row.set_margin_bottom(4)

            # Package info
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            info_box.set_hexpand(True)

            name_label = label(pkg["name"], "plain", hexpand=True)
            name_label.set_ellipsize(Pango.EllipsizeMode.END)
            info_box.append(name_label)

            details = []
            if pkg["size"] != "?":
                details.append(f"Size: {pkg['size']}")
            if pkg["desc"]:
                details.append(pkg["desc"][:80])
            if details:
                detail_label = label(" · ".join(details), "dimtext", hexpand=True)
                detail_label.set_ellipsize(Pango.EllipsizeMode.END)
                info_box.append(detail_label)

            row.append(info_box)

            # Action
            if is_removing:
                badge = label("Removing...", "sec")
                badge.add_css_class("chip")
                row.append(badge)
            else:
                remove = Gtk.Button(label="Remove")
                remove.add_css_class("chip")
                remove.connect("clicked", lambda _b, p=pkg["name"]: self.remove_package(p))
                row.append(remove)

            self.results_list.append(row)

    def remove_package(self, pkg):
        self.removing.add(pkg)
        self.say(f"Waiting for authentication to remove {pkg}...")
        self.render_results()

        def work():
            # pkexec can show the desktop password dialog. yay/sudo cannot prompt
            # from this GTK popup because it has no controlling terminal.
            rc, out = run_rc(
                "pkexec", "/usr/bin/pacman", "-Rns", "--noconfirm", pkg, timeout=180
            )
            return rc, out, pkg

        def done(result):
            rc, out, pkg = result
            self.removing.discard(pkg)
            if rc == 0:
                self.say(f"Removed {pkg}")
                self.refresh_packages()
            else:
                lines = out.strip().splitlines()
                msg = lines[-1][:120] if lines else "unknown error"
                self.say(f"Failed to remove {pkg}: {msg}")
                self.render_results()

        bg(work, done)

    def remove_orphans(self, _btn=None):
        self.say("Removing orphaned packages...")

        def work():
            # Get orphans first
            out = run("pacman", "-Qtdq", timeout=30)
            orphans = [line.strip() for line in out.splitlines() if line.strip()]
            if not orphans:
                return 0, "No orphaned packages found"
            # Remove them through the desktop authentication agent.
            rc, out = run_rc(
                "pkexec", "/usr/bin/pacman", "-Rns", "--noconfirm", *orphans, timeout=300
            )
            return rc, out

        def done(result):
            rc, out = result
            if rc == 0:
                self.say("Orphans removed")
                self.refresh_packages()
            else:
                if "No orphaned" in out:
                    self.say("No orphaned packages")
                else:
                    lines = out.strip().splitlines()
                    msg = lines[-1][:120] if lines else "unknown error"
                    self.say(f"Failed: {msg}")

        bg(work, done)


# ---------------------------------------------------------------- window
class ShellPage(Page):
    def build(self):
        self.syncing = False
        self.sw = {}
        self.box.append(sec("Shell"))
        cfg = SC.load()
        for key, title in (("dock", "Dock"), ("widgets", "Desktop widgets"), ("bar", "Top bar")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.append(label(title, "plain", hexpand=True))
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(bool(cfg[key].get("enabled", True)))
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            row.append(sw)
            self.box.append(row)
            self.sw[key] = sw
        self.box.append(label("Changes apply right away and are remembered.", "dimtext"))

    def on_show(self):
        cfg = SC.load()
        self.syncing = True
        for key, sw in self.sw.items():
            sw.set_active(bool(cfg[key].get("enabled", True)))
        self.syncing = False

    def toggle(self, key, state):
        if self.syncing:
            return False
        cfg = SC.load()
        cfg[key]["enabled"] = bool(state)
        SC.save(cfg)
        self.owner.app.set_shell(key, bool(state))
        self.say({"dock": "Dock", "widgets": "Widgets", "bar": "Top bar"}[key] + (" on" if state else " off"))
        return False


class SettingsPopup(Popup):
    name = "settings"
    width = 820
    centered = True
    top = 70
    autohide = False

    PAGES = [
        ("󰔎", "Look & feel", LookPage),
        ("󰸉", "Wallpaper & theme", WallpaperPage),
        ("󰖩", "Quick links", LinksPage),
        ("󰌌", "Keybinds", KeybindsPage),
        ("󰐥", "Startup", StartupPage),
        ("󰏖", "App Uninstaller", AppUninstallerPage),
        ("󰍹", "Shell", ShellPage),
    ]

    def build(self, root):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.append(label("Settings", "title", hexpand=True))
        close = Gtk.Button(label="󰅖")
        close.add_css_class("nav")
        close.connect("clicked", lambda _b: self.hide())
        head.append(close)
        root.append(head)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav.set_size_request(190, -1)
        nav.set_hexpand(False)
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.pages, self.navbtns = {}, {}
        for icon, title, cls in self.PAGES:
            page = cls(self)
            self.pages[title] = page
            sc = Gtk.ScrolledWindow()
            sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sc.set_min_content_height(470)
            sc.set_max_content_height(470)
            sc.set_child(page.box)
            self.stack.add_named(sc, title)
            b = item(icon, title, "", False, lambda t=title: self.go(t))
            nav.append(b)
            self.navbtns[title] = b
        body.append(nav)
        body.append(self.stack)
        root.append(body)
        self.go(self.PAGES[0][1], show=False)

    def go(self, title, show=True):
        self.stack.set_visible_child_name(title)
        for t, b in self.navbtns.items():
            (b.add_css_class if t == title else b.remove_css_class)("current")
        if show:
            self.pages[title].on_show()

    def on_show(self):
        name = self.stack.get_visible_child_name() or self.PAGES[0][1]
        self.pages[name].on_show()
