"""Application object: single instance, theme, actions, D-Bus, windows."""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")

from gi.repository import Gdk, Gio, GLib, Gtk

from . import (accent as accent_mod, css, filemanager1, prefs as prefs_mod,
               util, window as window_mod)

APP_ID = "local.glass.files"
APP_NAME = "Glass Files"
VERSION = "0.1.0"


class GlassApplication(Gtk.Application):
    def __init__(self, service=False):
        self._service = bool(service or "--gapplication-service" in sys.argv)
        flags = Gio.ApplicationFlags.HANDLES_OPEN
        if self._service:
            flags |= Gio.ApplicationFlags.IS_SERVICE
        super().__init__(application_id=APP_ID, flags=flags)
        self.prefs = prefs_mod.Prefs()
        self.accent_rgb = accent_mod.compute()
        self.css_provider = Gtk.CssProvider()
        self._fm1 = None
        self._prewarm_win = None
        self._prewarm_used = False

    # ------------------------------------------------------------- lifecycle
    def _is_service(self):
        return self._service

    def do_startup(self):
        Gtk.Application.do_startup(self)
        GLib.set_application_name(APP_NAME)
        GLib.set_prgname("glass-files")
        try:
            Gtk.Window.set_default_icon_name(APP_ID)
        except Exception:
            pass

        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, self.css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)

        try:
            settings = Gtk.Settings.get_default()
            dark = self.current_theme() == css.DARK
            scheme = getattr(Gtk, "InterfaceColorScheme", None)
            if (scheme is not None
                    and settings.find_property("gtk-interface-color-scheme") is not None):
                settings.set_property(
                    "gtk-interface-color-scheme",
                    scheme.DARK if dark else scheme.LIGHT)
            else:
                settings.set_property("gtk-application-prefer-dark-theme", dark)
            settings.set_property("gtk-font-name", "Inter 10")
        except Exception:
            pass

        self.reload_css()
        self._install_app_actions()
        self._install_accels()
        self._fm1 = filemanager1.FileManager1(self)
        if self._is_service() and not os.environ.get("GLASS_NO_PREWARM"):
            # Build the window while the app is idle so the first launch is
            # just a show/present instead of a full Python+GTK cold start.
            # Low priority: if a D-Bus ShowFolders call is already queued,
            # handle it first instead of prewarming and then showing.
            GLib.idle_add(self._prewarm, priority=GLib.PRIORITY_LOW)
        if os.environ.get("GLASS_PROBE"):
            GLib.timeout_add(2500, self._probe)

    def do_shutdown(self):
        if self._fm1 is not None:
            self._fm1.stop()
            self._fm1 = None
        Gtk.Application.do_shutdown(self)

    def _prewarm(self):
        """Create one hidden window in service mode so launch is near-instant."""
        if not self._is_service():
            return False
        if self.get_windows():
            return False
        try:
            win = window_mod.GlassWindow(self, self.prefs, util.HOME)
        except Exception as e:
            print(f"glass-files: prewarm failed: {e}")
            return False
        self._prewarm_win = win
        self._prewarm_used = False
        win.connect("destroy", self._on_prewarm_destroyed)
        try:
            # Realize and map one transparent frame so the first real present()
            # only has to show an already-laid-out window.
            win.realize()
            win.set_opacity(0.0)
            win.set_focusable(False)
            win.set_visible(True)
            GLib.timeout_add(150, self._finish_prewarm, win)
        except Exception as e:
            print(f"glass-files: prewarm failed: {e}")
        return False

    def _finish_prewarm(self, win):
        if win is not self._prewarm_win:
            return False
        win.set_opacity(1.0)
        if not self._prewarm_used:
            win.set_visible(False)
        return False

    def _on_prewarm_destroyed(self, win):
        if self._prewarm_win is win:
            self._prewarm_win = None
        if self._is_service() and not self.get_windows():
            # The user closed the window; keep a warm one ready for next time.
            GLib.timeout_add(400, self._prewarm)

    def _use_prewarm(self, win):
        if win is self._prewarm_win:
            self._prewarm_used = True
            try:
                win.set_focusable(True)
                win.set_opacity(1.0)
            except Exception:
                pass

    def do_activate(self):
        win = self.get_active_window()
        if win is None:
            wins = self.get_windows()
            win = wins[-1] if wins else None
        if win is None:
            self.new_window()
        else:
            self._use_prewarm(win)
            win.present()

    def do_open(self, files, n_files, hint):
        paths = []
        for f in files:
            p = f.get_path()
            if p:
                paths.append(p)
        if not paths:
            self.do_activate()
            return
        self.open_paths(paths)

    # ----------------------------------------------------------------- theme
    def current_theme(self):
        env = os.environ.get("GLASS_THEME", "").lower()
        if env in (css.LIGHT, css.DARK):
            return env
        mode = self.prefs.get("theme", "auto")
        if mode == "auto":
            return css.LIGHT if accent_mod.desktop_is_light() else css.DARK
        return css.LIGHT if mode == "light" else css.DARK

    def reload_css(self):
        try:
            self.accent_rgb = accent_mod.compute()
        except Exception:
            pass
        sheet = css.build(self.accent_rgb, self.current_theme())
        try:
            self.css_provider.load_from_data(sheet.encode("utf-8"), -1)
        except GLib.Error as e:
            print(f"glass-files: stylesheet error: {e.message}")

    @staticmethod
    def _font_families():
        return ""

    # --------------------------------------------------------------- windows
    def _probe(self):
        for win in self.get_windows():
            print("WINDOW", win.get_width(), "x", win.get_height(),
                  "visible", win.get_visible(), "theme", self.current_theme())
            self._dump(win, 0)
        print("PROBE-END")
        self.quit()
        return False

    def _dump(self, w, depth):
        if depth > 14:
            return
        text = ""
        for meth in ("get_label", "get_text", "get_title"):
            try:
                if hasattr(w, meth):
                    val = getattr(w, meth)()
                    if isinstance(val, str) and val:
                        text = f" {val[:70]!r}"
                        break
            except Exception:
                pass
        hidden = " HIDDEN" if not w.get_visible() else ""
        print("  " * depth + type(w).__name__ +
              f" {w.get_width()}x{w.get_height()}{text}{hidden}")
        child = w.get_first_child()
        while child is not None:
            self._dump(child, depth + 1)
            child = child.get_next_sibling()

    def new_window(self, location=None, split=False):
        loc = location or util.HOME
        win = window_mod.GlassWindow(self, self.prefs, loc, split=split)
        win.present()
        if self._is_service() and self._prewarm_win is None:
            # Cold D-Bus activation (or a prewarm failure): adopt the first
            # window so closing it hides the service instead of quitting it.
            self._prewarm_win = win
            win.connect("destroy", self._on_prewarm_destroyed)
        return win

    def open_paths(self, paths, show_items=False):
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if not os.path.isdir(p)]
        win = self.get_active_window()
        if win is None:
            wins = self.get_windows()
            win = wins[-1] if wins else None
        folder = None
        if dirs:
            folder = dirs[0]
        elif files:
            folder = os.path.dirname(files[0]) or util.HOME
        if win is None:
            win = self.new_window(folder or util.HOME)
            for d in (dirs[1:] if dirs else []):
                win.new_tab(d)
        elif folder:
            win.navigate(folder)
            for d in (dirs[1:] if dirs else []):
                win.new_tab(d)
        if win is self._prewarm_win:
            self._use_prewarm(win)
        win.present()

        if files:
            target = files[0]
            try:
                win.active_pane()._select_path_soon(target)
            except Exception:
                pass
            if show_items is False and len(files) == 1:
                # Launched with a file: the caller wants it revealed, not opened.
                pass
        else:
            try:
                win.active_pane().focus_view()
            except Exception:
                pass

    def present_uris(self, uris, show_items=False):
        paths = []
        for uri in uris or []:
            try:
                if uri.startswith("file://"):
                    p = Gio.File.new_for_uri(uri).get_path()
                else:
                    p = uri
            except Exception:
                p = None
            if p:
                paths.append(p)
        if paths:
            self.open_paths(paths, show_items=show_items)
        else:
            self.do_activate()
        return False

    def show_properties_uris(self, uris):
        paths = []
        for uri in uris or []:
            try:
                p = Gio.File.new_for_uri(uri).get_path() if uri.startswith("file://") else uri
            except Exception:
                p = None
            if p:
                paths.append(p)
        if not paths:
            return False
        self.open_paths(paths[:1], show_items=True)
        win = self.get_active_window()
        if win is not None:
            win.show_properties(paths[0])
        return False

    # --------------------------------------------------------------- actions
    def _install_app_actions(self):
        act = Gio.SimpleAction.new("new-window", None)
        act.connect("activate", lambda a, p: self.new_window())
        self.add_action(act)

        act = Gio.SimpleAction.new("quit", None)
        act.connect("activate", lambda a, p: self.quit())
        self.add_action(act)

        act = Gio.SimpleAction.new("about", None)
        act.connect("activate", lambda a, p: self._about())
        self.add_action(act)

    def _about(self):
        win = self.get_active_window()
        if win is not None:
            win.show_about()

    def _install_accels(self):
        table = {
            "app.new-window": ["<Control>n"],
            "app.quit": ["<Control>q"],
            "win.new-tab": ["<Control>t"],
            "win.close-tab": ["<Control>w"],
            "win.reopen-tab": ["<Control><Shift>t"],
            "win.copy": ["<Control>c"],
            "win.cut": ["<Control>x"],
            "win.paste": ["<Control>v"],
            "win.select-all": ["<Control>a"],
            "win.properties": ["<Alt>Return"],
            "win.preferences": ["<Control>comma"],
            "win.refresh": ["F5"],
            "win.home": ["<Alt>Home"],
            "win.focus-location": ["<Control>l"],
            "win.focus-search": ["<Control>f"],
            "win.show-hidden-toggle": ["<Control>h"],
            "win.view-grid": ["<Control>1"],
            "win.view-list": ["<Control>2"],
            "win.view-compact": ["<Control>3"],
            "win.zoom-in": ["<Control>plus", "<Control>equal"],
            "win.zoom-out": ["<Control>minus"],
            "win.open": ["Return"],
            "win.rename": ["F2"],
            "win.trash": ["Delete"],
            "win.delete": ["<Shift>Delete"],
            "win.new-folder": ["<Control><Shift>n"],
            "win.undo": ["<Control>z"],
            "win.redo": ["<Control><Shift>z"],
        }
        for action, accels in table.items():
            self.set_accels_for_action(action, accels)


def main(argv=None):
    args = sys.argv if argv is None else argv
    app = GlassApplication(service="--gapplication-service" in args)
    return app.run(argv if argv is not None else None)
