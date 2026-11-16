import calendar
import datetime

from glass import *

DAYS = "SMTWTFS"


class CalendarPopup(Popup):
    name = "calendar"
    width = 340

    def build(self, root):
        today = datetime.date.today()
        self.y, self.m = today.year, today.month

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        prev = Gtk.Button(label="󰅁")
        prev.add_css_class("nav")
        prev.connect("clicked", lambda _b: self.shift(-1))
        nxt = Gtk.Button(label="󰅂")
        nxt.add_css_class("nav")
        nxt.connect("clicked", lambda _b: self.shift(1))
        self.month = label("", "month")
        self.year = label("", "year")
        title = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title.append(self.month)
        title.append(self.year)
        tbtn = Gtk.Button()
        tbtn.add_css_class("nav")
        tbtn.set_child(title)
        tbtn.set_hexpand(True)
        tbtn.connect("clicked", lambda _b: self.go_today())
        head.append(tbtn)
        head.append(prev)
        head.append(nxt)
        root.append(head)

        self.grid = Gtk.Grid()
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_spacing(4)
        self.grid.set_column_spacing(2)
        root.append(self.grid)

        keys = Gtk.EventControllerKey()

        def on_key(_c, k, *_a):
            if k == Gdk.KEY_Left:
                self.shift(-1)
                return True
            if k == Gdk.KEY_Right:
                self.shift(1)
                return True
            if k == Gdk.KEY_Home:
                self.go_today()
                return True
            return False

        keys.connect("key-pressed", on_key)
        self.win.add_controller(keys)
        self.render()

    def on_show(self):
        self.go_today()

    def shift(self, delta):
        m = self.m + delta
        self.y += (m - 1) // 12
        self.m = (m - 1) % 12 + 1
        self.render()

    def go_today(self):
        t = datetime.date.today()
        self.y, self.m = t.year, t.month
        self.render()

    def render(self):
        self.month.set_text(calendar.month_name[self.m])
        self.year.set_text(str(self.y))
        clear(self.grid)
        for i, d in enumerate(DAYS):
            self.grid.attach(label(d, "wk", xalign=0.5), i, 0, 1, 1)
        today = datetime.date.today()
        dates = list(calendar.Calendar(firstweekday=6).itermonthdates(self.y, self.m))
        for idx, d in enumerate(dates):
            lab = label(str(d.day), "day", xalign=0.5)
            lab.set_halign(Gtk.Align.CENTER)
            if d.month != self.m:
                lab.add_css_class("dim")
            if d == today:
                lab.add_css_class("today")
            self.grid.attach(lab, idx % 7, 1 + idx // 7, 1, 1)
