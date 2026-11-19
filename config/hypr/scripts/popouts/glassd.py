import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, GLib

import accent
from glass import apply_css, fire
from dock import Dock
from widgets import Widgets
from pop_battery import BatteryPopup
from pop_bluetooth import BluetoothPopup
from pop_calendar import CalendarPopup
from pop_clipboard import ClipboardPopup
from pop_settings import SettingsPopup
from pop_osd import OsdPopup
from pop_volume import VolumePopup
from pop_notes import NotesPopup
from pop_wifi import WifiPopup

REGISTRY = {
    "notes": NotesPopup,
    "wifi": WifiPopup,
    "bluetooth": BluetoothPopup,
    "battery": BatteryPopup,
    "calendar": CalendarPopup,
    "volume": VolumePopup,
    "osd": OsdPopup,
    "clipboard": ClipboardPopup,
    "settings": SettingsPopup,
}


class Daemon(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="local.glass.daemon")
        self.ready = False
        self.pending = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()

    def do_activate(self):
        if self.ready:
            return
        self.ready = True
        self.rgb = accent.compute()
        accent.write(self.rgb)
        apply_css(self.rgb)
        self.pops = {name: cls(self) for name, cls in REGISTRY.items()}
        try:
            self.dock = Dock(self)
            self.widgets = Widgets(self)
        except Exception as e:
            print("dock/widgets failed:", e)

        act = Gio.SimpleAction.new("toggle", GLib.VariantType.new("s"))
        act.connect("activate", self.on_toggle)
        self.add_action(act)
        osd = Gio.SimpleAction.new("osd", GLib.VariantType.new("s"))
        osd.connect("activate", self.on_osd)
        self.add_action(osd)

        # follow the wallpaper: wallust rewrites kitty's colours whenever it changes
        self.mon = Gio.File.new_for_path(accent.KITTY).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.mon.connect("changed", self.on_colors)

    def set_shell(self, which, on):
        # live apply for the Shell settings page
        try:
            if which == "dock":
                d = getattr(self, "dock", None)
                if d is not None and d.win is not None:
                    d.set_enabled(on)
                elif on:
                    self.dock = Dock(self)
            elif which == "widgets":
                w = getattr(self, "widgets", None)
                if w is not None and w.win is not None:
                    w.set_enabled(on)
                elif on:
                    self.widgets = Widgets(self)
            elif which == "bar":
                import subprocess
                if on:
                    # wait for a still-exiting waybar to finish, then start a fresh one (detached, never blocks the UI)
                    subprocess.Popen(["sh", "-c", "i=0; while pgrep -x waybar >/dev/null && [ $i -lt 20 ]; do sleep 0.25; i=$((i+1)); done; pgrep -x waybar >/dev/null || exec waybar"],
                                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["pkill", "-x", "waybar"], capture_output=True)
        except Exception as e:
            print("set_shell failed:", e)

    def on_toggle(self, _action, param):
        try:
            name, x = param.get_string().split()
            x = int(x)
        except Exception:
            return
        pop = self.pops.get(name)
        if not pop:
            return
        for other in self.pops.values():
            if (other is not pop and other.visible()
                    and not getattr(other, "always_on", False)):
                other.hide()
        pop.toggle(x)

    def on_osd(self, _action, param):
        try:
            kind, what = param.get_string().split()
        except Exception:
            return
        self.pops["osd"].trigger(kind, what)

    def on_colors(self, *_a):
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(600, self.refresh_accent)

    def refresh_accent(self):
        self.pending = None
        rgb = accent.compute()
        if rgb != self.rgb:
            self.rgb = rgb
            accent.write(rgb)
            apply_css(rgb)
            fire("pkill", "-SIGUSR2", "waybar")
            fire("swaync-client", "-rs")
        return False


Daemon().run()
