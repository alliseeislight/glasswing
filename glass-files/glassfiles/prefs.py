"""Persistent preferences and per-folder view memory. No GTK."""

from __future__ import annotations

import json
import os
import tempfile

from . import util

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(util.HOME, ".config"), "glass"
)
PATH = os.path.join(CONFIG_DIR, "files.json")

DEFAULTS = {
    "view": "grid",
    "icon_size": 112,
    "show_hidden": False,
    "sort": {"key": "name", "desc": False, "folders_first": True},
    "per_folder": {},
    "theme": "auto",           # auto | dark | light
    "confirm_delete": True,
    "single_click": False,
    "terminal": "kitty",
    "preview": False,
    "thumbnail_limit_mb": 32,
    "search_recursive": False,
    "window": {"width": 1280, "height": 820, "maximized": False},
    "bookmarks": [],
    "sidebar_open": {"places": True, "bookmarks": True, "devices": True},
}


def _merge(base: dict, incoming: dict) -> dict:
    out = dict(base)
    for k, v in (incoming or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Prefs:
    def __init__(self, path: str = PATH):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                incoming = json.load(f)
            if isinstance(incoming, dict):
                self.data = _merge(self.data, incoming)
        except (OSError, ValueError):
            pass
        return self.data

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".files-", suffix=".json",
                                       dir=os.path.dirname(self.path))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError:
            pass

    # -- accessors ---------------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def update(self, **kwargs):
        self.data.update(kwargs)
        self.save()

    def folder_state(self, path: str) -> dict:
        st = self.data.get("per_folder", {}).get(path)
        out = dict(self.data.get("sort", DEFAULTS["sort"]))
        out["view"] = self.data.get("view", "grid")
        out["icon_size"] = self.data.get("icon_size", 112)
        out["show_hidden"] = self.data.get("show_hidden", False)
        if isinstance(st, dict):
            out.update(st)
        return out

    def remember_folder(self, path: str, **state):
        if not path:
            return
        per = self.data.setdefault("per_folder", {})
        cur = per.setdefault(path, {})
        cur.update(state)
        if len(per) > 800:
            for key in list(per)[: len(per) - 700]:
                per.pop(key, None)
        self.save()

    def bookmarks(self) -> list[dict]:
        raw = self.data.get("bookmarks", [])
        out = []
        for b in raw:
            if isinstance(b, str):
                b = {"path": b, "label": os.path.basename(b) or b}
            if isinstance(b, dict) and b.get("path"):
                out.append(b)
        return out

    def add_bookmark(self, path: str, label=None, index=None):
        marks = self.bookmarks()
        if any(b["path"] == path for b in marks):
            return
        item = {"path": path, "label": label or util.display_name(path)}
        if index is None:
            marks.append(item)
        else:
            marks.insert(max(0, index), item)
        self.data["bookmarks"] = marks
        self.save()

    def remove_bookmark(self, path: str):
        self.data["bookmarks"] = [b for b in self.bookmarks() if b["path"] != path]
        self.save()

    def move_bookmark(self, path: str, delta: int):
        marks = self.bookmarks()
        idx = next((i for i, b in enumerate(marks) if b["path"] == path), None)
        if idx is None:
            return
        new = max(0, min(len(marks) - 1, idx + delta))
        marks.insert(new, marks.pop(idx))
        self.data["bookmarks"] = marks
        self.save()


def stars_path() -> str:
    return os.path.join(CONFIG_DIR, "files-stars.json")


def load_stars() -> list[str]:
    try:
        with open(stars_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [p for p in data if isinstance(p, str)]
    except (OSError, ValueError):
        pass
    return []


def save_stars(paths: list[str]):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".stars-", suffix=".json", dir=CONFIG_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(set(paths)), f, indent=2)
        os.replace(tmp, stars_path())
    except OSError:
        pass
