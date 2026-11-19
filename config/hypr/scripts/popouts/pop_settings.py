import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gio", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GdkPixbuf, Gio, Pango, PangoCairo

from glass import *
import settings_logic as L
import shell_cfg as SC

HOME = os.path.expanduser("~")
KITTY = shutil.which("kitty") or "kitty"

# App installer cache
APP_CACHE_FILE = os.path.join(HOME, ".cache", "glass-app-cache.json")
APP_CACHE_TTL = 86400  # 24 hours


def hypr_get(keys):
    out = {}
    for k in keys:
        try:
            d = json.loads(run("hyprctl", "getoption", k, "-j"))
            for t in ("int", "float"):
                if t in d:
                    out[k] = d[t]
                    break
        except Exception:
            pass
    return out


def apply_palette_files(path):
    """Re-run wallust on a wallpaper (video -> one frame first), then reload everything that reads it."""
    src = path
    if path.lower().endswith(L.VID):
        src = "/tmp/glass-wall-frame.png"
        run_rc("ffmpeg", "-y", "-ss", "1", "-i", path, "-frames:v", "1", src, timeout=30)
    rc, text = run_rc("wallust", "run", src, timeout=60)
    run("pkill", "-USR1", "kitty")
    run("pkill", "-SIGUSR2", "waybar")
    run("swaync-client", "-rs")
    run("hyprctl", "reload")
    return rc, text


# ---------------------------------------------------------------- pages
class Page:
    def __init__(self, owner):
        self.owner = owner
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.status = label("", "dimtext")
        self.build()
        self.box.append(self.status)

    def say(self, text):
        self.status.set_text(text)

    def build(self):
        pass

    def on_show(self):
        pass


def sec(text):
    return label(text.upper(), "sec")


