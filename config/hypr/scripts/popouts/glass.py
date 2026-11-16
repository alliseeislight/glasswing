import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from gi.repository import Gtk4LayerShell as LS

import accent

# Clean environment for child processes: no venv, no layer-shell preload.
ENV = dict(os.environ)
ENV.pop("VIRTUAL_ENV", None)
ENV.pop("LD_PRELOAD", None)
ENV["PATH"] = "/usr/bin:/usr/local/bin:/bin"

# environment for launching real apps: full PATH, but no layer-shell preload
APP_ENV = dict(os.environ)
APP_ENV.pop("LD_PRELOAD", None)
APP_ENV.pop("VIRTUAL_ENV", None)

TOP_MARGIN = 12   # gap between top of screen and popup (just under the bar pills)
EDGE = 8          # minimum distance from the screen edges


def run(*a, timeout=15):
    try:
        return subprocess.run(a, capture_output=True, text=True, env=ENV, timeout=timeout).stdout
    except Exception:
        return ""


def run_rc(*a, timeout=30):
    try:
        p = subprocess.run(a, capture_output=True, text=True, env=ENV, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except Exception as e:
        return 1, str(e)


def fire(*a):
    try:
        subprocess.Popen(a, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=APP_ENV)
    except Exception:
        pass


def bg(fn, done=None):
    def work():
        res = fn()
        if done:
            GLib.idle_add(lambda: (done(res), False)[1])

    threading.Thread(target=work, daemon=True).start()


CSS = """
window.glass {
  background-color: rgba(20,22,32,0.42);
  background-image: linear-gradient(155deg, rgba(255,255,255,0.20), rgba(255,255,255,0.04) 55%, rgba(255,255,255,0.10));
  border-radius: 28px;
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow: inset 0 1px 0 @glass_accent_mid, inset 0 -1px 0 rgba(255,255,255,0.08);
}
.pad { padding: 16px 18px 14px 18px; }
label.title { color: white; font-size: 18px; font-weight: bold; }
label.sec { color: @glass_accent; font-size: 11px; font-weight: bold; margin: 2px 4px; }
label.dimtext { color: rgba(255,255,255,0.60); font-size: 12px; margin: 2px 4px; }
label.big { color: white; font-size: 34px; font-weight: bold; }
label.plain { color: white; }
button.mute { background: transparent; border: none; box-shadow: none; color: white; font-size: 20px; min-width: 36px; }
label.pct { color: white; font-weight: bold; min-width: 44px; }
button.dev, button.foot, button.nav {
  background: transparent;
  border: none;
  box-shadow: none;
  color: rgba(255,255,255,0.88);
  padding: 8px 10px;
  border-radius: 14px;
}
button.dev:hover, button.foot:hover, button.nav:hover { background-color: rgba(255,255,255,0.14); }
button.dev.current { background-color: @glass_accent_soft; color: white; font-weight: bold; }
button.chip {
  background-image: none;
  background-color: rgba(255,255,255,0.10);
  border: 1px solid rgba(255,255,255,0.14);
  box-shadow: none;
  color: rgba(255,255,255,0.85);
  padding: 8px 6px;
  border-radius: 16px;
}
button.chip:hover { background-color: rgba(255,255,255,0.18); }
button.chip.current { background-color: @glass_accent_soft; border: 1px solid @glass_accent_mid; color: white; font-weight: bold; }
separator { background-color: rgba(255,255,255,0.14); min-height: 1px; margin: 8px 4px; }
switch {
  background-color: rgba(255,255,255,0.22);
  border: 1px solid rgba(255,255,255,0.20);
  border-radius: 24px;
  min-width: 46px;
  min-height: 26px;
}
switch:checked { background-color: @glass_accent; }
switch slider {
  background-image: radial-gradient(circle at 35% 30%, #ffffff, #e9eef7 70%);
  border-radius: 24px;
  min-width: 22px;
  min-height: 22px;
  margin: 1px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.4);
}
entry {
  background-color: rgba(255,255,255,0.12);
  color: white;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.22);
  box-shadow: none;
  padding: 6px 12px;
  min-height: 22px;
}
entry:focus { border: 1px solid @glass_accent_mid; }
scale trough {
  background-color: rgba(255,255,255,0.16);
  background-image: linear-gradient(rgba(0,0,0,0.18), rgba(255,255,255,0.04));
  min-height: 12px;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.12);
}
scale highlight {
  background-image: linear-gradient(180deg, rgba(255,255,255,0.98), @glass_accent);
  border-radius: 12px;
}
scale slider {
  background-image: radial-gradient(circle at 35% 30%, #ffffff, #e9eef7 70%);
  min-width: 24px;
  min-height: 24px;
  border-radius: 24px;
  border: 1px solid rgba(255,255,255,0.9);
  box-shadow: 0 2px 8px rgba(0,0,0,0.45), inset 0 -2px 3px rgba(0,0,0,0.12);
}
progressbar trough {
  background-color: rgba(255,255,255,0.16);
  border: 1px solid rgba(255,255,255,0.12);
  min-height: 14px;
  border-radius: 14px;
}
progressbar progress {
  background-image: linear-gradient(180deg, rgba(255,255,255,0.98), @glass_accent);
  min-height: 14px;
  border-radius: 14px;
}
progressbar.charging progress { background-image: linear-gradient(180deg, #5be37d, #34c759); }
progressbar.low progress { background-image: linear-gradient(180deg, #ff8a80, #ff5f57); }
label.wk { color: rgba(255,255,255,0.50); font-size: 12px; font-weight: bold; min-width: 38px; }
label.day { color: white; font-size: 15px; min-width: 38px; min-height: 38px; border-radius: 38px; }
label.day.dim { color: rgba(255,255,255,0.28); }
label.day.today { background-color: @glass_accent; color: #101218; font-weight: bold; }
label.month { color: @glass_accent; font-size: 20px; font-weight: bold; }
label.year { color: rgba(255,255,255,0.55); font-size: 20px; }
window.dock {
  background-color: rgba(20,22,32,0.42);
  background-image: linear-gradient(155deg, rgba(255,255,255,0.20), rgba(255,255,255,0.04) 55%, rgba(255,255,255,0.10));
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow: inset 0 1px 0 @glass_accent_mid, inset 0 -1px 0 rgba(255,255,255,0.08);
  border-radius: 26px;
}
.dockpad { padding: 8px 12px 6px 12px; }
button.dockbtn { background: transparent; background-image: none; border: none; box-shadow: none; padding: 4px; border-radius: 14px; min-width: 52px; min-height: 52px; transition: background-color 120ms ease; }
button.dockbtn:hover { background-color: rgba(255,255,255,0.14); }
button.dockbtn image { transition: -gtk-icon-transform 120ms ease; }
button.dockbtn:hover image { -gtk-icon-transform: scale(1.04); }
.dockdot { background-color: rgba(255,255,255,0.85); min-width: 4px; min-height: 4px; border-radius: 4px; }
separator.docksep { min-width: 1px; min-height: 34px; background-color: rgba(255,255,255,0.22); margin: 10px 6px; }
window.widgets { background: transparent; }
.wcard {
  background-color: rgba(20,22,32,0.42);
  background-image: linear-gradient(155deg, rgba(255,255,255,0.20), rgba(255,255,255,0.04) 55%, rgba(255,255,255,0.10));
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow: inset 0 1px 0 @glass_accent_mid, inset 0 -1px 0 rgba(255,255,255,0.08);
  border-radius: 28px;
  padding: 14px 16px;
}
.wphoto {
  background-color: rgba(20,22,32,0.42);
  background-image: linear-gradient(155deg, rgba(255,255,255,0.20), rgba(255,255,255,0.04) 55%, rgba(255,255,255,0.10));
  border: 1px solid rgba(255,255,255,0.28);
  box-shadow: inset 0 1px 0 @glass_accent_mid, inset 0 -1px 0 rgba(255,255,255,0.08);
  border-radius: 28px;
  padding: 0;
}
.wphotoimg { border-radius: 28px; }
label.wmonth { color: @glass_accent; font-size: 12px; font-weight: bold; margin-bottom: 4px; }
label.wk2 { color: rgba(255,255,255,0.45); font-size: 10px; font-weight: bold; min-width: 20px; }
label.wday { color: white; font-size: 11px; min-width: 20px; min-height: 20px; border-radius: 20px; }
label.wday.dim { color: rgba(255,255,255,0.28); }
label.wday.today { background-color: @glass_accent; color: #101218; font-weight: bold; }
label.wcity { color: white; font-size: 14px; font-weight: bold; }
label.wtemp { color: white; font-size: 44px; font-weight: 300; }
label.wicon { color: white; font-size: 24px; }
label.wcond { color: rgba(255,255,255,0.75); font-size: 12px; }
.osdpad { padding: 12px 22px; }
window.glass.osd { border-radius: 40px; }
label.osdicon { color: white; font-size: 22px; min-width: 30px; }
button.swatch { min-width: 30px; min-height: 30px; padding: 0; border-radius: 30px; border: 2px solid rgba(255,255,255,0.25); box-shadow: none; background-image: none; }
button.swatch.on { border: 2px solid #ffffff; }
button.sw0 { background-color: #a8b8e6; }
button.sw1 { background-color: #9fd8c0; }
button.sw2 { background-color: #e8aebf; }
button.sw3 { background-color: #efbf9a; }
button.sw4 { background-color: #c3aee8; }
button.sw5 { background-color: #9fcfe8; }
button.sw6 { background-color: #d9cc9a; }
button.sw7 { background-color: #aeb8c4; }
button.thumbbtn { background: transparent; background-image: none; border: 2px solid transparent; box-shadow: none; padding: 2px; border-radius: 18px; }
button.thumbbtn:hover { background-color: rgba(255,255,255,0.12); }
button.thumbbtn.on { border: 2px solid @glass_accent; }
.thumb { border-radius: 14px; }

.notes-scrolled {
  background-color: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 16px;
}
.notes-textview {
  background-color: transparent;
  color: white;
  font-size: 14px;
  font-family: Inter;
  padding: 14px 16px;
}
.notes-textview:focus {
  background-color: rgba(255,255,255,0.06);
}
.notes-textview text {
  caret-color: @glass_accent;
}
button.chip.plus {
  background-color: @glass_accent_soft;
  border: 1px solid @glass_accent_mid;
  color: white;
  font-weight: bold;
  min-width: 36px;
}
button.chip.plus:hover {
  background-color: @glass_accent_mid;
}
button.chip.delete-pending {
  background-color: rgba(255,95,87,0.35);
  border: 1px solid #ff5f57;
  color: #ff8a80;
}
"""

_provider = Gtk.CssProvider()
_installed = False


def apply_css(rgb):
    global _installed
    _provider.load_from_data((accent.defines(rgb) + CSS).encode())
    if not _installed:
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        _installed = True


def screen_width():
    try:
        mons = Gdk.Display.get_default().get_monitors()
        return mons.get_item(0).get_geometry().width
    except Exception:
        return 1920


class Popup:
    """A glass card that is built once, then shown/hidden instantly under the clicked bar module."""

    name = "popup"
    width = 360

    def __init__(self, app):
        self.app = app
        self.hidden_at = 0.0
        self.was_active = False
        win = Gtk.ApplicationWindow(application=app)
        win.add_css_class("glass")
        LS.init_for_window(win)
        LS.set_namespace(win, "glass-popup")
        LS.set_layer(win, LS.Layer.TOP)
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_margin(win, LS.Edge.TOP, TOP_MARGIN)
        LS.set_margin(win, LS.Edge.LEFT, 100)
        LS.set_keyboard_mode(win, LS.KeyboardMode.ON_DEMAND)
        self.win = win

        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.root.add_css_class("pad")
        self.root.set_size_request(self.width, -1)
        win.set_child(self.root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda c, k, *a: self.hide() if k == Gdk.KEY_Escape else None)
        win.add_controller(keys)
        win.connect("notify::is-active", self._active_changed)
        win.connect("close-request", lambda w: (self.hide(), True)[1])

        self.build(self.root)

    # hooks for subclasses
    def build(self, root):
        pass

    def on_show(self):
        pass

    def _active_changed(self, win, _p):
        if win.is_active():
            self.was_active = True
        elif self.autohide and self.was_active and win.get_visible():
            self.hide()

    centered = False
    autohide = True
    top = TOP_MARGIN

    def place(self, x):
        sw = screen_width()
        if self.centered:
            left = int((sw - self.width) / 2)
        else:
            left = int(max(EDGE, min(x - self.width / 2, sw - self.width - EDGE)))
        LS.set_margin(self.win, LS.Edge.LEFT, left)
        LS.set_margin(self.win, LS.Edge.TOP, self.top)

    def visible(self):
        return self.win.get_visible()

    def show(self, x):
        self.place(x)
        self.was_active = False
        self.win.present()
        self.on_show()

    def hide(self):
        self.hidden_at = time.monotonic()
        self.was_active = False
        self.win.set_visible(False)

    def toggle(self, x):
        if self.visible():
            self.hide()
            return
        # clicking the bar steals focus first (which hides us); don't pop straight back up
        if time.monotonic() - self.hidden_at < 0.3:
            return
        self.show(x)


def label(text, css=None, xalign=0.0, hexpand=False):
    lab = Gtk.Label(label=text, xalign=xalign)
    if css:
        lab.add_css_class(css)
    lab.set_hexpand(hexpand)
    return lab


def title_row(text, switch=None):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    box.append(label(text, "title", hexpand=True))
    if switch is not None:
        box.append(switch)
    return box


def item(icon, text, trailing="", current=False, on_click=None):
    btn = Gtk.Button()
    btn.add_css_class("dev")
    if current:
        btn.add_css_class("current")
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    ic = label(icon, "plain")
    ic.set_size_request(24, -1)
    row.append(ic)
    name = label(text, "plain", hexpand=True)
    name.set_ellipsize(Pango.EllipsizeMode.END)
    row.append(name)
    if trailing:
        row.append(label(trailing, "plain"))
    btn.set_child(row)
    if on_click:
        btn.connect("clicked", lambda _b: on_click())
    return btn


def footer_button(text, on_click):
    btn = Gtk.Button()
    btn.add_css_class("foot")
    btn.set_child(label(text, "plain"))
    btn.connect("clicked", lambda _b: on_click())
    return btn


def clear(box):
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def scrolled(child, max_height=340):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    sw.set_propagate_natural_height(True)
    sw.set_max_content_height(max_height)
    sw.set_child(child)
    return sw
