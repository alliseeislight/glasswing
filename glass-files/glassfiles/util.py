"""Small, GTK-free helpers shared by the rest of Glass Files.

Nothing in here imports Gtk/Gdk, so it is all unit-testable headless.
"""

from __future__ import annotations

import datetime as _dt
import grp
import mimetypes
import os
import pwd
import re
import shutil
import stat as _stat
import time
import urllib.parse

HOME = os.path.expanduser("~")
APP_ID = "local.glass.files"
APP_NAME = "Glass Files"
VERSION = "1.0.0"

# Extensions that look like text even when the mimetype db is unhelpful.
TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".ini", ".cfg", ".conf", ".toml",
    ".yaml", ".yml", ".json", ".xml", ".csv", ".tsv", ".sql", ".sh", ".fish",
    ".bash", ".zsh", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".scss",
    ".html", ".htm", ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".lua", ".vim",
    ".nix", ".desktop", ".service", ".env", ".gitignore", ".diff", ".patch",
}


def fsdec(name: str) -> str:
    """Make a possibly surrogate-escaped filesystem name safe to render."""
    try:
        return os.fsencode(name).decode("utf-8", "replace")
    except Exception:
        try:
            return name.encode("utf-8", "replace").decode("utf-8", "replace")
        except Exception:
            return "?"


def entry_key(name: str) -> str:
    """Natural-sort key: file2 before file10, case-insensitive first."""
    name = name or ""
    parts = re.split(r"(\d+)", name.casefold())
    key = []
    for p in parts:
        if p.isdigit():
            key.append((0, int(p)))
        elif p:
            key.append((1, p))
    return key


def natural_key(name: str):
    return entry_key(name)


_USER_CACHE: dict[int, str] = {}
_GROUP_CACHE: dict[int, str] = {}