class SliderRow:
    def __init__(self, page, title, key, lo, hi):
        self.page, self.key, self.guard = page, key, False
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        t = label(title, "plain")
        t.set_size_request(140, -1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.val = label("", "pct", xalign=1.0)
        self.box.append(t)
        self.box.append(self.scale)
        self.box.append(self.val)
        self.scale.connect("value-changed", self.changed)

    def set(self, v):
        self.guard = True
        self.scale.set_value(v)
        self.guard = False
        self.val.set_text(str(int(round(v))))

    def changed(self, scale):
        if self.guard:
            return
        v = int(round(scale.get_value()))
        self.val.set_text(str(v))
        self.page.queue(self.key, v)


class FloatSliderRow:
    def __init__(self, page, title, key, lo, hi, step=0.01, digits=2):
        self.page, self.key, self.guard = page, key, False
        self.step, self.digits = step, digits
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        t = label(title, "plain")
        t.set_size_request(140, -1)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.val = label("", "pct", xalign=1.0)
        self.box.append(t)
        self.box.append(self.scale)
        self.box.append(self.val)
        self.scale.connect("value-changed", self.changed)
        self.set(lo)

    def set(self, v):
        self.guard = True
        self.scale.set_value(float(v))
        self.guard = False
        self.val.set_text(f"{float(v):.{self.digits}f}")

    def changed(self, scale):
        if self.guard:
            return
        v = round(scale.get_value() / self.step) * self.step
        self.val.set_text(f"{v:.{self.digits}f}")
        self.page.queue(self.key, round(v, 4))


class LockPreview(Gtk.Overlay):
    """Small, Windows-style preview of what the login or lock screen will look like."""

    W, H = 320, 180

    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.state = {}
        self._bg_token = 0
        self._bg_timer = None
        self._bg_sig = None
        self._has_bg = False

        self.set_size_request(self.W, self.H)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_halign(Gtk.Align.START)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.add_css_class("preview")

        self.bg = Gtk.Picture()
        self.bg.set_size_request(self.W, self.H)
        self.bg.set_content_fit(Gtk.ContentFit.COVER)
        self.bg.set_hexpand(True)
        self.bg.set_vexpand(True)
        self.set_child(self.bg)

        self.layer = Gtk.DrawingArea()
        self.layer.set_size_request(self.W, self.H)
        self.layer.set_hexpand(True)
        self.layer.set_vexpand(True)
        self.layer.set_draw_func(self.draw)
        self.add_overlay(self.layer)

        GLib.timeout_add_seconds(1, self._tick)

    def set_state(self, state):
        self.state = dict(state or {})
        self.layer.queue_draw()
        if self._bg_timer:
            GLib.source_remove(self._bg_timer)
        self._bg_timer = GLib.timeout_add(110, self._render_bg)

    def _tick(self):
        if self.get_mapped():
            self.layer.queue_draw()
        return True

    def _source(self):
        st = self.state
        if self.mode == "sddm":
            path = str(st.get("wallpaper", "") or "")
            kind = str(st.get("wallpaper_kind", "image"))
        else:
            path = str(st.get("wallpaper", "screenshot") or "screenshot")
            if path == "screenshot":
                path = L.current_wallpaper()
            kind = "video" if path.lower().endswith(L.VID) else "image"
        return path, kind

    def _params(self):
        st = self.state
        if self.mode == "sddm":
            try:
                blur = max(0.0, min(12.0, float(st.get("blur", 48)) / 8.0))
            except (TypeError, ValueError):
                blur = 6.0
            return blur, 1.0, 1.0
        try:
            blur_size = float(st.get("blur_size", 8))
            passes = float(st.get("blur_passes", 4))
            blur = max(0.0, min(14.0, blur_size * 0.55 + max(0.0, passes - 1) * 0.65))
            bright = max(0.10, min(1.5, float(st.get("brightness", 0.72))))
            sat = max(0.0, min(2.0, 1.0 + float(st.get("vibrancy", 0.25))))
            return blur, bright, sat
        except (TypeError, ValueError):
            return 6.0, 0.72, 1.25

    def _render_bg(self):
        self._bg_timer = None
        path, kind = self._source()
        blur, bright, sat = self._params()
        sig = (path, kind, round(blur, 2), round(bright, 3), round(sat, 3))
        if sig == self._bg_sig:
            return False
        self._bg_sig = sig
        self._bg_token += 1
        token = self._bg_token

        if not path or not os.path.isfile(path):
            self._has_bg = False
            self.bg.set_paintable(None)
            self.layer.queue_draw()
            return False

        os.makedirs(os.path.join(HOME, ".cache", "glass"), exist_ok=True)
        out = os.path.join(HOME, ".cache", "glass", f"lock-preview-{self.mode}-{token}.png")

        def work():
            return self._make_bg(path, kind, blur, bright, sat, out)

        def done(result):
            if token != self._bg_token:
                if result:
                    try:
                        os.remove(result)
                    except OSError:
                        pass
                return
            if result:
                try:
                    pix = GdkPixbuf.Pixbuf.new_from_file(result)
                    self.bg.set_paintable(Gdk.Texture.new_for_pixbuf(pix))
                    self._has_bg = True
                except Exception:
                    self._has_bg = False
                    self.bg.set_paintable(None)
                try:
                    os.remove(result)
                except OSError:
                    pass
            else:
                self._has_bg = False
                self.bg.set_paintable(None)
            self.layer.queue_draw()

        bg(work, done)
        return False

    @staticmethod
    def _make_bg(src, kind, blur, brightness, saturation, out):
        frame = src
        temporary = ""
        try:
            if kind == "video" or src.lower().endswith(L.VID):
                if not shutil.which("ffmpeg"):
                    return ""
                temporary = out + ".frame.png"
                rc, _text = run_rc(
                    "ffmpeg", "-y", "-ss", "0.5", "-i", src, "-frames:v", "1",
                    "-vf", f"scale={LockPreview.W}:{LockPreview.H}:force_original_aspect_ratio=increase,"
                           f"crop={LockPreview.W}:{LockPreview.H}",
                    temporary, timeout=25,
                )
                if rc != 0 or not os.path.isfile(temporary):
                    return ""
                frame = temporary

            magick = shutil.which("magick") or shutil.which("convert")
            if not magick:
                return ""
            cmd = [
                magick, frame, "-auto-orient",
                "-resize", f"{LockPreview.W}x{LockPreview.H}^",
                "-gravity", "center",
                "-extent", f"{LockPreview.W}x{LockPreview.H}",
            ]
            if blur > 0.05:
                cmd += ["-blur", f"0x{blur:.1f}"]
            if abs(brightness - 1.0) > 0.01 or abs(saturation - 1.0) > 0.01:
                cmd += ["-modulate", f"{brightness * 100:.1f},{saturation * 100:.1f},100"]
            cmd.append(out)
            rc, _text = run_rc(*cmd, timeout=25)
            return out if rc == 0 and os.path.isfile(out) else ""
        except Exception:
            return ""
        finally:
            if temporary:
                try:
                    os.remove(temporary)
                except OSError:
                    pass

    @staticmethod
    def _rounded(cr, x, y, w, h, r):
        r = max(0.0, min(r, w / 2.0, h / 2.0))
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2.0, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2.0)
        cr.arc(x + r, y + h - r, r, math.pi / 2.0, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3.0 * math.pi / 2.0)
        cr.close_path()

    @staticmethod
    def _text(cr, text, x, y, size, color=(1, 1, 1, 1), center=True, bold=False):
        text = str(text)
        if not text:
            return
        layout = PangoCairo.create_layout(cr)
        layout.set_text(text, -1)
        font = Pango.FontDescription(f"Inter {max(1.0, float(size)):.1f}")
        font.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
        layout.set_font_description(font)
        tw, th = layout.get_pixel_size()
        if center:
            x -= tw / 2.0
            y -= th / 2.0
        cr.set_source_rgba(*color)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    def draw(self, _area, cr, width, height):
        if width <= 1 or height <= 1:
            return
        if self.mode == "sddm":
            try:
                dim = max(0.0, min(1.0, float(self.state.get("dim", 0.12))))
            except (TypeError, ValueError):
                dim = 0.12
            if dim > 0:
                cr.set_source_rgba(0, 0, 0, dim)
                cr.paint()
            self._draw_sddm(cr, width, height)
        else:
            self._draw_hyprlock(cr, width, height)

    def _draw_sddm(self, cr, width, height):
        st = self.state
        s = height / 900.0
        cx = width / 2.0
        clock_size = max(14.0, min(34.0, 130.0 * s))
        clock = self._qt_clock(st.get("clock_format", "h:mm"))
        clock_y = height * 0.16 + clock_size / 2.0
        self._text(cr, clock, cx, clock_y, clock_size, (1, 1, 1, 0.97), bold=True)

        date_size = max(7.0, min(15.0, 22.0 * s))
        date = self._qt_date(st.get("date_format", "ddd MMM d"))
        self._text(cr, date, cx, clock_y + clock_size / 2.0 + date_size / 2.0 + 5.0,
                   date_size, (1, 1, 1, 0.72))

        user = os.environ.get("USER") or "user"
        avatar_r = max(10.0, min(22.0, 36.0 * s))
        avatar_y = height * 0.70
        cr.arc(cx, avatar_y, avatar_r, 0, 2 * math.pi)
        cr.set_source_rgba(0.66, 0.72, 0.90, 0.82)
        cr.fill()
        self._text(cr, user[:1].upper(), cx, avatar_y, avatar_r * 0.95,
                   (0.06, 0.07, 0.10, 0.95), bold=True)
        self._text(cr, user, cx, avatar_y + avatar_r + 8.0,
                   max(7.0, min(12.0, 16.0 * s)), (1, 1, 1, 0.86))

        iw = max(100.0, min(width - 28.0, 280.0 * s))
        ih = max(14.0, min(24.0, 44.0 * s))
        ix, iy = cx - iw / 2.0, height * 0.86 - ih / 2.0
        self._rounded(cr, ix, iy, iw, ih, ih / 2.0)
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.25)
        cr.set_line_width(1.0)
        cr.stroke()
        self._text(cr, "Enter Password", cx, iy + ih / 2.0,
                   max(6.0, min(10.0, 13.0 * s)), (1, 1, 1, 0.55))

    def _draw_hyprlock(self, cr, width, height):
        st = self.state
        s = height / 900.0
        cx, cy = width / 2.0, height / 2.0

        def number(key, default, lo, hi):
            try:
                return max(lo, min(hi, float(st.get(key, default))))
            except (TypeError, ValueError):
                return default

        card_w = max(28.0, min(width - 18.0, number("card_width", 440, 0, 1200) * s))
        card_h = max(28.0, min(height - 18.0, number("card_height", 380, 0, 1200) * s))
        card_x, card_y = cx - card_w / 2.0, cy + 10.0 * s - card_h / 2.0
        radius = max(0.0, min(card_w / 2.0, card_h / 2.0,
                              number("card_rounding", 36, 0, 200) * s))
        self._rounded(cr, card_x, card_y, card_w, card_h, radius)
        cr.set_source_rgba(0.08, 0.09, 0.13, number("card_opacity", 0.40, 0, 0.8))
        cr.fill_preserve()
        if number("card_border", 1, 0, 20) > 0:
            cr.set_source_rgba(1, 1, 1, 0.26)
            cr.set_line_width(max(0.8, number("card_border", 1, 0, 20) * s))
            cr.stroke()
        else:
            cr.new_path()

        clock_size = max(10.0, min(32.0, number("clock_size", 88, 24, 300) * s))
        clock = self._hypr_clock()
        self._text(cr, clock, cx, cy + 120.0 * s, clock_size, (1, 1, 1, 0.96), bold=True)

        if st.get("show_date", True):
            date_size = max(6.0, min(16.0, number("date_size", 18, 6, 80) * s))
            date = self._hypr_date()
            self._text(cr, date, cx, cy + 50.0 * s, date_size, (1, 1, 1, 0.70))

        if st.get("show_user", True):
            self._text(cr, os.environ.get("USER") or "user", cx, cy - 20.0 * s,
                       max(6.0, min(14.0, 16.0 * s)), (0.66, 0.72, 0.90, 0.95))

        iw = max(56.0, min(width - 24.0, number("input_width", 320, 80, 1200) * s))
        ih = max(12.0, min(30.0, number("input_height", 52, 20, 180) * s))
        ix, iy = cx - iw / 2.0, cy - 90.0 * s - ih / 2.0
        inset = max(0.0, min(iw / 2.0, ih / 2.0,
                            number("input_rounding", 26, 0, 100) * s))
        self._rounded(cr, ix, iy, iw, ih, inset)
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.fill_preserve()
        cr.set_source_rgba(0.66, 0.72, 0.90, 0.50)
        cr.set_line_width(1.0)
        cr.stroke()
        placeholder = re.sub(r"<[^>]+>", "", str(st.get("placeholder", "Enter password"))).strip()
        self._text(cr, placeholder or "Enter password", cx, iy + ih / 2.0,
                   max(6.0, min(11.0, 14.0 * s)), (1, 1, 1, 0.55))

    def _hypr_clock(self):
        st = self.state
        if st.get("clock_24h", True):
            fmt = "%H:%M"
        else:
            fmt = "%-I:%M"
        if st.get("clock_seconds", False):
            fmt += ":%S"
        if not st.get("clock_24h", True):
            fmt += " %p"
        return time.strftime(fmt)

    def _hypr_date(self):
        try:
            return time.strftime(str(self.state.get("date_format", "%A, %d %B")))
        except ValueError:
            return time.strftime("%A, %d %B")

    @staticmethod
    def _qt_clock(fmt):
        tokens = re.findall(r"HH|hh|H|h|mm|ss|AP|ap|.", str(fmt or "h:mm"))
        mapping = {
            "HH": "%H", "hh": "%I", "H": "%-H", "h": "%-I",
            "mm": "%M", "ss": "%S", "AP": "%p", "ap": "%p",
        }
        try:
            return time.strftime("".join(mapping.get(token, token) for token in tokens))
        except ValueError:
            return time.strftime("%-I:%M")

    @staticmethod
    def _qt_date(fmt):
        tokens = re.findall(r"dddd|ddd|dd|d|MMMM|MMM|MM|M|yyyy|yy|y|.", str(fmt or "ddd MMM d"))
        mapping = {
            "dddd": "%A", "ddd": "%a", "dd": "%d", "d": "%-d",
            "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": "%-m",
            "yyyy": "%Y", "yy": "%y", "y": "%Y",
        }
        try:
            return time.strftime("".join(mapping.get(token, token) for token in tokens))
        except ValueError:
            return time.strftime("%a %b %-d")


