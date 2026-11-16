"""Glass notepad popup — centred, tabbed, autosaving, glass-styled."""
import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from glass import *
import notes_logic as NL

DELETE_CONFIRM_MS = 3000


class NotesPopup(Popup):
    name = "notes"
    width = 440
    centered = True
    top = 120
    autohide = False

    def __init__(self, app):
        self.notes = NL.load_notes()
        self.current_idx = 0
        self.autosave_timer = None
        self.delete_pending = None  # (idx, timer_id)
        super().__init__(app)

    def build(self, root):
        # Header with title and close
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        head.append(label("Notes", "title", hexpand=True))
        close = Gtk.Button(label="󰅖")
        close.add_css_class("nav")
        close.connect("clicked", lambda _b: self.hide())
        head.append(close)
        root.append(head)

        # Tab bar (chips)
        self.tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.tab_box.set_homogeneous(False)
        self.tab_box.set_margin_top(4)
        self.tab_box.set_margin_bottom(4)
        root.append(self.tab_box)

        # Separator
        root.append(Gtk.Separator())

        # Text view area
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled.set_propagate_natural_height(True)
        self.scrolled.set_max_content_height(320)
        self.scrolled.add_css_class("notes-scrolled")

        self.textview = Gtk.TextView()
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.set_monospace(False)
        self.textview.add_css_class("notes-textview")
        self.buffer = self.textview.get_buffer()
        self.buffer.connect("changed", self.on_text_changed)

        # Placeholder overlay (GTK4 TextView has no set_placeholder_text)
        self.placeholder = Gtk.Label(label="Start typing…")
        self.placeholder.add_css_class("notes-placeholder")
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_start(14)
        self.placeholder.set_margin_top(14)

        overlay = Gtk.Overlay()
        overlay.set_child(self.textview)
        overlay.add_overlay(self.placeholder)
        self.scrolled.set_child(overlay)
        root.append(self.scrolled)

        # Footer: word/char count, Copy, Delete
        self.footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.footer.set_margin_top(8)

        self.count_label = label("0 words · 0 chars", "dimtext")
        self.count_label.set_hexpand(True)
        self.count_label.set_xalign(0.0)

        self.copy_btn = Gtk.Button(label="Copy")
        self.copy_btn.add_css_class("chip")
        self.copy_btn.connect("clicked", self.on_copy)

        self.delete_btn = Gtk.Button(label="Delete")
        self.delete_btn.add_css_class("chip")
        self.delete_btn.connect("clicked", self.on_delete_click)

        self.footer.append(self.count_label)
        self.footer.append(self.copy_btn)
        self.footer.append(self.delete_btn)
        root.append(self.footer)

        # Initial render
        self.rebuild_tabs()
        self.load_note(0)

    def on_show(self):
        self.rebuild_tabs()
        if self.current_idx >= len(self.notes):
            self.current_idx = max(0, len(self.notes) - 1)
        self.load_note(self.current_idx)
        self.textview.grab_focus()

    # ---------------------------------------------------------------- tabs
    def rebuild_tabs(self):
        clear(self.tab_box)
        for i, note in enumerate(self.notes):
            self.tab_box.append(self.make_tab_chip(i))
        # "+" chip
        if len(self.notes) < NL.MAX_NOTES:
            plus = Gtk.Button(label="+")
            plus.add_css_class("chip")
            plus.add_css_class("plus")
            plus.set_tooltip_text("New note")
            plus.connect("clicked", lambda _b: self.new_note())
            self.tab_box.append(plus)

    def make_tab_chip(self, idx):
        note = self.notes[idx]
        btn = Gtk.Button()
        btn.add_css_class("chip")
        if idx == self.current_idx:
            btn.add_css_class("current")
        btn.set_child(label(NL.title_of(note), "plain", xalign=0.5))
        btn.connect("clicked", lambda _b, i=idx: self.switch_tab(i))

        # Right-click to delete
        right = Gtk.GestureClick.new()
        right.set_button(3)
        right.connect("pressed", lambda *_a, i=idx: self.confirm_delete(i))
        btn.add_controller(right)

        # Drag to reorder
        drag = Gtk.DragSource.new()
        drag.set_content(Gdk.ContentProvider.new_for_value(str(idx)))
        drag.connect("prepare", lambda s, x, y: (Gdk.ContentProvider.new_for_value(str(idx)), Gdk.DragAction.MOVE))
        drag.connect("drag-end", lambda s, d, del_: self.on_drag_end(del_))
        btn.add_controller(drag)

        drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        drop.connect("drop", lambda s, v, x, y, i=idx: self.on_drop(v, i))
        btn.add_controller(drop)

        return btn

    def on_drag_end(self, deleted):
        if deleted:
            self.rebuild_tabs()

    def on_drop(self, value, target_idx):
        try:
            from_idx = int(value.get_string())
        except (ValueError, AttributeError):
            return False
        if from_idx == target_idx:
            return False
        self.notes = NL.reorder_notes(self.notes, from_idx, target_idx)
        self.current_idx = target_idx
        self.save_notes()
        self.rebuild_tabs()
        self.highlight_tab(self.current_idx)
        return True

    def highlight_tab(self, idx):
        child = self.tab_box.get_first_child()
        i = 0
        while child:
            if i < len(self.notes):
                (child.add_css_class if i == idx else child.remove_css_class)("current")
            i += 1
            child = child.get_next_sibling()

    def switch_tab(self, idx):
        if idx == self.current_idx:
            return
        self.flush_autosave()
        self.current_idx = idx
        self.load_note(idx)
        self.highlight_tab(idx)

    def new_note(self):
        self.flush_autosave()
        self.notes, new_idx = NL.add_note(self.notes, "New note", "")
        self.current_idx = new_idx
        self.save_notes()
        self.rebuild_tabs()
        self.load_note(new_idx)
        self.highlight_tab(new_idx)
        # Focus textview and select all for immediate renaming
        GLib.idle_add(lambda: (self.textview.grab_focus(), self.buffer.select_range(
            self.buffer.get_start_iter(), self.buffer.get_end_iter())))

    def confirm_delete(self, idx):
        """First right-click or delete-btn click: show 'Delete?' for 3s."""
        if self.delete_pending and self.delete_pending[0] == idx:
            return  # already pending
        self.cancel_delete_pending()
        btn = self.get_tab_button(idx)
        if btn:
            btn.set_label("Delete?")
            btn.add_css_class("delete-pending")
        timer = GLib.timeout_add(DELETE_CONFIRM_MS, self.cancel_delete_pending)
        self.delete_pending = (idx, timer)

    def cancel_delete_pending(self):
        if self.delete_pending:
            idx, timer = self.delete_pending
            GLib.source_remove(timer)
            btn = self.get_tab_button(idx)
            if btn:
                btn.set_label(NL.title_of(self.notes[idx]) if idx < len(self.notes) else "")
                btn.remove_css_class("delete-pending")
            self.delete_pending = None
        return False  # for timeout

    def get_tab_button(self, idx):
        child = self.tab_box.get_first_child()
        i = 0
        while child:
            if i == idx and i < len(self.notes):
                return child
            i += 1
            child = child.get_next_sibling()
        return None

    def on_delete_click(self, _btn):
        """Delete button in footer — same two-click confirm."""
        self.confirm_delete(self.current_idx)

    def delete_current(self):
        """Actually delete the note (called after confirm)."""
        self.cancel_delete_pending()
        if len(self.notes) <= 1:
            return
        self.notes = NL.delete_note(self.notes, self.current_idx)
        self.save_notes()
        if self.current_idx >= len(self.notes):
            self.current_idx = len(self.notes) - 1
        self.rebuild_tabs()
        self.load_note(self.current_idx)
        self.highlight_tab(self.current_idx)

    # ---------------------------------------------------------------- note content
    def load_note(self, idx):
        if 0 <= idx < len(self.notes):
            note = self.notes[idx]
            self.buffer.set_text(note.get("text", ""))
            self.update_counts()
            self.textview.grab_focus()

    def on_text_changed(self, _buf):
        self.update_counts()
        self.schedule_autosave()
        # Show/hide placeholder
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        self.placeholder.set_visible(not text.strip())

    def update_counts(self):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        words, chars = NL.counts(text)
        self.count_label.set_text(f"{words} words · {chars} chars")

    def schedule_autosave(self):
        if self.autosave_timer:
            GLib.source_remove(self.autosave_timer)
        self.autosave_timer = GLib.timeout_add(NL.AUTOSAVE_MS, self.flush_autosave)

    def flush_autosave(self):
        if self.autosave_timer:
            GLib.source_remove(self.autosave_timer)
            self.autosave_timer = None
        self.save_current_note()
        return False  # for timeout

    def save_current_note(self):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        title = self.notes[self.current_idx].get("title", "").strip() or "Untitled"
        # If title is still default and we have content, derive from first line
        if title == "New note" and text.strip():
            first_line = text.strip().split("\n")[0][:40]
            title = first_line or "Untitled"
        self.notes = NL.update_note(self.notes, self.current_idx, title=title, text=text)
        self.save_notes()
        # Update tab label if title changed
        self.rebuild_tabs()
        self.highlight_tab(self.current_idx)

    def save_notes(self):
        NL.save_notes(self.notes)

    def on_copy(self, _btn):
        start = self.buffer.get_start_iter()
        end = self.buffer.get_end_iter()
        text = self.buffer.get_text(start, end, True)
        if text:
            clipboard = self.textview.get_clipboard()
            clipboard.set_text(text)
            self.count_label.set_text("Copied!")
            GLib.timeout_add(1500, lambda: (self.update_counts(), False)[1])

    # ---------------------------------------------------------------- hide
    def hide(self):
        self.flush_autosave()
        self.cancel_delete_pending()
        super().hide()


