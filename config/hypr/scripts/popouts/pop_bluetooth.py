import re
import shutil

from glass import *

MAC_NAME = re.compile(r"^([0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}$")


def icon_for(kind):
    kind = kind.lower()
    if "headset" in kind or "headphone" in kind:
        return "󰋋"
    if "keyboard" in kind:
        return "󰌌"
    if "mouse" in kind:
        return "󰦋"
    if "phone" in kind:
        return "󰏲"
    if "audio" in kind or "speaker" in kind:
        return "󰓃"
    return "󰂯"


def devices():
    out = run("bluetoothctl", "devices", "Paired")
    if not out.strip():
        out = run("bluetoothctl", "devices")
    res = []
    for line in out.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        mac, name = parts[1], parts[2]
        if MAC_NAME.match(name):
            continue
        info = run("bluetoothctl", "info", mac)
        kind = ""
        batt = ""
        for l in info.splitlines():
            l = l.strip()
            if l.startswith("Icon:"):
                kind = l.split(":", 1)[1].strip()
            elif l.startswith("Battery Percentage:") and "(" in l:
                batt = l[l.rfind("(") + 1:l.rfind(")")] + "%"
        res.append({"mac": mac, "name": name, "on": "Connected: yes" in info,
                    "icon": icon_for(kind), "batt": batt})
    res.sort(key=lambda d: (not d["on"], d["name"].lower()))
    return res


class BluetoothPopup(Popup):
    name = "bluetooth"

    def build(self, root):
        self.guard = False
        self.sw = Gtk.Switch()
        self.sw.set_valign(Gtk.Align.CENTER)
        self.sw.connect("state-set", self.on_power)
        root.append(title_row("Bluetooth", self.sw))

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.list.append(label("Loading…", "dimtext"))
        root.append(scrolled(self.list, 330))
        self.status = label("", "dimtext")
        root.append(self.status)

        if shutil.which("blueman-manager"):
            root.append(Gtk.Separator())
            root.append(footer_button("󰒓  Bluetooth settings", lambda: (fire("blueman-manager"), self.hide())))

    def on_show(self):
        self.say("")
        bg(lambda: "Powered: yes" in run("bluetoothctl", "show"), self.power_state)

    def power_state(self, on):
        self.guard = True
        self.sw.set_active(on)
        self.guard = False
        self.refresh()

    def say(self, text):
        self.status.set_text(text)

    def refresh_once(self):
        if self.visible():
            self.refresh()
        return False

    def on_power(self, _sw, state):
        if self.guard:
            return False
        bg(lambda: run("bluetoothctl", "power", "on" if state else "off"),
           lambda _r: GLib.timeout_add(1200, self.refresh_once))
        return False

    def refresh(self):
        if not self.sw.get_active():
            clear(self.list)
            self.list.append(label("Bluetooth is off", "dimtext"))
            return
        bg(devices, self.build_list)

    def build_list(self, devs):
        clear(self.list)
        if not devs:
            self.list.append(label("No paired devices", "dimtext"))
            return
        for d in devs:
            bits = []
            if d["batt"]:
                bits.append(d["batt"])
            if d["on"]:
                bits.append("󰄬")
            self.list.append(item(d["icon"], d["name"], "  ".join(bits), d["on"],
                                  lambda d=d: self.toggle_dev(d)))

    def toggle_dev(self, d):
        verb = "disconnect" if d["on"] else "connect"
        self.say(("Disconnecting from " if d["on"] else "Connecting to ") + d["name"] + "…")

        def done(res):
            rc, _t = res
            self.say("" if rc == 0 else "That didn't work — is the device on?")
            self.refresh()

        bg(lambda: run_rc("bluetoothctl", verb, d["mac"], timeout=25), done)
