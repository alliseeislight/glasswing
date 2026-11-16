import json
import os
import socket
import time

from gi.repository import Gio, Gdk

from glass import *
import shell_cfg as C

HERE = os.path.dirname(os.path.abspath(__file__))
POPUP = os.path.join(HERE, "popup.sh")
ROFI_THEME = os.path.expanduser("~/.config/rofi/glass.rasi")

# Hyprland's Lua dispatch syntax differs between builds, so try the likely forms and remember the one that works.
FOCUS_EXPRS = [
    'hl.dsp.focus({ window = "address:%s" })',
    'hl.dsp.window.focus({ window = "address:%s" })',
    'hl.dsp.focus_window("address:%s")',
]
_focus_ok = None


def focus(address):
    global _focus_ok
    order = list(range(len(FOCUS_EXPRS)))
    if _focus_ok is not None:
        order.remove(_focus_ok)
        order.insert(0, _focus_ok)
    for i in order:
        rc, out = run_rc("hyprctl", "dispatch", FOCUS_EXPRS[i] % address, timeout=3)
        if rc == 0 and out.strip().lower() == "ok":
            _focus_ok = i
            return True
    print("dock: could not focus", address, "- tried", len(order), "forms")
    return False


def clients():
    try:
        data = json.loads(run("hyprctl", "clients", "-j"))
    except Exception:
        return []
    out = []
    for c in data:
        cls = (c.get("class") or "").strip()
        if not cls or not c.get("mapped", True) or c.get("hidden"):
            continue
        out.append({"class": cls, "address": c.get("address", ""), "focus": c.get("focusHistoryID", 99)})
    return out


def build_index():
    """window class (lower-case) -> desktop id"""
    idx = {}
    for info in Gio.AppInfo.get_all():
        try:
            if not info.should_show():
                continue
        except Exception:
            pass
        did = info.get_id() or ""
        keys = {did.lower().removesuffix(".desktop")}
        try:
            wm = info.get_startup_wm_class()
            if wm:
                keys.add(wm.lower())
        except Exception:
            pass
        exe = info.get_executable()
        if exe:
            keys.add(os.path.basename(exe).lower())
        for k in keys:
            idx.setdefault(k, did)
    return idx


TRIGGER_PX = 5   # cursor this close to the bottom edge reveals the dock
ZONE_PAD = 16    # extra px above the dock that still counts as being on the dock


def cursor_pos():
    # read the cursor from the Hyprland socket, fall back to hyprctl
    try:
        sig = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
        path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "hypr", sig, ".socket.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            s.connect(path)
            s.sendall(b"/cursorpos")
            data = s.recv(128).decode().strip()
    except Exception:
        data = (run("hyprctl", "cursorpos", timeout=1) or "").strip()
    try:
        x, y = data.split(",")
        return int(float(x)), int(float(y))
    except Exception:
        return None


