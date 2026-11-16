"""Pure-Python logic for the glass notepad popup (no GTK, testable alone)."""
import json
import os
import re
import time
from pathlib import Path

DATA_DIR = Path.home() / ".local" / "share" / "glass"
DATA_FILE = DATA_DIR / "notes.json"
MAX_NOTES = 8
AUTOSAVE_MS = 600


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_notes():
    """Load notes from JSON. Returns list of dicts: {title, text, updated}."""
    _ensure_dir()
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return _default_notes()
        # validate and sanitize
        out = []
        for n in data[:MAX_NOTES]:
            if isinstance(n, dict):
                title = str(n.get("title", "")).strip() or "Untitled"
                text = str(n.get("text", ""))
                updated = n.get("updated", 0)
                out.append({"title": title, "text": text, "updated": updated})
        return out or _default_notes()
    except (OSError, json.JSONDecodeError):
        return _default_notes()


def save_notes(notes):
    """Atomic write of notes list."""
    _ensure_dir()
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(notes, f, indent=2)
        f.write("\n")
    os.replace(tmp, DATA_FILE)


def _default_notes():
    return [{"title": "Note 1", "text": "", "updated": int(time.time())}]


def title_of(note):
    """Return a display title, truncated for tab chips."""
    t = note.get("title", "").strip()
    if not t:
        t = "Untitled"
    return t[:28] + ("…" if len(t) > 28 else "")


def counts(text):
    """Return (word_count, char_count) for a text string."""
    words = len(re.findall(r"\S+", text))
    chars = len(text)
    return words, chars


def add_note(notes, title="New note", text=""):
    """Add a new note, enforce MAX_NOTES, return new list and new index."""
    now = int(time.time())
    new_note = {"title": title, "text": text, "updated": now}
    notes = notes + [new_note]
    if len(notes) > MAX_NOTES:
        notes = notes[-MAX_NOTES:]
    return notes, len(notes) - 1


def delete_note(notes, index):
    """Delete note at index, return new list. Keeps at least one note."""
    if len(notes) <= 1:
        return _default_notes()
    if 0 <= index < len(notes):
        notes = notes[:index] + notes[index + 1:]
    return notes


def update_note(notes, index, title=None, text=None):
    """Update note fields, refresh updated timestamp."""
    if 0 <= index < len(notes):
        note = notes[index].copy()
        if title is not None:
            note["title"] = title.strip() or "Untitled"
        if text is not None:
            note["text"] = text
        note["updated"] = int(time.time())
        notes = notes.copy()
        notes[index] = note
    return notes


def reorder_notes(notes, from_idx, to_idx):
    """Move note from from_idx to to_idx."""
    if 0 <= from_idx < len(notes) and 0 <= to_idx < len(notes) and from_idx != to_idx:
        notes = notes.copy()
        note = notes.pop(from_idx)
        notes.insert(to_idx, note)
    return notes


# --- simple test when run directly ---
if __name__ == "__main__":
    import tempfile
    import shutil

    # test in a temp dir
    test_dir = Path(tempfile.mkdtemp())
    test_file = test_dir / "notes.json"
    try:
        # monkey-patch
        import notes_logic as nl
        orig_file = nl.DATA_FILE
        orig_dir = nl.DATA_DIR
        nl.DATA_FILE = test_file
        nl.DATA_DIR = test_dir

        # load default
        notes = nl.load_notes()
        assert len(notes) == 1 and notes[0]["title"] == "Note 1"
        print("✓ default notes")

        # add
        notes, idx = nl.add_note(notes, "Hello", "World")
        assert len(notes) == 2 and idx == 1
        print("✓ add note")

        # update
        notes = nl.update_note(notes, 0, text="Updated text")
        assert notes[0]["text"] == "Updated text"
        print("✓ update note")

        # delete
        notes = nl.delete_note(notes, 0)
        assert len(notes) == 1
        print("✓ delete note")

        # max notes enforcement
        notes = _default_notes()
        for i in range(12):
            notes, _ = nl.add_note(notes, f"Note {i}", "x")
        assert len(notes) == nl.MAX_NOTES
        print("✓ max notes enforced")

        # reorder
        notes = [{"title": f"N{i}", "text": "", "updated": 0} for i in range(3)]
        notes = nl.reorder_notes(notes, 0, 2)
        assert notes[2]["title"] == "N0"
        print("✓ reorder")

        # counts
        w, c = nl.counts("hello world")
        assert w == 2 and c == 11
        print("✓ counts")

        print("\nAll tests passed!")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
