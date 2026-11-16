import re
import subprocess

from glass import *

LIMIT = 40


def fetch():
    out = run("cliphist", "list", timeout=10)
    return [l for l in out.splitlines() if l.strip()]


def describe(line):
    _id, _, prev = line.partition("\t")
    prev = prev.strip()
    m = re.match(r"^\[\[ binary data (.*) \]\]$", prev)
    if m:
        dims = re.search(r"(\d+x\d+)", m.group(1))
        return "󰋩", "Image" + (f" · {dims.group(1)}" if dims else "")
    one = " ".join(prev.split())
    if len(one) > 90:
        one = one[:89] + "…"
    return "󰆏", one or "(empty)"


def copy_entry(line):
    try:
        data = subprocess.run(["cliphist", "decode"], input=(line + "\n").encode(),
                              capture_output=True, env=ENV, timeout=10).stdout
        cmd = ["wl-copy"]
        if data.startswith(b"\x89PNG"):
            cmd += ["--type", "image/png"]
        elif data.startswith(b"\xff\xd8"):
            cmd += ["--type", "image/jpeg"]
        subprocess.run(cmd, input=data, env=ENV, timeout=10)
    except Exception:
        pass


class ClipboardPopup(Popup):
    name = "clipboard"
    width = 440
    centered = True
    top = 110

    def build(self, root):
        self.lines = []
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.append(label("Clipboard", "title", hexpand=True))
        clr = Gtk.Button(label="Clear")
        clr.add_css_class("chip")
        clr.connect("clicked", lambda _b: self.wipe())
        head.append(clr)
        root.append(head)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search")
        self.entry.connect("changed", lambda _e: self.render())
        self.entry.connect("activate", lambda _e: self.pick_first())
        root.append(self.entry)

        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.list.append(label("Loading…", "dimtext"))
        root.append(scrolled(self.list, 420))

    def on_show(self):
        self.entry.set_text("")
        self.entry.grab_focus()
        self.refresh()

    def refresh(self):
        bg(fetch, self.set_lines)

    def set_lines(self, lines):
        self.lines = lines
        self.render()

    def filtered(self):
        q = self.entry.get_text().strip().lower()
        return [l for l in self.lines if q in l.lower()][:LIMIT]

    def render(self):
        clear(self.list)
        rows = self.filtered()
        if not rows:
            self.list.append(label("Nothing copied yet" if not self.lines else "No matches", "dimtext"))
            return
        for line in rows:
            icon, text = describe(line)
            self.list.append(item(icon, text, "", False, lambda l=line: self.pick(l)))

    def pick(self, line):
        self.hide()
        bg(lambda: copy_entry(line))

    def pick_first(self):
        rows = self.filtered()
        if rows:
            self.pick(rows[0])

    def wipe(self):
        bg(lambda: run("cliphist", "wipe"), lambda _r: self.refresh())
