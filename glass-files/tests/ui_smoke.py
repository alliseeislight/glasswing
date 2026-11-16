#!/usr/bin/python3
"""Live UI smoke test. Run it on the real Wayland session:

    /usr/bin/python3 tests/ui_smoke.py

It uses a throwaway directory under /tmp/opencode, exercises navigation, views,
search, tabs, split, copy, rename, trash + undo, Quick Look, and the dialogs.
Nothing in your home directory is modified (the app config is read-only here).
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, Gtk

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from glassfiles import app as app_mod, dialogs, model, util  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def pump(seconds):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.01)


class SmokeApp(app_mod.GlassApplication):
    def __init__(self, base):
        self.base = base
        self.testdir = tempfile.mkdtemp(prefix="glass-ui-", dir=base)
        self.otherdir = tempfile.mkdtemp(prefix="glass-ui-other-", dir=base)
        self._seed()
        super().__init__()
        self.win = None

    def _seed(self):
        os.makedirs(os.path.join(self.testdir, "Docs"), exist_ok=True)
        with open(os.path.join(self.testdir, "note.txt"), "w") as f:
            f.write("hello glass\n")
        with open(os.path.join(self.testdir, "pic.png"), "wb") as f:
            f.write(bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                "1f15c4890000000d49444154789c6360000000020001e221bc33000000"
                "0049454e44ae426082"))
        with open(os.path.join(self.testdir, "song.mp3"), "wb") as f:
            f.write(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        with open(os.path.join(self.testdir, "archive.zip"), "wb") as f:
            f.write(b"PK\x05\x06" + b"\x00" * 18)

    def do_activate(self):
        if self.win is not None:
            return
        self.win = self.new_window(self.testdir)
        self.win.set_default_size(1100, 760)
        GLib.timeout_add(900, self.run_all)

    def run_all(self):
        win = self.win
        ok = True
        try:
            pump(0.4)

            p = win.active_pane()
            check("window created", win.get_visible())
            check("navigated to temp dir", p.location == self.testdir, p.location)
            check("model has items", p.model.count() >= 4, str(p.model.count()))
            check("breadcrumb built", win.crumbs.get_first_child() is not None)
            check("sidebar present", win.sidebar.get_visible())

            # --------------------------------------------------------- views
            for mode in ("list", "compact", "grid"):
                win.set_view(mode)
                pump(0.15)
                check(f"view {mode}", p.view_mode == mode)
            win.bump_zoom(16)
            pump(0.3)
            check("zoom applied", p.icon_size >= 120, str(p.icon_size))

            # -------------------------------------------------------- sorting
            win._set_sort("size")
            pump(0.15)
            check("sort size", p.sort_key == "size")
            win._toggle_sort_desc()
            pump(0.1)
            check("sort descending", p.sort_desc)
            win._set_sort("name")

            # --------------------------------------------------------- search
            win.search.set_text("note")
            pump(0.5)
            check("filter search", p.model.count() == 1, str(p.model.count()))
            win.search.set_text("")
            pump(0.3)
            check("search cleared", p.model.count() >= 4, str(p.model.count()))

            # ------------------------------------------------------ selection
            pos = next(i for i in range(p.model.count())
                       if util.display_name(
                           model.path_of(
                               p.model.item(i), p.base_path)) == "note.txt")
            p.model.selection.select_item(pos, True)
            pump(0.15)
            check("selection", p.selected_paths() == [os.path.join(self.testdir, "note.txt")],
                  str(p.selected_paths()))

            # ----------------------------------------------------------- tabs
            tabs_before = len(win.tabs)
            win.new_tab(self.otherdir)
            pump(0.5)
            check("new tab", len(win.tabs) == tabs_before + 1)
            check("new tab navigated", win.active_pane().location == self.otherdir)
            win.toggle_split()
            pump(0.4)
            check("split view", len(win.active_tab.panes) == 2)
            win.toggle_split()
            pump(0.4)
            check("split closed", len(win.active_tab.panes) == 1)
            win.close_tab(win.active_tab)
            pump(0.4)
            check("tab closed", len(win.tabs) == tabs_before)
            check("back on first tab", win.active_pane().location == self.testdir)

            # ---------------------------------------------------------- copy
            src = os.path.join(self.testdir, "note.txt")
            win.paste_paths([src], self.otherdir, False)
            pump(1.0)
            copied = os.path.join(self.otherdir, "note.txt")
            check("copy landed", os.path.isfile(copied))
            for j in win.jobs.jobs():
                if j.status != "done":
                    print("  job:", j.title, j.status, j.error)
            check("undo stack has copy", win.undo_stack.can_undo())
            win.undo()
            pump(1.2)
            check("copy undone (moved to trash)", not os.path.exists(copied))

            # --------------------------------------------------------- rename
            win.do_rename(src, "renamed.txt")
            pump(0.8)
            renamed = os.path.join(self.testdir, "renamed.txt")
            check("rename", os.path.isfile(renamed))
            win.undo()
            pump(0.5)
            check("rename undone", os.path.isfile(src))

            # ---------------------------------------------------------- trash
            pos = next(i for i in range(p.model.count())
                       if os.path.join(self.testdir, "song.mp3") ==
                       model.path_of(
                           p.model.item(i), p.base_path))
            p.model.selection.unselect_all()
            p.model.selection.select_item(pos, True)
            win.trash_selected()
            pump(1.5)
            check("trash removed source", not os.path.exists(os.path.join(self.testdir, "song.mp3")))
            win.undo()
            pump(1.5)
            check("trash undone", os.path.exists(os.path.join(self.testdir, "song.mp3")))

            # ------------------------------------------------------ quick look
            pos = next(i for i in range(p.model.count())
                       if os.path.join(self.testdir, "pic.png") ==
                       model.path_of(
                           p.model.item(i), p.base_path))
            p.model.selection.unselect_all()
            p.model.selection.select_item(pos, True)
            win.toggle_quicklook()
            pump(1.2)
            q = win._quick
            check("quick look visible", q is not None and q.get_visible())
            if q is not None and q.get_visible():
                q.close()
            pump(0.2)

            # --------------------------------------------------------- dialogs
            d = dialogs.properties_dialog(win, os.path.join(self.testdir, "pic.png"))
            pump(0.6)
            check("properties dialog", d.get_visible())
            d.close()
            pump(0.2)

            d = dialogs.preferences_dialog(win)
            pump(0.4)
            check("preferences dialog", d.get_visible())
            d.close()
            pump(0.2)

            d = dialogs.rename_dialog(win, src)
            pump(0.4)
            check("rename dialog", d.get_visible())
            d.close()
            pump(0.2)

            # --------------------------------------------------- hidden files
            win.toggle_hidden()
            pump(0.4)
            check("hidden toggle", p.show_hidden)
            win.toggle_hidden()
            pump(0.3)

            # ------------------------------------------------------ trash view
            win.navigate("trash://")
            pump(1.2)
            check("trash view", win.active_pane().source_kind == "trash")
            win.navigate(self.testdir)
            pump(0.8)

            # ------------------------------------------------------ nav buttons
            win.navigate(self.otherdir)
            pump(0.5)
            check("navigated other", win.active_pane().location == self.otherdir)
            win.active_pane().back()
            pump(0.6)
            check("back", win.active_pane().location == self.testdir)

        except Exception:
            ok = False
            traceback.print_exc()
            check("no exception", False)
        else:
            check("no exception", True)

        failed = [name for name, good, _ in RESULTS if not good]
        print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
        if failed:
            print("failed:", ", ".join(failed))
        win.destroy()
        self.quit()
        return False


def main():
    base = "/tmp/opencode"
    os.makedirs(base, exist_ok=True)
    app = SmokeApp(base)
    code = app.run([])
    shutil.rmtree(app.testdir, ignore_errors=True)
    shutil.rmtree(app.otherdir, ignore_errors=True)
    return code or (0 if all(good for _, good, _ in RESULTS) else 1)


if __name__ == "__main__":
    raise SystemExit(main())
