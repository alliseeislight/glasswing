"""Recursive search. Threaded, cancellable, GTK-free."""

from __future__ import annotations

import os
import subprocess

from . import util


def _opts(show_hidden: bool):
    return ["--hidden"] if show_hidden else []


def _fd(base: str, query: str, limit: int, show_hidden: bool, cancel) -> list[str]:
    cmd = [
        "fd", "--color=never", "--print0", "--absolute-path",
        "--max-results", str(limit), "--fixed-strings", *_opts(show_hidden),
        "--", query, base,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=util.clean_env(), cwd=base)
    out = []
    try:
        while True:
            chunk = proc.stdout.read(8192)
            if not chunk:
                break
            if cancel is not None and cancel.is_set():
                proc.kill()
                return out
            out.extend(p for p in chunk.split(b"\0") if p)
            if len(out) >= limit:
                proc.kill()
                break
    finally:
        proc.stdout.close()
        proc.wait()
    return [os.fsdecode(p) for p in out[:limit]]


def _walk(base: str, query: str, limit: int, show_hidden: bool, cancel) -> list[str]:
    q = query.casefold()
    out = []
    stack = [base]
    base_depth = base.rstrip(os.sep).count(os.sep)
    while stack:
        if cancel is not None and cancel.is_set():
            return out
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    if not show_hidden and ent.name.startswith("."):
                        continue
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(ent.path)
                    except OSError:
                        continue
                    if q in ent.name.casefold():
                        out.append(ent.path)
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out


def search(base: str, query: str, *, limit: int = 3000, show_hidden: bool = False,
           cancel=None) -> list[str]:
    query = (query or "").strip()
    if not query or not os.path.isdir(base):
        return []
    if shutil_which("fd"):
        try:
            return _fd(base, query, limit, show_hidden, cancel)
        except Exception:
            pass
    return _walk(base, query, limit, show_hidden, cancel)


def shutil_which(name: str):
    import shutil

    return shutil.which(name, path="/usr/local/bin:/usr/bin:/bin")


def matches(path: str, *, kinds=None, days: int = 0, size_band=None) -> bool:
    from .model import KINDS  # noqa: delayed, model is safe headless too

    try:
        st = os.lstat(path)
    except OSError:
        return False
    is_directory = os.path.isdir(path) and not os.path.islink(path)
    mime = "inode/directory" if is_directory else util.mime_type(path)
    if kinds:
        if not any(KINDS.get(k, lambda m, d: False)(mime, is_directory) for k in kinds):
            return False
    if days:
        import time

        if time.time() - st.st_mtime > days * 86400:
            return False
    if size_band:
        lo, hi = size_band
        if is_directory:
            return False
        if lo is not None and st.st_size < lo:
            return False
        if hi is not None and st.st_size > hi:
            return False
    return True
