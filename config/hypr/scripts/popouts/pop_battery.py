import glob
import os

from glass import *

PS = "/sys/class/power_supply"
BAT = (sorted(glob.glob(PS + "/BAT*")) or [None])[0]
PROFILES = [("power-saver", "󰾆", "Saver"), ("balanced", "󰾅", "Balanced"), ("performance", "󰓅", "Performance")]


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def ac_online():
    for p in glob.glob(PS + "/*"):
        if read(p + "/type") == "Mains" and read(p + "/online") == "1":
            return True
    return False


def snapshot():
    cap = int(read(BAT + "/capacity", "0") or 0)
    status = read(BAT + "/status", "Unknown")
    ac = ac_online()
    limit = read(BAT + "/charge_control_end_threshold")
    if status == "Charging":
        text, plugged = "Charging", True
    elif status == "Full":
        text, plugged = "Fully charged", True
    elif ac:
        text, plugged = "Plugged in", True
        if limit.isdigit() and int(limit) < 100:
            text += f" · limit {limit}%"
    else:
        text, plugged = "On battery", False
    left = ""
    for line in run("upower", "-e").splitlines():
        if "battery" in line:
            for l in run("upower", "-i", line.strip()).splitlines():
                l = l.strip()
                if l.startswith("time to empty:"):
                    left = l.split(":", 1)[1].strip() + " remaining"
                elif l.startswith("time to full:"):
                    left = l.split(":", 1)[1].strip() + " until full"
            break
    mode = run("powerprofilesctl", "get").strip()
    return cap, text, plugged, left, mode


class BatteryPopup(Popup):
    name = "battery"

    def build(self, root):
        self.timer = False
        root.append(title_row("Battery"))
        if BAT is None:
            root.append(label("No battery found", "dimtext"))
            self.chips = {}
            return
        self.big = label("", "big")
        self.state = label("", "dimtext")
        self.state.set_valign(Gtk.Align.END)
        self.state.set_margin_bottom(6)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.append(self.big)
        top.append(self.state)
        root.append(top)

        self.bar = Gtk.ProgressBar()
        root.append(self.bar)
        self.time = label("", "dimtext")
        root.append(self.time)

        root.append(Gtk.Separator())
        root.append(label("POWER MODE", "sec"))
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_homogeneous(True)
        self.chips = {}
        for key, icon, name in PROFILES:
            b = Gtk.Button()
            b.add_css_class("chip")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            inner.append(label(icon, "plain", xalign=0.5))
            inner.append(label(name, "plain", xalign=0.5))
            b.set_child(inner)
            b.connect("clicked", lambda _b, k=key: self.set_profile(k))
            row.append(b)
            self.chips[key] = b
        root.append(row)

    def on_show(self):
        if BAT is None:
            return
        self.refresh()
        if not self.timer:
            self.timer = True
            GLib.timeout_add_seconds(5, self.tick)

    def tick(self):
        if not self.visible():
            self.timer = False
            return False
        self.refresh()
        return True

    def refresh(self):
        bg(snapshot, self.apply)

    def apply(self, snap):
        cap, text, plugged, left, mode = snap
        self.big.set_text(f"{cap}%")
        self.state.set_text(text)
        self.bar.set_fraction(cap / 100)
        self.bar.remove_css_class("charging")
        self.bar.remove_css_class("low")
        if plugged:
            self.bar.add_css_class("charging")
        elif cap <= 20:
            self.bar.add_css_class("low")
        self.time.set_text(left)
        self.mark(mode)

    def mark(self, cur):
        for k, b in self.chips.items():
            if k == cur:
                b.add_css_class("current")
            else:
                b.remove_css_class("current")

    def set_profile(self, key):
        self.mark(key)
        bg(lambda: run("powerprofilesctl", "set", key))
