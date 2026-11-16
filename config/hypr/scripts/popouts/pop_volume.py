import json
import shutil

from glass import *

OUT = "@DEFAULT_AUDIO_SINK@"
INP = "@DEFAULT_AUDIO_SOURCE@"


def get(target):
    out = run("wpctl", "get-volume", target)
    try:
        return round(float(out.split()[1]) * 100), "MUTED" in out
    except Exception:
        return 0, False


def sinks():
    try:
        data = json.loads(run("pactl", "-f", "json", "list", "sinks"))
        return [(s["name"], s.get("description", s["name"])) for s in data]
    except Exception:
        return []


class Row:
    def __init__(self, target, icon_on, icon_off):
        self.target = target
        self.icon_on = icon_on
        self.icon_off = icon_off
        self.guard = False
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn = Gtk.Button()
        self.btn.add_css_class("mute")
        self.btn.set_label(icon_on)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.pct = Gtk.Label()
        self.pct.add_css_class("pct")
        self.box.append(self.btn)
        self.box.append(self.scale)
        self.box.append(self.pct)
        self.scale.connect("value-changed", self.changed)
        self.btn.connect("clicked", self.toggle)

    def refresh(self):
        bg(lambda: get(self.target), self.apply)

    def apply(self, res):
        v, m = res
        self.guard = True
        self.scale.set_value(v)
        self.guard = False
        self.pct.set_text(f"{v}%")
        self.btn.set_label(self.icon_off if m else self.icon_on)

    def changed(self, scale):
        if self.guard:
            return
        v = int(scale.get_value())
        self.pct.set_text(f"{v}%")
        fire("wpctl", "set-volume", self.target, f"{v / 100:.2f}")

    def toggle(self, _btn):
        def work():
            run("wpctl", "set-mute", self.target, "toggle")
            return get(self.target)

        bg(work, self.apply)


class VolumePopup(Popup):
    name = "volume"

    def build(self, root):
        root.append(label("OUTPUT", "sec"))
        self.out = Row(OUT, "󰕾", "󰝟")
        root.append(self.out.box)
        self.devs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        root.append(self.devs)
        root.append(Gtk.Separator())
        root.append(label("INPUT", "sec"))
        self.mic = Row(INP, "󰍬", "󰍭")
        root.append(self.mic.box)
        if shutil.which("pavucontrol"):
            root.append(Gtk.Separator())
            root.append(footer_button("󰒓  Open mixer", lambda: (fire("pavucontrol"), self.hide())))

    def on_show(self):
        self.out.refresh()
        self.mic.refresh()
        bg(lambda: (run("pactl", "get-default-sink").strip(), sinks()), self.build_devices)

    def build_devices(self, res):
        cur, devs = res
        clear(self.devs)
        for name, desc in devs:
            self.devs.append(item("󰄬" if name == cur else "󰓃", desc, "", name == cur,
                                  lambda n=name: self.pick(n)))

    def pick(self, name):
        def work():
            run("pactl", "set-default-sink", name)
            for line in run("pactl", "list", "short", "sink-inputs").splitlines():
                if line.strip():
                    fire("pactl", "move-sink-input", line.split()[0], name)
            return (name, sinks())

        bg(work, self.build_devices)
        self.out.refresh()