class StatGraph(Gtk.Box):
    """Compact donut-style pie chart with the percentage in the middle."""

    def __init__(self, title, color):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.color = tuple(max(0, min(1, c / 255.0)) for c in color)
        self.fraction = 0.0

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.append(label(title.upper(), "sec", hexpand=True))
        self.append(head)

        self.graph = Gtk.DrawingArea()
        self.graph.set_size_request(148, 148)
        self.graph.set_halign(Gtk.Align.CENTER)
        self.graph.add_css_class("statgraph")
        self.graph.set_draw_func(self.draw)
        self.append(self.graph)

        self.detail = label("", "dimtext")
        self.detail.set_wrap(True)
        self.detail.set_justify(Gtk.Justification.CENTER)
        self.append(self.detail)

    def update(self, fraction, detail):
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.detail.set_text(detail)
        self.graph.queue_draw()

    def draw(self, _area, cr, width, height):
        if width <= 8 or height <= 8:
            return
        r, g, b = self.color
        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) / 2.0 - 10.0
        thickness = max(12.0, radius * 0.30)
        ring = radius - thickness / 2.0
        start = -math.pi / 2.0

        cr.set_source_rgba(1, 1, 1, 0.085)
        cr.set_line_width(thickness)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)
        cr.arc(cx, cy, ring, 0, 2 * math.pi)
        cr.stroke()

        if self.fraction > 0:
            cr.set_source_rgba(r, g, b, 0.96)
            cr.set_line_width(thickness)
            cr.set_line_cap(cairo.LINE_CAP_ROUND if self.fraction < 0.98 else cairo.LINE_CAP_BUTT)
            end = start + 2 * math.pi * self.fraction
            if self.fraction >= 0.999:
                cr.arc(cx, cy, ring, 0, 2 * math.pi)
            else:
                cr.arc(cx, cy, ring, start, end)
            cr.stroke()

        font_size = max(22.0, min(34.0, radius * 0.42))
        LockPreview._text(cr, f"{self.fraction * 100:.0f}%", cx, cy - 5,
                          font_size, (1, 1, 1, 0.97), center=True, bold=True)
        LockPreview._text(cr, "USED", cx, cy + max(16.0, font_size * 0.62),
                          max(8.0, font_size * 0.34), (1, 1, 1, 0.50), center=True)


class LookPage(Page):
    SLIDERS = [
        ("Blur size", "decoration:blur:size", 1, 20),
        ("Blur passes", "decoration:blur:passes", 1, 6),
        ("Corner rounding", "decoration:rounding", 0, 32),
        ("Gaps between windows", "general:gaps_in", 0, 20),
        ("Gaps to screen edge", "general:gaps_out", 0, 40),
    ]

    def build(self):
        self.timer = None
        self.rows = []
        self.box.append(sec("Accent colour"))
        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.auto_btn = Gtk.Button(label="Follow wallpaper")
        self.auto_btn.add_css_class("chip")
        self.auto_btn.connect("clicked", lambda _b: self.set_accent("auto"))
        modes.append(self.auto_btn)
        self.box.append(modes)
        sw = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        sw.set_margin_top(4)
        self.swatches = []
        for i, hexv in enumerate(L.SWATCHES):
            b = Gtk.Button()
            b.add_css_class("swatch")
            b.add_css_class(f"sw{i}")
            b.connect("clicked", lambda _b, h=hexv: self.set_accent("manual", h))
            sw.append(b)
            self.swatches.append((b, hexv))
        self.box.append(sw)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Glass & layout"))
        for title, key, lo, hi in self.SLIDERS:
            r = SliderRow(self, title, key, lo, hi)
            self.rows.append(r)
            self.box.append(r.box)
        reset = Gtk.Button(label="Reset to defaults")
        reset.add_css_class("chip")
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", lambda _b: self.reset())
        self.box.append(reset)

    def on_show(self):
        self.mark_accent()
        keys = [r.key for r in self.rows]
        bg(lambda: hypr_get(keys), self.fill)

    def fill(self, vals):
        for r in self.rows:
            if r.key in vals:
                r.set(vals[r.key])

    def mark_accent(self):
        st = L.load_settings()
        manual = st.get("accent_mode") == "manual"
        cur = (st.get("accent") or "").lower()
        (self.auto_btn.remove_css_class if manual else self.auto_btn.add_css_class)("current")
        for b, hexv in self.swatches:
            (b.add_css_class if manual and hexv == cur else b.remove_css_class)("on")

    def set_accent(self, mode, hexv=None):
        st = L.load_settings()
        st["accent_mode"] = mode
        if hexv:
            st["accent"] = hexv
        L.save_settings(st)
        self.mark_accent()
        self.owner.app.refresh_accent()
        self.say("Accent follows your wallpaper" if mode == "auto" else "Accent set")

    def queue(self, key, value):
        st = L.load_settings()
        st.setdefault("hypr", {})[key] = value
        L.save_settings(st)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(500, self.apply)

    def apply(self):
        self.timer = None

        def work():
            L.write_atomic(L.USER_LUA, L.lua_text(L.load_settings().get("hypr", {})))
            run("hyprctl", "reload")
            return run("hyprctl", "configerrors").strip()

        def done(err):
            self.say("Applied" if not err else "Hyprland rejected a value: " + err.splitlines()[0][:110])

        self.say("Applying…")
        bg(work, done)
        return False

    def reset(self):
        st = L.load_settings()
        st["hypr"] = {}
        L.save_settings(st)
        self.say("Resetting…")

        def work():
            L.write_atomic(L.USER_LUA, L.lua_text({}))
            run("hyprctl", "reload")
            return hypr_get([r.key for r in self.rows])

        def done(vals):
            self.fill(vals)
            self.say("Back to defaults")

        bg(work, done)


