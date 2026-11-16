import re

from glass import *

HIDE_MS = 1400


def vol_state():
    out = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    try:
        return round(float(out.split()[1]) * 100), "MUTED" in out
    except Exception:
        return 0, False


def bright_state():
    m = re.search(r",(\d+)%", run("brightnessctl", "-m"))
    return int(m.group(1)) if m else 0


def act(kind, action):
    """Do the change, then report (icon, percent) for the overlay."""
    if kind == "volume":
        if action == "up":
            run("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+")
        elif action == "down":
            run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-")
        elif action == "mute":
            run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
        v, muted = vol_state()
        icon = "󰝟" if muted or v == 0 else ("󰕿" if v < 34 else ("󰖀" if v < 67 else "󰕾"))
        return icon, (0 if muted else v)
    if action == "up":
        run("brightnessctl", "set", "5%+")
    elif action == "down":
        run("brightnessctl", "-n1", "set", "5%-")
    b = bright_state()
    return ("󰃞" if b < 34 else ("󰃟" if b < 67 else "󰃠")), b


class OsdPopup(Popup):
    name = "osd"
    width = 300
    autohide = False

    def __init__(self, app):
        self.timer = None
        super().__init__(app)
        self.win.add_css_class("osd")
        LS.set_anchor(self.win, LS.Edge.TOP, False)
        LS.set_anchor(self.win, LS.Edge.LEFT, False)
        LS.set_anchor(self.win, LS.Edge.BOTTOM, True)
        LS.set_margin(self.win, LS.Edge.BOTTOM, 90)
        LS.set_keyboard_mode(self.win, LS.KeyboardMode.NONE)

    def build(self, root):
        root.remove_css_class("pad")
        root.add_css_class("osdpad")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.set_valign(Gtk.Align.CENTER)
        self.icon = label("󰕾", "osdicon", xalign=0.5)
        self.bar = Gtk.ProgressBar()
        self.bar.set_hexpand(True)
        self.bar.set_valign(Gtk.Align.CENTER)
        self.pct = label("", "pct", xalign=1.0)
        row.append(self.icon)
        row.append(self.bar)
        row.append(self.pct)
        root.append(row)

    def trigger(self, kind, action):
        bg(lambda: act(kind, action), self.update)

    def update(self, res):
        icon, pct = res
        self.icon.set_text(icon)
        self.bar.set_fraction(max(0, min(pct, 100)) / 100)
        self.pct.set_text(f"{pct}%")
        if not self.win.get_visible():
            self.win.present()
            GLib.idle_add(self.passthrough)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(HIDE_MS, self.expire)

    def passthrough(self):
        # let clicks go straight through the overlay
        try:
            import cairo
            surf = self.win.get_surface()
            if surf is not None:
                surf.set_input_region(cairo.Region())
        except Exception:
            pass
        return False

    def expire(self):
        self.timer = None
        self.win.set_visible(False)
        return False