class Dock:
    def __init__(self, app):
        self.win = None
        cfg = C.load()
        self.full = cfg
        self.cfg = cfg["dock"]
        if not self.cfg.get("enabled", True):
            return
        self.index = build_index()
        self.sig = None
        self.size = int(self.cfg.get("icon_size", 44))

        if not self.cfg.get("pinned"):
            ids = [i.get_id() for i in Gio.AppInfo.get_all() if i.get_id()]
            self.cfg["pinned"] = C.default_pinned(ids)
            C.save(self.full)

        win = Gtk.ApplicationWindow(application=app)
        win.add_css_class("dock")
        LS.init_for_window(win)
        LS.set_namespace(win, "glass-dock")
        LS.set_layer(win, LS.Layer.TOP)
        LS.set_anchor(win, LS.Edge.BOTTOM, True)
        LS.set_margin(win, LS.Edge.BOTTOM, -self.get_height())  # Start hidden (slide up)
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
        # NO exclusive zone - overlay on top of windows
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.box.add_css_class("dockpad")
        win.set_child(self.box)
        self.win = win
        win.present()

        # State
        self.enabled = True
        self.visible = False
        self.target_visible = False
        self.animating = False
        self.last_activity = time.monotonic()
        self.hide_delay = 5.0  # seconds

        # Mouse tracking
        self.cursor_monitor = None
        self.setup_mouse_tracking()

        # Animation
        self.dock_height = self.get_height()
        self.start_animation()

        # Initial refresh
        self.refresh()
        GLib.timeout_add_seconds(1, self.tick)

    def set_enabled(self, on):
        self.enabled = on
        self.cfg["enabled"] = on
        if not self.win:
            return
        self.target_visible = False
        self.visible = False
        LS.set_margin(self.win, LS.Edge.BOTTOM, -self.dock_height)
        if on:
            self.sig = None
            self.win.present()
            self.refresh()
        else:
            self.win.set_visible(False)

    def get_height(self):
        """Calculate dock height based on icon size + padding"""
        return self.size + 24  # icon + padding + dots

    def setup_mouse_tracking(self):
        """Track mouse position to show/hide dock"""
        # Add motion controller to the dock window itself
        motion = Gtk.EventControllerMotion.new()
        motion.connect("enter", lambda *_a: self.record_activity())
        motion.connect("leave", lambda *_a: self.check_hide())
        self.win.add_controller(motion)

        # Also poll cursor position using hyprctl for global position
        GLib.timeout_add(100, self.check_cursor_position)

    def monitor_geom(self):
        try:
            display = Gdk.Display.get_default()
            mon = display.get_monitor_at_surface(self.win.get_surface())
            return mon.get_geometry() if mon else None
        except Exception:
            return None

    def check_cursor_position(self):
        # bottom edge reveals, above-middle hides, 5s off the dock hides
        if not self.win or not self.enabled:
            return True
        pos = cursor_pos()
        geom = self.monitor_geom()
        if pos is None or geom is None:
            return True
        x, y = pos
        bottom = geom.y + geom.height
        middle = geom.y + geom.height // 2
        on_monitor = geom.x <= x < geom.x + geom.width
        from_bottom = bottom - y

        if not on_monitor or y < middle:
            self.hide_dock()
            return True

        zone = self.dock_height + 8 + ZONE_PAD
        at_edge = from_bottom <= TRIGGER_PX
        over_dock = self.target_visible and from_bottom <= zone
        if at_edge or over_dock:
            self.last_activity = time.monotonic()
            if not self.target_visible:
                self.show_dock()
        elif self.target_visible and time.monotonic() - self.last_activity > self.hide_delay:
            self.hide_dock()
        return True

    def check_hide(self):
        """Check if we should hide when mouse leaves dock"""
        if self.target_visible and time.monotonic() - self.last_activity > self.hide_delay:
            # Check if cursor is actually at bottom
            self.check_cursor_position()

    def show_dock(self):
        self.target_visible = True
        self.last_activity = time.monotonic()
        if not self.visible:
            self.start_animation()

    def hide_dock(self):
        self.target_visible = False
        if self.visible:
            self.start_animation()

    def start_animation(self):
        if self.animating:
            return
        self.animating = True
        self.animate_step()

    def animate_step(self):
        if not self.win:
            self.animating = False
            return

        current_margin = LS.get_margin(self.win, LS.Edge.BOTTOM)
        target_margin = 8 if self.target_visible else -self.dock_height

        # Smooth animation
        diff = target_margin - current_margin
        if abs(diff) < 2:
            LS.set_margin(self.win, LS.Edge.BOTTOM, target_margin)
            self.visible = self.target_visible
            self.animating = False
            return

        # Ease out animation
        step = diff * 0.3
        new_margin = current_margin + step
        LS.set_margin(self.win, LS.Edge.BOTTOM, int(new_margin))

        # Continue animation
        GLib.timeout_add(16, self.animate_step)

    def record_activity(self):
        self.last_activity = time.monotonic()
        if not self.target_visible:
            self.show_dock()

    # ---------------------------------------------------------------- state
    def tick(self):
        if not self.enabled:
            return True
        self.refresh()
        # Check auto-hide
        if self.visible and self.target_visible:
            if time.monotonic() - self.last_activity > self.hide_delay:
                self.hide_dock()
        return True

    def refresh(self):
        bg(clients, self.apply)

    def lookup(self, cls):
        c = cls.lower()
        return self.index.get(c) or self.index.get(c.replace("_", "-")) or self.index.get(c.replace("-", "_"))

    def apply(self, wins):
        running = {}
        for w in wins:
            did = self.lookup(w["class"]) or ("class:" + w["class"].lower())
            running.setdefault(did, []).append(w)
        items = []
        for did in self.cfg.get("pinned", []):
            info = Gio.DesktopAppInfo.new(did)
            if info is None:
                continue
            items.append({"id": did, "info": info, "wins": running.pop(did, []), "pinned": True,
                          "name": info.get_name(), "class": ""})
        extra = []
        for did, ws in running.items():
            info = Gio.DesktopAppInfo.new(did) if not did.startswith("class:") else None
            extra.append({"id": did, "info": info, "wins": ws, "pinned": False,
                          "name": info.get_name() if info else ws[0]["class"], "class": ws[0]["class"]})
        sig = tuple((i["id"], len(i["wins"]), i["pinned"]) for i in items + extra)
        if sig == self.sig:
            return
        self.sig = sig
        self.rebuild(items, extra)

    # ---------------------------------------------------------------- ui
    def rebuild(self, items, extra):
        clear(self.box)
        self.box.append(self.special("view-app-grid-symbolic", "Apps", self.open_launcher))
        self.box.append(self.sep())
        for it in items:
            self.box.append(self.make(it))
        if extra:
            self.box.append(self.sep())
            for it in extra:
                self.box.append(self.make(it))
        self.box.append(self.sep())
        self.box.append(self.special("preferences-system", "Settings", lambda: fire(POPUP, "settings")))

    def sep(self):
        s = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        s.add_css_class("docksep")
        return s

    def icon(self, it):
        img = Gtk.Image()
        info = it.get("info")
        if info is not None and info.get_icon() is not None:
            img.set_from_gicon(info.get_icon())
        else:
            img.set_from_icon_name((it.get("class") or "").lower() or "application-x-executable")
        img.set_pixel_size(self.size)
        return img

    def make(self, it):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        btn = Gtk.Button()
        btn.add_css_class("dockbtn")
        btn.set_child(self.icon(it))
        btn.set_tooltip_text(it["name"])
        btn.connect("clicked", lambda _b, it=it: self.activate(it))
        # Track activity on hover
        hover = Gtk.EventControllerMotion.new()
        hover.connect("enter", lambda *_a: self.record_activity())
        btn.add_controller(hover)
        right = Gtk.GestureClick.new()
        right.set_button(3)
        right.connect("pressed", lambda *_a, it=it: self.toggle_pin(it))
        btn.add_controller(right)
        col.append(btn)
        dot = Gtk.Box()
        dot.add_css_class("dockdot")
        dot.set_halign(Gtk.Align.CENTER)
        dot.set_opacity(1.0 if it["wins"] else 0.0)
        col.append(dot)
        return col

    def special(self, icon_name, tip, fn):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        btn = Gtk.Button()
        btn.add_css_class("dockbtn")
        img = Gtk.Image.new_from_icon_name(icon_name)
        img.set_pixel_size(self.size)
        btn.set_child(img)
        btn.set_tooltip_text(tip)
        btn.connect("clicked", lambda _b: fn())
        hover = Gtk.EventControllerMotion.new()
        hover.connect("enter", lambda *_a: self.record_activity())
        btn.add_controller(hover)
        col.append(btn)
        dot = Gtk.Box()
        dot.add_css_class("dockdot")
        dot.set_opacity(0.0)
        col.append(dot)
        return col

    # ---------------------------------------------------------------- actions
    def open_launcher(self):
        args = ["rofi", "-show", "drun"]
        if os.path.exists(ROFI_THEME):
            args += ["-theme", ROFI_THEME]
        fire(*args)

    def activate(self, it):
        self.record_activity()
        if it["wins"]:
            best = sorted(it["wins"], key=lambda w: w["focus"])[0]
            if focus(best["address"]):
                GLib.timeout_add(200, lambda: (self.refresh(), False)[1])
                return
        info = it.get("info")
        if info is not None and info.get_filename():
            fire("gio", "launch", info.get_filename())
        GLib.timeout_add(1500, lambda: (self.refresh(), False)[1])

    def toggle_pin(self, it):
        if it["info"] is None:
            return
        pinned = self.cfg.setdefault("pinned", [])
        if it["id"] in pinned:
            pinned.remove(it["id"])
        else:
            pinned.append(it["id"])
        C.save(self.full)
        self.sig = None
        self.refresh()