# ---- CSS additions for notes (to be appended to glass.py CSS) ----
NOTES_CSS = """
.notes-scrolled {
  background-color: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 16px;
}
.notes-textview {
  background-color: transparent;
  color: white;
  font-size: 14px;
  font-family: Inter;
  padding: 14px 16px;
}
.notes-textview:focus {
  background-color: rgba(255,255,255,0.06);
}
.notes-textview text {
  caret-color: @glass_accent;
}
.notes-placeholder {
  color: rgba(255,255,255,0.35);
  font-size: 14px;
  font-family: Inter;
  pointer-events: none;
}
button.chip.plus {
  background-color: @glass_accent_soft;
  border: 1px solid @glass_accent_mid;
  color: white;
  font-weight: bold;
  min-width: 36px;
}
button.chip.plus:hover {
  background-color: @glass_accent_mid;
}
button.chip.delete-pending {
  background-color: rgba(255,95,87,0.35);
  border: 1px solid #ff5f57;
  color: #ff8a80;
}
"""


if __name__ == "__main__":
    # Quick smoke test under Xvfb
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from glass import apply_css
    from accent import compute

    apply_css(compute())
    app = Gtk.Application(application_id="local.glass.notes-test")
    pop = NotesPopup(app)
    pop.show(960)
    app.run()