def user_name(uid: int) -> str:
    if uid not in _USER_CACHE:
        try:
            _USER_CACHE[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _USER_CACHE[uid] = str(uid)
    return _USER_CACHE[uid]


def group_name(gid: int) -> str:
    if gid not in _GROUP_CACHE:
        try:
            _GROUP_CACHE[gid] = grp.getgrgid(gid).gr_name
        except KeyError:
            _GROUP_CACHE[gid] = str(gid)
    return _GROUP_CACHE[gid]


def human_size(size, decimals: int = 1) -> str:
    if size is None:
        return "--"
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "--"
    if size < 0:
        return "--"
    units = ("B", "kB", "MB", "GB", "TB", "PB")
    idx = 0
    while size >= 1000.0 and idx < len(units) - 1:
        size /= 1000.0
        idx += 1
    if idx == 0:
        return f"{int(size)} B"
    txt = f"{size:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{txt} {units[idx]}"


def human_rate(bps: float) -> str:
    return human_size(bps) + "/s"


def human_eta(seconds: float) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def format_time(ts, now=None) -> str:
    """Friendly mtime: Today 14:03 / Yesterday 09:12 / 12 Nov 2025."""
    if not ts:
        return "--"
    try:
        dt = _dt.datetime.fromtimestamp(float(ts))
    except (ValueError, OSError, OverflowError):
        return "--"
    now = now or _dt.datetime.now()
    d = dt.date()
    today = now.date()
    if d == today:
        return "Today " + dt.strftime("%H:%M")
    if d == today - _dt.timedelta(days=1):
        return "Yesterday " + dt.strftime("%H:%M")
    if d.year == today.year:
        return dt.strftime("%d %b %H:%M")
    return dt.strftime("%d %b %Y")


def format_date_full(ts) -> str:
    if not ts:
        return "--"
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%a %d %b %Y, %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "--"


def perm_string(mode: int) -> str:
    if mode is None:
        return "---------"
    return _stat.filemode(int(mode))[1:]


def octal_mode(mode: int) -> str:
    if mode is None:
        return "0000"
    return format(int(mode) & 0o7777, "04o")


def parse_octal(text: str):
    text = (text or "").strip()
    if not re.fullmatch(r"[0-7]{1,4}", text):
        return None
    return int(text, 8) & 0o7777


def shared_dir(path: str) -> str:
    """A directory under $HOME is private; anything else is shared."""
    try:
        home = os.path.realpath(HOME)
        real = os.path.realpath(path)
        return "" if (real == home or real.startswith(home + os.sep)) else "shared"
    except OSError:
        return "shared"


def expand_path(text: str) -> str:
    """Turn ~, $VARS and relative paths into an absolute path."""
    text = (text or "").strip().strip("\x00")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    text = os.path.expandvars(text)
    if text == "~" or text.startswith("~/"):
        text = HOME + text[1:]
    if not text:
        text = HOME
    if text.startswith("file://"):
        text = uri_to_path(text) or HOME
    if not os.path.isabs(text):
        text = os.path.abspath(os.path.join(HOME, text))
    text = os.path.normpath(text)
    return text


def path_to_uri(path: str) -> str:
    try:
        raw = os.fsencode(path)
    except Exception:
        raw = path.encode("utf-8", "replace")
    return "file://" + urllib.parse.quote_from_bytes(raw, safe="/")


def uri_to_path(uri: str):
    try:
        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme != "file":
            return None
        raw = urllib.parse.unquote_to_bytes(parsed.path)
        return os.fsdecode(raw)
    except Exception:
        return None


def mime_type(path: str) -> str:
    mt, _ = mimetypes.guess_type(path)
    if mt:
        return mt
    if os.path.isdir(path):
        return "inode/directory"
    return "application/octet-stream"


def is_text_like(path: str, mime: str = "") -> bool:
    if mime.startswith("text/"):
        return True
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        return True
    return mime in {
        "application/json", "application/xml", "application/javascript",
        "application/x-shellscript", "application/x-desktop",
    }


def display_name(path: str) -> str:
    name = os.path.basename(path.rstrip(os.sep)) or path
    return fsdec(name)


def dir_size(path: str, cancel=None, progress=None) -> int:
    """Recursive byte size. Symlinks are counted as their own length."""
    total = 0
    if not os.path.isdir(path) or os.path.islink(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            return total
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
        if progress is not None:
            progress(total)
    return total


def free_space(path: str) -> tuple[int, int]:
    try:
        u = shutil.disk_usage(path)
        return u.free, u.total
    except OSError:
        return 0, 0


def unique_path(parent: str, name: str, suffix: str = "") -> str:
    """foo.txt -> foo (copy).txt -> foo (copy 2).txt, never overwriting."""
    base, ext = os.path.splitext(name)
    if name.endswith(".tar.gz"):
        base, ext = name[:-7], ".tar.gz"
    first = f"{base}{suffix}{ext}"
    cand = os.path.join(parent, first)
    n = 2
    while os.path.lexists(cand):
        cand = os.path.join(parent, f"{base}{suffix} {n}{ext}")
        n += 1
    return cand


def same_path(a: str, b: str) -> bool:
    try:
        return os.path.normpath(os.path.realpath(a)) == os.path.normpath(os.path.realpath(b))
    except OSError:
        return os.path.normpath(a) == os.path.normpath(b)


def safe_stat(path: str):
    try:
        return os.lstat(path)
    except OSError:
        return None


def dirs_from_xdg() -> dict[str, str]:
    """Parse ~/.config/user-dirs.dirs without shelling out."""
    out = {
        "DESKTOP": os.path.join(HOME, "Desktop"),
        "DOCUMENTS": os.path.join(HOME, "Documents"),
        "DOWNLOAD": os.path.join(HOME, "Downloads"),
        "MUSIC": os.path.join(HOME, "Music"),
        "PICTURES": os.path.join(HOME, "Pictures"),
        "VIDEOS": os.path.join(HOME, "Videos"),
        "TEMPLATES": os.path.join(HOME, "Templates"),
        "PUBLICSHARE": os.path.join(HOME, "Public"),
    }
    cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "user-dirs.dirs")
    try:
        with open(cfg, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'\s*XDG_(\w+)_DIR\s*=\s*"([^"]*)"', line)
                if not m:
                    continue
                key, val = m.group(1), m.group(2)
                val = val.replace("$HOME", HOME)
                if key in out:
                    out[key] = val
    except OSError:
        pass
    return out


def pretty_type(path: str, mime: str = "") -> str:
    mime = mime or mime_type(path)
    if mime == "inode/directory":
        return "Folder"
    ext = os.path.splitext(path)[1].lstrip(".").upper()
    table = {
        "text/plain": "Text", "application/pdf": "PDF document",
        "image/png": "PNG image", "image/jpeg": "JPEG image",
        "image/gif": "GIF image", "image/svg+xml": "SVG image",
        "image/webp": "WebP image", "video/mp4": "MP4 video",
        "audio/mpeg": "MP3 audio", "application/zip": "ZIP archive",
        "application/x-tar": "TAR archive", "inode/symlink": "Link",
    }
    if mime in table:
        return table[mime]
    if ext:
        return f"{ext} file"
    return mime or "File"


def elide_middle(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return text
    keep = max(4, (limit - 1) // 2)
    return text[:keep] + "\u2026" + text[-keep:]


def clean_env() -> dict[str, str]:
    """Environment for helper binaries: never let the aniworld venv leak in."""
    env = dict(os.environ)
    path = "/usr/local/bin:/usr/bin:/bin"
    env["PATH"] = path
    for var in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(var, None)
    return env


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    return human_eta(seconds)


def now_ts() -> float:
    return time.time()
