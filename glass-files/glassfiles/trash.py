"""freedesktop.org Trash specification, in plain Python.

Layout:  $XDG_DATA_HOME/Trash/{files,info}
Info:    files/NAME  <->  info/NAME.trashinfo
Contents:
    [Trash Info]
    Path=/path/to/file
    DeletionDate=2026-11-15T01:23:45
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import stat
import urllib.parse

from . import util


def _home_trash() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(util.HOME, ".local", "share")
    return os.path.join(data, "Trash")


def _mount_point(path: str) -> str:
    path = os.path.abspath(path)
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def _escape_path(path: str) -> str:
    try:
        raw = os.fsencode(path)
        return urllib.parse.quote_from_bytes(raw, safe="/")
    except Exception:
        return urllib.parse.quote(path, safe="/")


def _unescape_path(text: str) -> str:
    try:
        return os.fsdecode(urllib.parse.unquote_to_bytes(text))
    except Exception:
        return urllib.parse.unquote(text)


def trash_root_for(path: str) -> str:
    """Return the Trash directory that should hold `path`."""
    home = os.path.realpath(util.HOME)
    real_parent = os.path.realpath(os.path.dirname(os.path.abspath(path)) or "/")
    if real_parent == home or real_parent.startswith(home + os.sep):
        return _home_trash()
    mount = _mount_point(real_parent)
    uid = os.getuid()
    # Shared .Trash with a sticky bit is preferred per spec.
    shared = os.path.join(mount, ".Trash")
    try:
        st = os.stat(shared)
        if stat.S_ISDIR(st.st_mode) and (st.st_mode & stat.S_ISVTX):
            per_user = os.path.join(shared, str(uid))
            os.makedirs(per_user, exist_ok=True)
            test = os.path.join(per_user, ".write-test")
            with open(test, "w"):
                pass
            os.unlink(test)
            return per_user
    except OSError:
        pass
    own = os.path.join(mount, f".Trash-{uid}")
    try:
        os.makedirs(os.path.join(own, "files"), exist_ok=True)
        os.makedirs(os.path.join(own, "info"), exist_ok=True)
        test = os.path.join(own, ".write-test")
        with open(test, "w"):
            pass
        os.unlink(test)
        return own
    except OSError:
        return _home_trash()


def _dirs(root: str) -> tuple[str, str]:
    files = os.path.join(root, "files")
    info = os.path.join(root, "info")
    return files, info


def _free_name(files_dir: str, name: str) -> str:
    cand = name
    n = 1
    while os.path.lexists(os.path.join(files_dir, cand)) or os.path.lexists(
        os.path.join(files_dir, cand + ".trashinfo")
    ):
        if "." in name and not name.startswith("."):
            stem, _, ext = name.rpartition(".")
            cand = f"{stem}.{n}.{ext}"
        else:
            cand = f"{name}.{n}"
        n += 1
    return cand


def trash(paths, progress=None) -> list[dict]:
    """Move paths to the trash. Returns one record per successfully trashed item."""
    records = []
    total = len(paths)
    for idx, path in enumerate(paths):
        path = os.path.abspath(path)
        if not os.path.lexists(path):
            continue
        if os.path.dirname(path) == _home_trash():
            continue  # already in the bin
        root = trash_root_for(path)
        files_dir, info_dir = _dirs(root)
        try:
            os.makedirs(files_dir, exist_ok=True)
            os.makedirs(info_dir, exist_ok=True)
        except OSError:
            raise
        name = os.path.basename(path.rstrip(os.sep)) or "unnamed"
        name = _free_name(files_dir, name)
        info_path = os.path.join(info_dir, name + ".trashinfo")
        payload = (
            "[Trash Info]\n"
            f"Path={_escape_path(path)}\n"
            f"DeletionDate={_dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n"
        )
        # Write the metadata first: a file in the bin without metadata can't be
        # restored, so this order is what keeps the bin consistent.
        try:
            with open(info_path, "x", encoding="utf-8") as f:
                f.write(payload)
        except FileExistsError:
            name = _free_name(files_dir, name)
            info_path = os.path.join(info_dir, name + ".trashinfo")
            with open(info_path, "x", encoding="utf-8") as f:
                f.write(payload)
        dest = os.path.join(files_dir, name)
        try:
            try:
                os.rename(path, dest)
            except OSError:
                shutil.move(path, dest)
        except Exception:
            try:
                os.unlink(info_path)
            except OSError:
                pass
            raise
        records.append(
            {
                "trashed": dest,
                "original": path,
                "info": info_path,
                "name": name,
                "date": _dt.datetime.now().timestamp(),
            }
        )
        if progress:
            progress((idx + 1) / max(1, total), name)
    return records


def _parse_info(info_path: str) -> dict | None:
    rec = {"info": info_path, "original": None, "date": 0.0}
    try:
        with open(info_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    in_section = False
    for line in lines:
        if line.strip().lower() == "[trash info]":
            in_section = True
            continue
        if not in_section or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()
        if key == "path":
            rec["original"] = _unescape_path(val.strip())
        elif key == "deletiondate":
            try:
                rec["date"] = _dt.datetime.strptime(val.strip(), "%Y-%m-%dT%H:%M:%S").timestamp()
            except ValueError:
                rec["date"] = 0.0
    if not rec["original"]:
        return None
    name = os.path.basename(info_path)[: -len(".trashinfo")]
    rec["name"] = name
    rec["trashed"] = os.path.join(os.path.dirname(info_path), "..", "files", name)
    rec["trashed"] = os.path.normpath(rec["trashed"])
    return rec


def list_trash() -> list[dict]:
    root = _home_trash()
    _, info_dir = _dirs(root)
    out = []
    try:
        names = os.listdir(info_dir)
    except OSError:
        return out
    for name in names:
        if not name.endswith(".trashinfo"):
            continue
        rec = _parse_info(os.path.join(info_dir, name))
        if not rec:
            continue
        try:
            st = os.lstat(rec["trashed"])
            rec["size"] = st.st_size if not stat.S_ISDIR(st.st_mode) else None
            rec["mtime"] = st.st_mtime
            rec["is_dir"] = stat.S_ISDIR(st.st_mode)
            rec["is_link"] = stat.S_ISLNK(st.st_mode)
        except OSError:
            rec["size"] = None
            rec["mtime"] = rec["date"]
            rec["is_dir"] = False
            rec["is_link"] = False
        rec["display"] = util.fsdec(rec["name"])
        out.append(rec)
    out.sort(key=lambda r: r.get("date", 0), reverse=True)
    return out


def trash_count() -> int:
    _, info_dir = _dirs(_home_trash())
    try:
        return sum(1 for n in os.listdir(info_dir) if n.endswith(".trashinfo"))
    except OSError:
        return 0


def restore(records) -> list[dict]:
    """Restore trashed items. Never overwrites: collides get a ' (restored)' name."""
    done = []
    for rec in records:
        trashed = rec["trashed"]
        original = rec["original"]
        info = rec["info"]
        if not os.path.lexists(trashed):
            continue
        parent = os.path.dirname(original) or util.HOME
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            parent = util.HOME
        if os.path.lexists(original):
            target = util.unique_path(parent, os.path.basename(original), " (restored)")
        else:
            target = original
        try:
            try:
                os.rename(trashed, target)
            except OSError:
                shutil.move(trashed, target)
            os.unlink(info)
        except Exception:
            continue
        done.append({"restored": target, "original": original})
    return done


def purge(records) -> int:
    """Permanently delete specific trashed items."""
    n = 0
    for rec in records:
        trashed = rec["trashed"]
        try:
            if os.path.isdir(trashed) and not os.path.islink(trashed):
                shutil.rmtree(trashed)
            elif os.path.lexists(trashed):
                os.unlink(trashed)
            try:
                os.unlink(rec["info"])
            except OSError:
                pass
            n += 1
        except OSError:
            continue
    return n


def empty(progress=None) -> int:
    root = _home_trash()
    files_dir, info_dir = _dirs(root)
    n = 0
    errors = 0
    try:
        names = os.listdir(files_dir)
    except OSError:
        names = []
    total = max(1, len(names))
    for i, name in enumerate(names):
        path = os.path.join(files_dir, name)
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
            n += 1
        except OSError:
            errors += 1
        try:
            os.unlink(os.path.join(info_dir, name + ".trashinfo"))
        except OSError:
            pass
        if progress:
            progress((i + 1) / total, name)
    # Orphaned metadata (item already gone) is still metadata to clear.
    try:
        for name in os.listdir(info_dir):
            try:
                os.unlink(os.path.join(info_dir, name))
            except OSError:
                pass
    except OSError:
        pass
    return n