class WallpaperPage(Page):
    def build(self):
        self.thumbs = {}
        self.buttons = {}
        self.cur = ""
        self.video_queue = queue.Queue()
        threading.Thread(target=self._video_worker, daemon=True).start()
        self.box.append(sec("Wallpaper"))
        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_max_children_per_line(3)
        self.flow.set_min_children_per_line(2)
        self.flow.set_column_spacing(8)
        self.flow.set_row_spacing(8)
        self.flow.set_homogeneous(True)
        self.box.append(self.flow)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nxt = Gtk.Button(label="Next wallpaper")
        nxt.add_css_class("chip")
        nxt.connect("clicked", lambda _b: self.next_wall())
        row.append(nxt)
        if shutil.which("waypaper"):
            wp = Gtk.Button(label="Open Waypaper")
            wp.add_css_class("chip")
            wp.connect("clicked", lambda _b: (fire("waypaper"), self.owner.hide()))
            row.append(wp)
        self.box.append(row)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Colour style"))
        self.pal_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pal_btns = {}
        for name in L.PALETTES:
            b = Gtk.Button(label=name)
            b.add_css_class("chip")
            b.connect("clicked", lambda _b, n=name: self.set_palette(n))
            self.pal_row.append(b)
            self.pal_btns[name] = b
        self.box.append(self.pal_row)

    def on_show(self):
        self.cur = L.current_wallpaper()
        if not self.buttons:
            self.fill_grid()
        self.mark()
        pal = L.palette_get()
        for n, b in self.pal_btns.items():
            (b.add_css_class if n == pal else b.remove_css_class)("current")

    def fill_grid(self):
        walls = L.wallpapers()
        if not walls:
            self.flow.append(label("Put images or videos in ~/Pictures/wallpapers", "dimtext"))
            return
        for path, is_video in walls:
            btn = Gtk.Button()
            btn.add_css_class("thumbbtn")
            btn.set_tooltip_text(os.path.basename(path))
            if is_video:
                holder = Gtk.Overlay()
                holder.set_size_request(self.TW, self.TH)
                holder.set_overflow(Gtk.Overflow.HIDDEN)
                holder.add_css_class("thumb")
                holder.add_css_class("thumbbox")
                pic = Gtk.Picture()
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.set_hexpand(True)
                pic.set_vexpand(True)
                holder.set_child(pic)
                badge = Gtk.Label(label="󰕧")
                badge.add_css_class("videobadge")
                badge.set_halign(Gtk.Align.CENTER)
                badge.set_valign(Gtk.Align.CENTER)
                holder.add_overlay(badge)
                btn.set_child(holder)
                self.video_queue.put((path, pic))
            else:
                pic = Gtk.Picture()
                pic.set_size_request(self.TW, self.TH)
                pic.set_content_fit(Gtk.ContentFit.COVER)
                pic.add_css_class("thumb")
                pic.set_overflow(Gtk.Overflow.HIDDEN)
                btn.set_child(pic)
                bg(lambda p=path: self.load_thumb(p), lambda pix, pc=pic: self.set_thumb(pc, pix))
            btn.connect("clicked", lambda _b, p=path: self.apply_wall(p))
            self.flow.append(btn)
            self.buttons[path] = btn

    def _video_worker(self):
        while True:
            path, pic = self.video_queue.get()
            try:
                thumb = self.video_thumb(path)
                pix = self.load_thumb(thumb) if thumb else None
            except Exception:
                pix = None
            GLib.idle_add(self._video_done, pic, pix)

    @staticmethod
    def _video_done(pic, pix):
        if pix is not None:
            pic.set_paintable(Gdk.Texture.new_for_pixbuf(pix))
        return False

    @staticmethod
    def video_thumb(path):
        if not shutil.which("ffmpeg"):
            return ""
        try:
            stat = os.stat(path)
            key = f"{path}|{stat.st_mtime_ns}|{stat.st_size}"
        except OSError:
            key = path
        digest = hashlib.sha256(key.encode("utf-8", "surrogateescape")).hexdigest()[:24]
        outdir = os.path.join(HOME, ".cache", "glass", "video-thumbs")
        out = os.path.join(outdir, digest + ".jpg")
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            return out
        os.makedirs(outdir, exist_ok=True)
        tmp = out + ".tmp.jpg"
        vf = "scale=480:270:force_original_aspect_ratio=increase,crop=480:270"
        for seek in ("1", "0"):
            rc, _text = run_rc(
                "ffmpeg", "-y", "-ss", seek, "-i", path, "-frames:v", "1",
                "-vf", vf, "-q:v", "3", tmp, timeout=25,
            )
            if rc == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
                try:
                    os.replace(tmp, out)
                    return out
                except OSError:
                    pass
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ""

    TW, TH = 172, 97

    @staticmethod
    def load_thumb(path, tw=None, th=None):
        try:
            tw = tw or WallpaperPage.TW
            th = th or WallpaperPage.TH
            info = GdkPixbuf.Pixbuf.get_file_info(path)
            w, h = info[1], info[2]
            k = max(tw / w, th / h)
            sw, sh = max(tw, int(w * k + 0.5)), max(th, int(h * k + 0.5))
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, sw, sh, False)
            return pix.new_subpixbuf((sw - tw) // 2, (sh - th) // 2, tw, th)
        except Exception:
            return None

    @staticmethod
    def set_thumb(pic, pix):
        if pix is not None:
            pic.set_paintable(Gdk.Texture.new_for_pixbuf(pix))

    def mark(self):
        for p, b in self.buttons.items():
            (b.add_css_class if p == self.cur else b.remove_css_class)("on")

    def apply_wall(self, path):
        self.say("Applying wallpaper…")

        def work():
            rc, _t = run_rc("waypaper", "--wallpaper", path, timeout=40)
            if rc != 0:
                return rc
            apply_palette_files(path)
            return 0

        def done(rc):
            if rc == 0:
                self.cur = path
                self.mark()
                self.say("Wallpaper and colours updated")
            else:
                self.say("waypaper couldn't set it — is it installed and configured?")

        bg(work, done)

    def next_wall(self):
        script = os.path.join(L.HYPR, "scripts", "cycle_wall.sh")
        if os.path.exists(script):
            fire(script)
            self.say("Cycling wallpaper…")
            GLib.timeout_add(2500, lambda: (self.on_show(), False)[1])
        else:
            self.say("cycle_wall.sh not found")

    def set_palette(self, name):
        if not L.palette_set(name):
            self.say("Couldn't find the palette line in wallust.toml")
            return
        self.say("Regenerating colours…")
        wall = self.cur or L.current_wallpaper()
        if not wall:
            self.say("Palette saved — pick a wallpaper to apply it")
            return
        bg(lambda: apply_palette_files(wall), lambda _r: (self.say("Colour style applied"), self.on_show()))


class LockPage(Page):
    DATE_FORMATS = [
        ("Weekday, date", "%A, %d %B"),
        ("Weekday", "%A"),
        ("Day, month", "%d %B"),
        ("Short", "%d %b %Y"),
        ("ISO", "%Y-%m-%d"),
    ]

    def build(self):
        self.timer = None
        self.syncing = False
        self.chooser = None
        self.rows = []
        self.switches = {}
        self.date_btns = {}

        self.box.append(sec("Lock screen wallpaper"))
        self.preview = LockPreview("hyprlock")
        self.box.append(self.preview)
        self.wall_label = label("", "dimtext")
        self.box.append(self.wall_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for text, fn in (
            ("Blurred desktop", self.use_blurred),
            ("Use desktop wallpaper", self.use_desktop),
            ("Choose image…", self.choose_wall),
        ):
            b = Gtk.Button(label=text)
            b.add_css_class("chip")
            b.connect("clicked", lambda _b, f=fn: f())
            row.append(b)
        self.box.append(row)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Background"))
        self.slider("Blur size", "blur_size", 0, 20)
        self.slider("Blur passes", "blur_passes", 1, 6)
        self.slider("Brightness", "brightness", 0.10, 1.00, 0.01, 2)
        self.slider("Vibrancy", "vibrancy", 0.00, 0.80, 0.01, 2)
        self.slider("Noise", "noise", 0.000, 0.080, 0.005, 3)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Card"))
        self.slider("Width", "card_width", 320, 720)
        self.slider("Height", "card_height", 240, 620)
        self.slider("Opacity", "card_opacity", 0.00, 0.80, 0.01, 2)
        self.slider("Rounding", "card_rounding", 0, 64)
        self.slider("Border", "card_border", 0, 4)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Clock & labels"))
        self.switch("24-hour clock", "clock_24h")
        self.switch("Show seconds", "clock_seconds")
        self.switch("Show date", "show_date")
        self.switch("Show username", "show_user")
        self.slider("Clock size", "clock_size", 48, 150)
        self.slider("Date size", "date_size", 10, 34)

        self.date_flow = Gtk.FlowBox()
        self.date_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.date_flow.set_max_children_per_line(3)
        self.date_flow.set_min_children_per_line(2)
        self.date_flow.set_column_spacing(8)
        self.date_flow.set_row_spacing(8)
        for title, fmt in self.DATE_FORMATS:
            b = Gtk.Button(label=title)
            b.add_css_class("chip")
            b.connect("clicked", lambda _b, f=fmt: self.set_date_format(f))
            self.date_flow.append(b)
            self.date_btns[fmt] = b
        self.box.append(self.date_flow)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Password field"))
        self.placeholder = Gtk.Entry()
        self.placeholder.set_placeholder_text("Placeholder text")
        self.placeholder.connect("changed", self.placeholder_changed)
        self.box.append(self.placeholder)
        self.slider("Width", "input_width", 200, 600)
        self.slider("Height", "input_height", 36, 90)
        self.slider("Rounding", "input_rounding", 0, 45)

        reset = Gtk.Button(label="Reset lock screen")
        reset.add_css_class("chip")
        reset.set_halign(Gtk.Align.START)
        reset.set_margin_top(6)
        reset.connect("clicked", lambda _b: self.reset())
        self.box.append(reset)

    def slider(self, title, key, lo, hi, step=None, digits=2):
        if step is None:
            row = SliderRow(self, title, key, lo, hi)
        else:
            row = FloatSliderRow(self, title, key, lo, hi, step, digits)
        self.rows.append(row)
        self.box.append(row.box)

    def switch(self, title, key):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.append(label(title, "plain", hexpand=True))
        sw = Gtk.Switch()
        sw.set_valign(Gtk.Align.CENTER)
        sw.connect("state-set", lambda _s, state, k=key: self.flip(k, state))
        row.append(sw)
        self.box.append(row)
        self.switches[key] = sw

    def on_show(self):
        st = L.load_lock_settings()
        self.syncing = True
        for row in self.rows:
            row.set(st.get(row.key, L.LOCK_DEFAULTS.get(row.key, 0)))
        for key, sw in self.switches.items():
            sw.set_active(bool(st.get(key, L.LOCK_DEFAULTS.get(key))))
        self.placeholder.set_text(str(st.get("placeholder", "")))
        self.mark_date(st.get("date_format", L.LOCK_DEFAULTS["date_format"]))
        self.refresh_preview(st)
        self.syncing = False

    def flip(self, key, state):
        if not self.syncing:
            self.queue(key, bool(state))
        return False

    def placeholder_changed(self, _entry):
        if not self.syncing:
            self.queue("placeholder", self.placeholder.get_text())

    def mark_date(self, fmt):
        for key, b in self.date_btns.items():
            (b.add_css_class if key == fmt else b.remove_css_class)("current")

    def set_date_format(self, fmt):
        self.mark_date(fmt)
        self.queue("date_format", fmt)

    def queue(self, key, value):
        if self.syncing:
            return
        st = L.load_lock_settings()
        st[key] = value
        L.save_lock_settings(st)
        self.refresh_preview(st)
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(400, self.apply)
        self.say("Saving lock screen…")

    def apply(self):
        self.timer = None
        try:
            L.apply_lock_settings(L.load_lock_settings())
        except Exception as e:
            self.say(str(e))
            return False
        self.say("Saved — changes appear next time you lock.")
        return False

    def reset(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        L.save_lock_settings(dict(L.LOCK_DEFAULTS))
        self.on_show()
        self.apply()

    def refresh_preview(self, st):
        path = str(st.get("wallpaper", "screenshot"))
        if path == "screenshot":
            src = L.current_wallpaper()
            if src and src.lower().endswith(L.VID):
                self.wall_label.set_text("Blurred desktop (from the current video wallpaper)")
            elif src:
                self.wall_label.set_text("Blurred desktop")
            else:
                self.wall_label.set_text("No desktop wallpaper found")
        else:
            self.wall_label.set_text(os.path.basename(path) or path)
        self.preview.set_state(st)

    def use_blurred(self):
        self.set_wallpaper("screenshot")

    def use_desktop(self):
        path = L.current_wallpaper()
        if not path or not os.path.isfile(path):
            self.say("No current desktop wallpaper was found.")
            return
        if path.lower().endswith(L.VID):
            out = os.path.join(HOME, ".local", "share", "glasswing", "lock-wallpaper.png")
            self.say("Extracting a frame from the video wallpaper…")

            def work():
                os.makedirs(os.path.dirname(out), exist_ok=True)
                rc, _t = run_rc("ffmpeg", "-y", "-ss", "1", "-i", path,
                                "-frames:v", "1", out, timeout=30)
                return rc == 0 and os.path.isfile(out)

            def done(ok):
                if ok:
                    self.set_wallpaper(out)
                else:
                    self.say("Couldn't extract a frame from the video wallpaper.")
            bg(work, done)
            return
        self.set_wallpaper(path)

    def choose_wall(self):
        chooser = Gtk.FileChooserNative(
            title="Choose lock screen wallpaper",
            transient_for=getattr(self.owner, "win", None),
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.set_modal(True)
        filt = Gtk.FileFilter()
        filt.set_name("Images")
        for ext in L.LOCK_IMG:
            filt.add_pattern("*" + ext)
            filt.add_pattern("*" + ext.upper())
        chooser.add_filter(filt)
        if os.path.isdir(L.WALLS):
            chooser.set_current_folder(Gio.File.new_for_path(L.WALLS))
        chooser.connect("response", self.wall_chosen)
        self.chooser = chooser
        chooser.show()

    def wall_chosen(self, chooser, response):
        self.chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        f = chooser.get_file()
        path = f.get_path() if f else ""
        if not path or not os.path.isfile(path):
            self.say("That image could not be opened.")
            return
        if not path.lower().endswith(L.LOCK_IMG):
            self.say("Choose a JPG, PNG, WebP, or BMP image.")
            return
        self.set_wallpaper(path)

    def set_wallpaper(self, path):
        self.queue("wallpaper", path)


class LoginPage(Page):
    DATE_FORMATS = [
        ("Weekday, date", "ddd MMM d"),
        ("Full date", "dddd, MMMM d"),
        ("ISO date", "yyyy-MM-dd"),
        ("Day/month/year", "dd/MM/yyyy"),
    ]

    def build(self):
        self.timer = None
        self.pending = {}
        self.syncing = False
        self.chooser = None
        self.rows = []
        self.date_btns = {}
        self.clock_key = ""
        self.date_key = ""
        self.preview_state = {}

        st = L.read_sddm_settings()
        self.ready = bool(st.get("theme"))

        self.box.append(sec("Display manager"))
        self.theme_label = label("", "plain")
        self.box.append(self.theme_label)
        note = label("Settings here apply to the SDDM login screen before you sign in.", "dimtext")
        note.set_wrap(True)
        self.box.append(note)

        if not self.ready:
            missing = label("No SDDM theme was detected. This page is only active on systems using SDDM.", "dimtext")
            missing.set_wrap(True)
            self.box.append(missing)
            return

        self.theme_label.set_text(f"Theme: {st.get('theme', '')}")
        self.box.append(sec("Login screen wallpaper"))
        self.preview = LockPreview("sddm")
        self.box.append(self.preview)
        self.wall_label = label("", "dimtext")
        self.box.append(self.wall_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for text, fn in (
            ("Use desktop wallpaper", self.use_desktop),
            ("Choose image/video…", self.choose_wall),
            ("Theme default", self.restore_default),
        ):
            b = Gtk.Button(label=text)
            b.add_css_class("chip")
            b.connect("clicked", lambda _b, f=fn: f())
            row.append(b)
        self.box.append(row)

        if st.get("blur_key") or st.get("dim_key"):
            self.box.append(Gtk.Separator())
            self.box.append(sec("Background"))
            if st.get("blur_key"):
                self.slider("Blur", st["blur_key"], 0, 64)
            if st.get("dim_key"):
                self.slider("Dim", st["dim_key"], 0.0, 0.8, 0.01, 2)

        if st.get("clock_key") or st.get("date_key"):
            self.box.append(Gtk.Separator())
            self.box.append(sec("Clock & date"))
            self.clock_key = st.get("clock_key", "")
            self.date_key = st.get("date_key", "")
            if self.clock_key:
                self.clock24 = self.switch_row("24-hour clock", self.clock_changed)
                self.clock_seconds = self.switch_row("Show seconds", self.clock_changed)
            if self.date_key:
                flow = Gtk.FlowBox()
                flow.set_selection_mode(Gtk.SelectionMode.NONE)
                flow.set_max_children_per_line(3)
                flow.set_min_children_per_line(2)
                flow.set_column_spacing(8)
                flow.set_row_spacing(8)
                for title, fmt in self.DATE_FORMATS:
                    b = Gtk.Button(label=title)
                    b.add_css_class("chip")
                    b.connect("clicked", lambda _b, f=fmt: self.set_date_format(f))
                    flow.append(b)
                    self.date_btns[fmt] = b
                self.box.append(flow)

    def slider(self, title, key, lo, hi, step=None, digits=2):
        if step is None:
            row = SliderRow(self, title, key, lo, hi)
        else:
            row = FloatSliderRow(self, title, key, lo, hi, step, digits)
        self.rows.append(row)
        self.box.append(row.box)

    def switch_row(self, title, callback):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.append(label(title, "plain", hexpand=True))
        sw = Gtk.Switch()
        sw.set_valign(Gtk.Align.CENTER)
        sw.connect("state-set", lambda _s, _state: callback())
        row.append(sw)
        self.box.append(row)
        return sw

    def on_show(self):
        if not self.ready:
            return
        st = L.read_sddm_settings()
        self.syncing = True
        self.theme_label.set_text(f"Theme: {st.get('theme', '')}")
        for row in self.rows:
            row.set(st.get(row.key, 0))
        if self.clock_key:
            self.clock24.set_active(bool(st.get("clock_24h")))
            self.clock_seconds.set_active(bool(st.get("clock_seconds")))
        self.mark_date(st.get("date_format", ""))
        self.preview_state = dict(st)
        self.refresh_preview(st)
        self.syncing = False

    def clock_changed(self):
        if self.syncing or not self.clock_key:
            return False
        fmt = "HH:mm" if self.clock24.get_active() else "h:mm"
        if self.clock_seconds.get_active():
            fmt += ":ss"
        self.queue(self.clock_key, fmt)
        return False

    def mark_date(self, fmt):
        for key, b in self.date_btns.items():
            (b.add_css_class if key == fmt else b.remove_css_class)("current")

    def set_date_format(self, fmt):
        self.mark_date(fmt)
        if self.date_key:
            self.queue(self.date_key, fmt)

    def queue(self, key, value):
        if self.syncing:
            return
        self.pending[key] = value

        st = dict(self.preview_state)
        if key == self.clock_key:
            st["clock_format"] = value
            st["clock_24h"] = "H" in str(value)
            st["clock_seconds"] = "s" in str(value)
        elif key == self.date_key:
            st["date_format"] = value
        elif key == st.get("blur_key"):
            st["blur"] = value
        elif key == st.get("dim_key"):
            st["dim"] = value
        self.preview_state = st
        self.refresh_preview(st)

        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(400, self.apply)
        self.say("Saving login screen…")

    def apply(self):
        self.timer = None
        updates, self.pending = self.pending, {}
        if not updates:
            return False
        try:
            L.set_sddm_values(updates)
        except Exception as e:
            self.say(str(e))
            return False
        self.say("Saved — changes appear on the next login screen.")
        return False

    def refresh_preview(self, st):
        path = str(st.get("wallpaper", ""))
        if not path or not os.path.isfile(path):
            self.wall_label.set_text("Theme background")
        else:
            name = os.path.basename(path) or path
            suffix = " (video)" if st.get("wallpaper_kind") == "video" else ""
            self.wall_label.set_text(f"{name}{suffix}")
        self.preview.set_state(st)

    def use_desktop(self):
        path = L.current_wallpaper()
        if not path or not os.path.isfile(path):
            self.say("No current desktop wallpaper was found.")
            return
        self.set_wallpaper(path)

    def choose_wall(self):
        chooser = Gtk.FileChooserNative(
            title="Choose login screen wallpaper",
            transient_for=getattr(self.owner, "win", None),
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.set_modal(True)
        filt = Gtk.FileFilter()
        filt.set_name("Images and videos")
        for ext in L.IMG + L.VID:
            filt.add_pattern("*" + ext)
            filt.add_pattern("*" + ext.upper())
        chooser.add_filter(filt)
        if os.path.isdir(L.WALLS):
            chooser.set_current_folder(Gio.File.new_for_path(L.WALLS))
        chooser.connect("response", self.wall_chosen)
        self.chooser = chooser
        chooser.show()

    def wall_chosen(self, chooser, response):
        self.chooser = None
        if response != Gtk.ResponseType.ACCEPT:
            return
        f = chooser.get_file()
        path = f.get_path() if f else ""
        if not path or not os.path.isfile(path):
            self.say("That file could not be opened.")
            return
        if not path.lower().endswith(L.IMG + L.VID):
            self.say("Choose an image or video file.")
            return
        self.set_wallpaper(path)

    def set_wallpaper(self, path):
        self.say("Copying the login wallpaper…")

        def work():
            try:
                L.set_sddm_wallpaper(path)
                return ""
            except Exception as e:
                return str(e)

        def done(error):
            if error:
                self.say(error)
                return
            self.say("Saved — changes appear on the next login screen.")
            self.on_show()

        bg(work, done)

    def restore_default(self):
        self.say("Restoring the theme default…")

        def work():
            try:
                L.set_sddm_default_wallpaper()
                return ""
            except Exception as e:
                return str(e)

        def done(error):
            if error:
                self.say(error)
                return
            self.say("Theme default restored.")
            self.on_show()

        bg(work, done)


class LinksPage(Page):
    LINKS = [
        ("󰖩", "Wi-Fi & networks", "nm-connection-editor", "networkmanager"),
        ("󰂯", "Bluetooth devices", "blueman-manager", "blueman"),
        ("󰕾", "Sound & audio", "pavucontrol", "pavucontrol"),
        ("󰍹", "Display & monitors", "hyprmod", "hyprmod"),
        ("󰃟", "GTK theme & cursor", "nwg-look", "nwg-look"),
        ("󰒓", "Hyprland (advanced)", "hyprmod", "hyprmod"),
    ]

    def build(self):
        self.box.append(sec("Open settings for"))
        for icon, title, cmd, pkg in self.LINKS:
            have = shutil.which(cmd) is not None
            hint = "" if have else f"yay -S {pkg}"
            btn = item(icon, title, hint, False, (lambda c=cmd: (fire(c), self.owner.hide())) if have else None)
            if not have:
                btn.set_sensitive(False)
            self.box.append(btn)
        self.box.append(Gtk.Separator())
        self.box.append(sec("Displays"))
        self.mon = label("Loading…", "dimtext")
        self.box.append(self.mon)

    def on_show(self):
        def fetch():
            try:
                return L.monitors_summary(json.loads(run("hyprctl", "monitors", "-j")))
            except Exception:
                return []

        bg(fetch, lambda m: self.mon.set_text("\n".join(m) or "No display info"))


class KeybindsPage(Page):
    def build(self):
        self.rows = []
        self.box.append(sec("Keybinds"))
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Search keys or actions")
        self.entry.connect("changed", lambda _e: self.render())
        self.box.append(self.entry)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.append(self.list)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        edit = Gtk.Button(label="Edit binds.lua")
        edit.add_css_class("chip")
        edit.connect("clicked", lambda _b: self.edit())
        rel = Gtk.Button(label="Reload Hyprland")
        rel.add_css_class("chip")
        rel.connect("clicked", lambda _b: (fire("hyprctl", "reload"), self.say("Reloaded")))
        row.append(edit)
        row.append(rel)
        self.box.append(row)

    def path(self):
        return os.path.join(L.HYPR, "components", "binds.lua")

    def on_show(self):
        self.entry.set_text("")
        bg(lambda: L.parse_binds(L.read(self.path())), self.set_rows)

    def set_rows(self, rows):
        self.rows = rows
        self.render()

    def render(self):
        clear(self.list)
        q = self.entry.get_text().strip().lower()
        shown = [r for r in self.rows if q in (r[0] + " " + r[1]).lower()][:60]
        if not shown:
            self.list.append(label("No keybinds found", "dimtext"))
            return
        for keys, act in shown:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            k = label(keys, "plain")
            k.set_size_request(190, -1)
            a = label(act, "dimtext", hexpand=True)
            a.set_ellipsize(Pango.EllipsizeMode.END)
            row.append(k)
            row.append(a)
            self.list.append(row)

    def edit(self):
        fire(KITTY, "-e", "micro", self.path())
        self.owner.hide()


class StartupPage(Page):
    def build(self):
        self.box.append(sec("Runs at login"))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.box.append(self.list)
        self.box.append(label("Changes apply the next time you log in.", "dimtext"))

    def path(self):
        return os.path.join(L.HYPR, "components", "autostart.lua")

    def on_show(self):
        bg(lambda: L.parse_autostart(L.read(self.path())), self.render)

    def render(self, items):
        clear(self.list)
        if not items:
            self.list.append(label("No simple autostart entries found", "dimtext"))
            return
        for it in items:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            name = label(it["text"], "plain", hexpand=True)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(it["enabled"])
            if it["protected"]:
                sw.set_sensitive(False)
                name.set_text(it["text"] + "  (needed by the popups)")
            sw.connect("state-set", lambda _s, state, i=it["idx"]: self.toggle(i, state))
            row.append(name)
            row.append(sw)
            self.list.append(row)

    def toggle(self, idx, state):
        p = self.path()
        L.backup_once(p)
        L.write_atomic(p, L.set_autostart(L.read(p), idx, state))
        self.say("Saved — takes effect next login")
        return False


class AppUninstallerPage(Page):
    def build(self):
        self.box.append(sec("App Uninstaller"))

        # Search entry
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text("Search installed packages...")
        self.search_entry.connect("changed", self.on_search_changed)
        self.search_entry.connect("activate", self.on_search_activate)
        self.box.append(self.search_entry)

        # Status label
        self.status_label = label("", "dimtext")
        self.box.append(self.status_label)

        # Results list
        self.results_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_max_content_height(420)
        scrolled.set_child(self.results_list)
        self.box.append(scrolled)

        # Action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button(label="Refresh installed list")
        refresh.add_css_class("chip")
        refresh.connect("clicked", self.refresh_packages)
        btn_row.append(refresh)

        orphan = Gtk.Button(label="Remove orphans")
        orphan.add_css_class("chip")
        orphan.connect("clicked", self.remove_orphans)
        btn_row.append(orphan)

        self.box.append(btn_row)

        # State
        self.packages = []  # list of dicts: {name, size, description}
        self.search_timer = None
        self.removing = set()

    def on_show(self):
        self.search_entry.set_text("")
        self.refresh_packages()

    def refresh_packages(self, _btn=None):
        self.say("Fetching installed packages...")

        def work():
            # Get explicitly installed packages with sizes
            out = run("pacman", "-Qqe", timeout=30)
            pkgs = [line.strip() for line in out.splitlines() if line.strip()]

            # Get size info for each package
            detailed = []
            for pkg in pkgs:
                try:
                    # Get package info including size
                    info_out = run("pacman", "-Qi", pkg, timeout=10)
                    size = "?"
                    desc = ""
                    for line in info_out.splitlines():
                        if line.startswith("Installed Size"):
                            size = line.split(":", 1)[1].strip()
                        elif line.startswith("Description"):
                            desc = line.split(":", 1)[1].strip()
                    detailed.append({"name": pkg, "size": size, "desc": desc})
                except Exception:
                    detailed.append({"name": pkg, "size": "?", "desc": ""})
            return detailed

        def done(result):
            if isinstance(result, list):
                self.packages = result
                self.say(f"Found {len(self.packages)} installed packages")
                self.render_results()
            else:
                self.say("Failed to fetch packages")

        bg(work, done)

    def on_search_changed(self, entry):
        if self.search_timer:
            GLib.source_remove(self.search_timer)
            self.search_timer = None
        self.search_timer = GLib.timeout_add(200, self._render_later)

    def _render_later(self):
        self.search_timer = None
        self.render_results()
        return False

    def on_search_activate(self, entry):
        self.render_results()

    def render_results(self):
        clear(self.results_list)
        query = self.search_entry.get_text().strip().lower()

        if not query:
            self.results_list.append(label("Type to search installed packages...", "dimtext"))
            return

        # Filter packages
        matches = [p for p in self.packages if query in p["name"].lower()][:50]

        if not matches:
            self.results_list.append(label(f"No installed packages matching '{query}'", "dimtext"))
            return

        for pkg in matches:
            is_removing = pkg["name"] in self.removing

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.set_margin_top(4)
            row.set_margin_bottom(4)

            # Package info
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            info_box.set_hexpand(True)

            name_label = label(pkg["name"], "plain", hexpand=True)
            name_label.set_ellipsize(Pango.EllipsizeMode.END)
            info_box.append(name_label)

            details = []
            if pkg["size"] != "?":
                details.append(f"Size: {pkg['size']}")
            if pkg["desc"]:
                details.append(pkg["desc"][:80])
            if details:
                detail_label = label(" · ".join(details), "dimtext", hexpand=True)
                detail_label.set_ellipsize(Pango.EllipsizeMode.END)
                info_box.append(detail_label)

            row.append(info_box)

            # Action
            if is_removing:
                badge = label("Removing...", "sec")
                badge.add_css_class("chip")
                row.append(badge)
            else:
                remove = Gtk.Button(label="Remove")
                remove.add_css_class("chip")
                remove.connect("clicked", lambda _b, p=pkg["name"]: self.remove_package(p))
                row.append(remove)

            self.results_list.append(row)

    def remove_package(self, pkg):
        self.removing.add(pkg)
        self.say(f"Waiting for authentication to remove {pkg}...")
        self.render_results()

        def work():
            # pkexec can show the desktop password dialog. yay/sudo cannot prompt
            # from this GTK popup because it has no controlling terminal.
            rc, out = run_rc(
                "pkexec", "/usr/bin/pacman", "-Rns", "--noconfirm", pkg, timeout=180
            )
            return rc, out, pkg

        def done(result):
            rc, out, pkg = result
            self.removing.discard(pkg)
            if rc == 0:
                self.say(f"Removed {pkg}")
                self.refresh_packages()
            else:
                lines = out.strip().splitlines()
                msg = lines[-1][:120] if lines else "unknown error"
                self.say(f"Failed to remove {pkg}: {msg}")
                self.render_results()

        bg(work, done)

    def remove_orphans(self, _btn=None):
        self.say("Removing orphaned packages...")

        def work():
            # Get orphans first
            out = run("pacman", "-Qtdq", timeout=30)
            orphans = [line.strip() for line in out.splitlines() if line.strip()]
            if not orphans:
                return 0, "No orphaned packages found"
            # Remove them through the desktop authentication agent.
            rc, out = run_rc(
                "pkexec", "/usr/bin/pacman", "-Rns", "--noconfirm", *orphans, timeout=300
            )
            return rc, out

        def done(result):
            rc, out = result
            if rc == 0:
                self.say("Orphans removed")
                self.refresh_packages()
            else:
                if "No orphaned" in out:
                    self.say("No orphaned packages")
                else:
                    lines = out.strip().splitlines()
                    msg = lines[-1][:120] if lines else "unknown error"
                    self.say(f"Failed: {msg}")

        bg(work, done)


# ---------------------------------------------------------------- window
class ShellPage(Page):
    def build(self):
        self.syncing = False
        self.sw = {}
        self.box.append(sec("Shell"))
        cfg = SC.load()
        for key, title in (("dock", "Dock"), ("widgets", "Desktop widgets"), ("bar", "Top bar")):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.append(label(title, "plain", hexpand=True))
            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            sw.set_active(bool(cfg[key].get("enabled", True)))
            sw.connect("state-set", lambda _s, state, k=key: self.toggle(k, state))
            row.append(sw)
            self.box.append(row)
            self.sw[key] = sw
        self.box.append(label("Changes apply right away and are remembered.", "dimtext"))

    def on_show(self):
        cfg = SC.load()
        self.syncing = True
        for key, sw in self.sw.items():
            sw.set_active(bool(cfg[key].get("enabled", True)))
        self.syncing = False

    def toggle(self, key, state):
        if self.syncing:
            return False
        cfg = SC.load()
        cfg[key]["enabled"] = bool(state)
        SC.save(cfg)
        self.owner.app.set_shell(key, bool(state))
        self.say({"dock": "Dock", "widgets": "Widgets", "bar": "Top bar"}[key] + (" on" if state else " off"))
        return False


class SystemPage(Page):
    INTERVAL = 2

    def build(self):
        self.timer = None
        self.busy = False
        try:
            ram_color = accent.compute()
        except Exception:
            ram_color = (168, 184, 230)

        self.box.append(sec("Memory"))
        self.ram = StatGraph("RAM", ram_color)
        self.box.append(self.ram)
        self.swap = label("", "dimtext")
        self.box.append(self.swap)

        self.box.append(Gtk.Separator())
        self.box.append(sec("Storage"))
        home_name = os.path.basename(L.HOME) or L.HOME
        self.disk = StatGraph(f"Disk · {home_name}", (159, 216, 192))
        self.box.append(self.disk)
        self.disk_extra = label("", "dimtext")
        self.box.append(self.disk_extra)

        self.box.append(Gtk.Separator())
        self.box.append(sec("At a glance"))
        self.glance = label("", "dimtext")
        self.glance.set_wrap(True)
        self.box.append(self.glance)

        refresh = Gtk.Button(label="Refresh now")
        refresh.add_css_class("chip")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", lambda _b: self.refresh())
        self.box.append(refresh)

    def on_show(self):
        self.refresh()
        if self.timer is None:
            self.timer = GLib.timeout_add_seconds(self.INTERVAL, self.tick)

    def tick(self):
        if not self.owner.visible():
            self.timer = None
            return False
        self.refresh()
        return True

    def refresh(self):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                return L.system_snapshot()
            except Exception:
                return None

        bg(work, self.apply)

    def apply(self, snap):
        self.busy = False
        if not snap:
            self.say("Couldn't read system stats")
            return

        ram = snap["ram"]
        swap = snap["swap"]
        disk = snap["disk"]
        self.ram.update(
            ram["fraction"],
            f"{L.human_size(ram['used'])} of {L.human_size(ram['total'])} used · "
            f"{L.human_size(ram['available'])} available",
        )
        if swap["total"]:
            self.swap.set_text(
                f"Swap: {L.human_size(swap['used'])} of {L.human_size(swap['total'])} used"
            )
        else:
            self.swap.set_text("Swap: disabled")
        self.disk.update(
            disk["fraction"],
            f"{L.human_size(disk['used'])} of {L.human_size(disk['total'])} used · "
            f"{L.human_size(disk['free'])} free",
        )
        self.disk_extra.set_text(f"Mount: {disk['path']}")

        temp = f" · {snap['temp']:.0f}°C" if snap.get("temp") else ""
        self.glance.set_text(
            f"Load {snap['load']:.2f} / {snap['cores']} cores · "
            f"Uptime {L.human_duration(snap['uptime'])} · "
            f"{snap['processes']} processes{temp}"
        )


class LauncherPage(Page):
    def build(self):
        self.apps = []
        self.hidden = set()
        self.busy = False
        self.syncing = False

        self.box.append(sec("Launcher apps"))
        note = label("Turn an app off to hide it from the launcher (Super + D).", "dimtext")
        note.set_wrap(True)
        self.box.append(note)

        self.search = Gtk.Entry()
        self.search.set_placeholder_text("Search apps")
        self.search.connect("changed", lambda _e: self.render())
        self.box.append(self.search)

        self.summary = label("", "dimtext")
        self.box.append(self.summary)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.box.append(self.list)

    def on_show(self):
        self.refresh()

    def refresh(self):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                hidden = L.hidden_app_ids()
                return L.launcher_apps(hidden), hidden
            except Exception:
                return [], set()

        bg(work, self.loaded)

    def loaded(self, data):
        self.busy = False
        self.apps, self.hidden = data
        self.render()

    @staticmethod
    def app_image(icon_name):
        if icon_name and os.path.isabs(icon_name) and os.path.isfile(icon_name):
            icon = Gio.FileIcon.new(Gio.File.new_for_path(icon_name))
            return Gtk.Image.new_from_gicon(icon)
        return Gtk.Image.new_from_icon_name(icon_name or "application-x-executable")

    def render(self):
        clear(self.list)
        query = self.search.get_text().strip().lower()
        shown = [app for app in self.apps if query in app["name"].lower()]
        total = len(self.apps)
        self.summary.set_text(f"{total - len(self.hidden)} shown · {len(self.hidden)} hidden")

        if not shown:
            self.list.append(label("No apps match that search", "dimtext"))
            return

        for app in shown:
            app_id = app["id"]
            visible = app_id not in self.hidden
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            img = self.app_image(app["icon"])
            img.set_size_request(24, 24)
            row.append(img)

            name = label(app["name"], "plain", hexpand=True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            self._dim(name, not visible)
            row.append(name)

            if app["comment"]:
                comment = label(app["comment"], "dimtext")
                comment.set_ellipsize(Pango.EllipsizeMode.END)
                comment.set_max_width_chars(24)
                row.append(comment)

            sw = Gtk.Switch()
            sw.set_valign(Gtk.Align.CENTER)
            self.syncing = True
            sw.set_active(visible)
            self.syncing = False
            sw.connect("state-set",
                       lambda _s, state, i=app_id, s=sw, n=name: self.toggle(i, state, s, n))
            row.append(sw)
            self.list.append(row)

    @staticmethod
    def _dim(name, hidden):
        (name.add_css_class if hidden else name.remove_css_class)("dimtext")

    def toggle(self, app_id, visible, switch, name):
        if self.syncing:
            return False
        try:
            if visible:
                L.unhide_app(app_id)
                self.say(f"Showing {name.get_text()}")
            else:
                L.hide_app(app_id)
                self.say(f"Hidden {name.get_text()} from the launcher")
        except Exception as e:
            self.syncing = True
            switch.set_active(not visible)
            self.syncing = False
            self.say(str(e))
            return False

        self.hidden = L.hidden_app_ids()
        self._dim(name, not visible)
        self.summary.set_text(f"{len(self.apps) - len(self.hidden)} shown · {len(self.hidden)} hidden")
        bg(lambda: run("update-desktop-database", L.USER_APPLICATIONS, timeout=15))
        return False


class SettingsPopup(Popup):
    name = "settings"
    width = 820
    centered = True
    top = 70
    autohide = False

    PAGES = [
        ("󰔎", "Look & feel", LookPage),
        ("󰸉", "Wallpaper & theme", WallpaperPage),
        ("󰍂", "Login screen", LoginPage),
        ("󰌾", "Screen lock", LockPage),
        ("󰈺", "System", SystemPage),
        ("󰍉", "Launcher", LauncherPage),
        ("󰖩", "Quick links", LinksPage),
        ("󰌌", "Keybinds", KeybindsPage),
        ("󰐥", "Startup", StartupPage),
        ("󰏖", "App Uninstaller", AppUninstallerPage),
        ("󰍹", "Shell", ShellPage),
    ]

    def build(self, root):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.append(label("Settings", "title", hexpand=True))
        close = Gtk.Button(label="󰅖")
        close.add_css_class("nav")
        close.connect("clicked", lambda _b: self.hide())
        head.append(close)
        root.append(head)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav.set_size_request(190, -1)
        nav.set_hexpand(False)
        self.stack = Gtk.Stack()
        self.stack.set_hexpand(True)
        self.pages, self.navbtns = {}, {}
        for icon, title, cls in self.PAGES:
            page = cls(self)
            self.pages[title] = page
            sc = Gtk.ScrolledWindow()
            sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sc.set_min_content_height(470)
            sc.set_max_content_height(470)
            sc.set_child(page.box)
            self.stack.add_named(sc, title)
            b = item(icon, title, "", False, lambda t=title: self.go(t))
            nav.append(b)
            self.navbtns[title] = b
        body.append(nav)
        body.append(self.stack)
        root.append(body)
        self.go(self.PAGES[0][1], show=False)

    def go(self, title, show=True):
        self.stack.set_visible_child_name(title)
        for t, b in self.navbtns.items():
            (b.add_css_class if t == title else b.remove_css_class)("current")
        if show:
            self.pages[title].on_show()

    def on_show(self):
        name = self.stack.get_visible_child_name() or self.PAGES[0][1]
        self.pages[name].on_show()
