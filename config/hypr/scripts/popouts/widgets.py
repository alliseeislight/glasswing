import calendar
import datetime
import glob
import json
import os
import random
import urllib.request

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from glass import *
import shell_cfg as C

WTTR = os.environ.get("GLASS_WTTR_URL", "https://wttr.in/?format=j1")
CACHE = os.path.expanduser("~/.cache/glass/weather.json")
CARD_W = 188
GRID_W = CARD_W * 2 + 12

ICONS = [
    ({113}, "󰖙"), ({116}, "󰖕"), ({119, 122}, "󰖐"), ({143, 248, 260}, "󰖑"),
    ({200, 386, 389, 392, 395}, "󰖓"),
    ({179, 182, 185, 227, 230, 281, 284, 311, 314, 317, 320, 323, 326, 329, 332, 335, 338,
      350, 362, 365, 368, 371, 374, 377}, "󰖘"),
]


def icon_for(code):
    for codes, glyph in ICONS:
        if code in codes:
            return glyph
    return "󰖗"


def parse_wttr(data, units="metric"):
    cur = data["current_condition"][0]
    day = data["weather"][0]
    f = "F" if units == "imperial" else "C"
    area = (data.get("nearest_area") or [{}])[0].get("areaName", [{"value": ""}])[0]["value"]
    code = int(cur.get("weatherCode", 0))
    return {
        "city": area,
        "temp": int(float(cur["temp_" + f])),
        "desc": cur["weatherDesc"][0]["value"],
        "hi": int(float(day["maxtemp" + f])),
        "lo": int(float(day["mintemp" + f])),
        "icon": icon_for(code),
    }


def fetch_weather(units):
    try:
        req = urllib.request.Request(WTTR, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
        data = json.loads(raw)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "wb") as f:
            f.write(raw)
        return parse_wttr(data, units)
    except Exception:
        try:
            with open(CACHE) as f:
                return parse_wttr(json.load(f), units)
        except Exception:
            return None


def cover(path, w, h):
    info = GdkPixbuf.Pixbuf.get_file_info(path)
    iw, ih = info[1], info[2]
    k = max(w / iw, h / ih)
    sw, sh = max(w, int(iw * k + 0.5)), max(h, int(ih * k + 0.5))
    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
    return pix.new_subpixbuf((sw - w) // 2, (sh - h) // 2, w, h)


def card(css="wcard"):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class(css)
    return box


class CalendarCard:
    def __init__(self):
        self.box = card()
        self.box.set_size_request(CARD_W, CARD_W)
        self.month = label("", "wmonth")
        self.box.append(self.month)
        self.grid = Gtk.Grid()
        self.grid.set_column_homogeneous(True)
        self.grid.set_row_spacing(1)
        self.box.append(self.grid)
        self.day = None
        self.render()
        GLib.timeout_add_seconds(60, self.tick)

    def tick(self):
        if self.day != datetime.date.today():
            self.render()
        return True

    def render(self):
        today = datetime.date.today()
        self.day = today
        self.month.set_text(calendar.month_name[today.month].upper())
        clear(self.grid)
        for i, d in enumerate("SMTWTFS"):
            self.grid.attach(label(d, "wk2", xalign=0.5), i, 0, 1, 1)
        dates = list(calendar.Calendar(firstweekday=6).itermonthdates(today.year, today.month))
        dates += [dates[-1] + datetime.timedelta(days=i + 1) for i in range(42 - len(dates))]
        for idx, d in enumerate(dates[:42]):
            lab = label(str(d.day), "wday", xalign=0.5)
            lab.set_halign(Gtk.Align.CENTER)
            if d.month != today.month:
                lab.add_css_class("dim")
            if d == today:
                lab.add_css_class("today")
            self.grid.attach(lab, idx % 7, 1 + idx // 7, 1, 1)


class WeatherCard:
    def __init__(self, units):
        self.units = units
        self.box = card()
        self.box.set_size_request(CARD_W, CARD_W)
        self.city = label("Weather", "wcity")
        self.city.set_ellipsize(Pango.EllipsizeMode.END)
        self.temp = label("--°", "wtemp")
        self.icon = label("󰖐", "wicon")
        self.desc = label("", "wcond")
        self.desc.set_ellipsize(Pango.EllipsizeMode.END)
        self.hl = label("", "wcond")
        for w in (self.city, self.temp):
            self.box.append(w)
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.box.append(spacer)
        self.box.append(self.icon)
        self.box.append(self.desc)
        self.box.append(self.hl)
        self.refresh()
        GLib.timeout_add_seconds(1200, self.tick)

    def tick(self):
        self.refresh()
        return True

    def refresh(self):
        bg(lambda: fetch_weather(self.units), self.apply)

    def apply(self, w):
        if not w:
            self.desc.set_text("No weather data")
            return
        self.city.set_text(w["city"] or "Weather")
        self.temp.set_text(f"{w['temp']}°")
        self.icon.set_text(w["icon"])
        self.desc.set_text(w["desc"])
        self.hl.set_text(f"H:{w['hi']}°  L:{w['lo']}°")


class PhotoCard:
    def __init__(self, folder):
        self.files = []
        for ext in ("jpg", "jpeg", "png", "webp"):
            self.files += glob.glob(os.path.join(folder, "*." + ext)) + glob.glob(os.path.join(folder, "*." + ext.upper()))
        self.box = None
        if not self.files:
            return
        self.box = card("wphoto")
        self.pic = Gtk.Picture()
        self.pic.set_size_request(GRID_W, 150)
        self.pic.set_can_shrink(False)
        self.pic.set_content_fit(Gtk.ContentFit.COVER)
        self.pic.set_overflow(Gtk.Overflow.HIDDEN)
        self.pic.add_css_class("wphotoimg")
        self.box.append(self.pic)
        self.box.set_overflow(Gtk.Overflow.HIDDEN)
        self.next()
        GLib.timeout_add_seconds(900, self.tick)

    def tick(self):
        self.next()
        return True

    def next(self):
        path = random.choice(self.files)

        def load():
            try:
                return cover(path, GRID_W, 150)
            except Exception:
                return None

        bg(load, lambda pix: self.pic.set_paintable(Gdk.Texture.new_for_pixbuf(pix)) if pix is not None else None)


class Widgets:
    def __init__(self, app):
        self.win = None
        cfg = C.load()["widgets"]
        if not cfg.get("enabled", True):
            return
        win = Gtk.ApplicationWindow(application=app)
        win.add_css_class("widgets")
        LS.init_for_window(win)
        LS.set_namespace(win, "glass-widget")
        LS.set_layer(win, LS.Layer.BOTTOM)
        LS.set_anchor(win, LS.Edge.TOP, True)
        LS.set_anchor(win, LS.Edge.LEFT, True)
        LS.set_margin(win, LS.Edge.TOP, int(cfg.get("margin_top", 56)))
        LS.set_margin(win, LS.Edge.LEFT, int(cfg.get("margin_left", 20)))
        LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)

        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(12)
        self.cal = CalendarCard()
        self.wx = WeatherCard(cfg.get("units", "metric"))
        grid.attach(self.cal.box, 0, 0, 1, 1)
        grid.attach(self.wx.box, 1, 0, 1, 1)
        self.photo = PhotoCard(os.path.expanduser(cfg.get("photo_dir", "~/Pictures/widgets")))
        if self.photo.box is not None:
            grid.attach(self.photo.box, 0, 1, 2, 1)
        win.set_child(grid)
        self.win = win
        win.present()

    def set_enabled(self, on):
        if self.win is None:
            return
        if on:
            self.win.present()
        else:
            self.win.set_visible(False)
