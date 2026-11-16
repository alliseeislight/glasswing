import shutil

from glass import *

SIG = ["󰤟", "󰤢", "󰤥", "󰤨"]


def sig_icon(p):
    return SIG[min(3, p // 25)]


def unesc(s):
    return s.replace("\\:", ":").replace("\\\\", "\\")


def scan():
    out = run("nmcli", "-t", "-f", "IN-USE,SIGNAL,SECURITY,SSID", "dev", "wifi", "list", "--rescan", "no")
    nets = {}
    for line in out.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        use, sig, sec, ssid = parts
        ssid = unesc(ssid)
        if not ssid:
            continue
        sig = int(sig) if sig.isdigit() else 0
        cur = use.strip() == "*"
        old = nets.get(ssid)
        if old is None or cur or (not old["cur"] and sig > old["sig"]):
            nets[ssid] = {"ssid": ssid, "sig": sig, "sec": sec.strip() not in ("", "--"), "cur": cur}
    saved = set()
    for line in run("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").splitlines():
        name, _, typ = line.rpartition(":")
        if typ == "802-11-wireless":
            saved.add(unesc(name))
    ordered = sorted(nets.values(), key=lambda n: (not n["cur"], -n["sig"]))
    return ordered, saved


class WifiPopup(Popup):
    name = "wifi"

    def build(self, root):
        self.guard = False
        self.saved = set()
        self.pw_ssid = None
        self.sw = Gtk.Switch()
        self.sw.set_valign(Gtk.Align.CENTER)
        self.sw.connect("state-set", self.on_power)
        root.append(title_row("Wi-Fi", self.sw))

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.list.append(label("Loading…", "dimtext"))
        root.append(scrolled(self.list, 330))

        self.status = label("", "dimtext")
        root.append(self.status)

        self.pw_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("Password")
        self.entry.connect("activate", lambda _e: self.submit_password())
        go = Gtk.Button(label="Join")
        go.add_css_class("chip")
        go.connect("clicked", lambda _b: self.submit_password())
        self.pw_box.append(self.entry)
        self.pw_box.append(go)
        self.pw_box.set_visible(False)
        root.append(self.pw_box)

        if shutil.which("nm-connection-editor"):
            root.append(Gtk.Separator())
            root.append(footer_button("󰒓  Network settings", lambda: (fire("nm-connection-editor"), self.hide())))

    def on_show(self):
        self.pw_box.set_visible(False)
        self.entry.set_text("")
        self.say("")
        bg(lambda: run("nmcli", "radio", "wifi").strip() == "enabled", self.power_state)
        bg(lambda: run("nmcli", "dev", "wifi", "rescan"), lambda _r: GLib.timeout_add(2500, self.refresh_once))

    def power_state(self, on):
        self.guard = True
        self.sw.set_active(on)
        self.guard = False
        self.refresh()

    def refresh_once(self):
        if self.visible():
            self.refresh()
        return False

    def say(self, text):
        self.status.set_text(text)

    def on_power(self, _sw, state):
        if self.guard:
            return False
        bg(lambda: run("nmcli", "radio", "wifi", "on" if state else "off"),
           lambda _r: GLib.timeout_add(1800, self.refresh_once))
        return False

    def refresh(self):
        if not self.sw.get_active():
            clear(self.list)
            self.list.append(label("Wi-Fi is off", "dimtext"))
            return
        bg(scan, self.build_list)

    def build_list(self, res):
        nets, saved = res
        self.saved = saved
        clear(self.list)
        if not nets:
            self.list.append(label("No networks found", "dimtext"))
            return
        for n in nets:
            trailing = "󰄬" if n["cur"] else ("󰌾" if n["sec"] else "")
            self.list.append(item(sig_icon(n["sig"]), n["ssid"], trailing, n["cur"],
                                  lambda n=n: self.connect(n)))

    def connect(self, net, password=None):
        if net["cur"]:
            return
        ssid = net["ssid"]
        if net["sec"] and password is None and ssid not in self.saved:
            self.ask_password(ssid)
            return
        self.pw_box.set_visible(False)
        self.say(f"Connecting to {ssid}…")

        def work():
            args = ["nmcli", "dev", "wifi", "connect", ssid]
            if password:
                args += ["password", password]
            return run_rc(*args, timeout=35)

        def done(res):
            rc, _text = res
            if rc == 0:
                self.say(f"Connected to {ssid}")
                self.refresh()
            elif net["sec"] and password is None:
                self.ask_password(ssid)
            else:
                self.say("Couldn't connect — check the password")

        bg(work, done)

    def ask_password(self, ssid):
        self.pw_ssid = ssid
        self.say(f"Password for {ssid}")
        self.entry.set_text("")
        self.pw_box.set_visible(True)
        self.entry.grab_focus()

    def submit_password(self):
        pw = self.entry.get_text()
        if self.pw_ssid and pw:
            self.connect({"ssid": self.pw_ssid, "sec": True, "cur": False, "sig": 0}, pw)
