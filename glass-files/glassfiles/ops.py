"""File operations, deliberately GTK-free and defensive about data loss.

Rules of the house:
  * never write through an existing file: copy to a temp sibling, then rename
  * never delete the destination of a move until the copy is complete
  * conflicts are resolved by an explicit callback, not silently
  * everything accepts a threading.Event for cancellation
"""

from __future__ import annotations

import errno
import hashlib
import os
import random
import shutil
import stat
import subprocess
import time
import zipfile

from . import util


class OpError(Exception):
    pass


class Cancelled(Exception):
    pass


class Outcome:
    COPIED = "copied"
    MOVED = "moved"
    SKIPPED = "skipped"
    REPLACED = "replaced"
    MERGED = "merged"
    FAILED = "failed"


COPY = "copy"
MOVE = "move"
LINK = "link"

REPLACE = "replace"
SKIP = "skip"
KEEP_BOTH = "keepboth"
MERGE = "merge"
ASK = "ask"


def _reporthook(progress, cancel):
    state = {"last": 0.0}

    def tick(copied, total, path, force=False):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        now = time.monotonic()
        if progress and (force or now - state["last"] > 0.05):
            state["last"] = now
            progress(copied, total, path)

    return tick


def tree_stats(path: str) -> tuple[int, int]:
    """(byte total, file count). Never follows symlinks."""
    total = 0
    count = 0
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return (st.st_size, 1)
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(ent.path)
                            count += 1
                        else:
                            total += ent.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count


def _copy_file(src: str, dst: str, tick, written: list[int], total: int, cancel) -> None:
    parent = os.path.dirname(dst) or "."
    tmp = os.path.join(parent, f".glass-tmp-{os.getpid()}-{random.randrange(1 << 30):x}")
    try:
        with open(src, "rb") as fsrc:
            fdst = open(tmp, "wb")
            try:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    buf = fsrc.read(1024 * 1024)
                    if not buf:
                        break
                    fdst.write(buf)
                    written[0] += len(buf)
                    tick(written[0], total, src)
            finally:
                fdst.flush()
                os.fsync(fdst.fileno())
                fdst.close()
        shutil.copystat(src, tmp, follow_symlinks=True)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _copy_symlink(src: str, dst: str) -> None:
    target = os.readlink(src)
    if os.path.lexists(dst):
        os.unlink(dst)
    os.symlink(target, dst)


def _copy_dir(src: str, dst: str, tick, written, total, cancel, resolve, depth=0) -> str:
    """Copy src directory to dst. dst must not exist (caller resolved conflicts)."""
    os.makedirs(dst, exist_ok=True)
    try:
        shutil.copystat(src, dst, follow_symlinks=False)
    except OSError:
        pass
    try:
        entries = list(os.scandir(src))
    except OSError as e:
        raise OpError(f"Cannot read {src}: {e.strerror}") from e
    for ent in entries:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        target = os.path.join(dst, ent.name)
        try:
            if ent.is_symlink():
                _copy_symlink(ent.path, target)
            elif ent.is_dir(follow_symlinks=False):
                _copy_dir(ent.path, target, tick, written, total, cancel, resolve, depth + 1)
            elif ent.is_file(follow_symlinks=False):
                _copy_file(ent.path, target, tick, written, total, cancel)
                written[0] += 0  # accounting happens inside _copy_file
            else:
                continue  # sockets, fifos and devices are not copied
        except (Cancelled, OpError):
            raise
        except OSError as e:
            raise OpError(f"{ent.path}: {e.strerror}") from e
    return dst


def _merge_dir(src: str, dst: str, tick, written, total, cancel, resolve) -> None:
    """Merge src into an existing dst, asking about each real conflict."""
    try:
        entries = list(os.scandir(src))
    except OSError as e:
        raise OpError(f"Cannot read {src}: {e.strerror}") from e
    for ent in entries:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        target = os.path.join(dst, ent.name)
        try:
            if not os.path.lexists(target):
                if ent.is_symlink():
                    _copy_symlink(ent.path, target)
                elif ent.is_dir(follow_symlinks=False):
                    _copy_dir(ent.path, target, tick, written, total, cancel, resolve)
                elif ent.is_file(follow_symlinks=False):
                    _copy_file(ent.path, target, tick, written, total, cancel)
                continue
            if ent.is_dir(follow_symlinks=False) and os.path.isdir(target) and not os.path.islink(target):
                _merge_dir(ent.path, target, tick, written, total, cancel, resolve)
                continue
            answer = resolve(ent.path, target, os.path.isdir(ent.path), os.path.isdir(target)) if resolve else KEEP_BOTH
            if answer == SKIP:
                continue
            if answer == KEEP_BOTH:
                target = _unique(target)
            elif answer == MERGE and os.path.isdir(target):
                _merge_dir(ent.path, target, tick, written, total, cancel, resolve)
                continue
            if ent.is_symlink():
                _copy_symlink(ent.path, target)
            elif ent.is_dir(follow_symlinks=False):
                _copy_dir(ent.path, target, tick, written, total, cancel, resolve)
            elif ent.is_file(follow_symlinks=False):
                _copy_file(ent.path, target, tick, written, total, cancel)
        except (Cancelled, OpError):
            raise
        except OSError as e:
            raise OpError(f"{ent.path}: {e.strerror}") from e


def _remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.unlink(path)


def _decide(dst: str, resolve, src: str, is_dir: bool, force: str | None):
    """Return 'skip', 'keepboth' or 'replace' after asking the resolver."""
    if not os.path.lexists(dst):
        return "go"
    if force in (REPLACE, SKIP, KEEP_BOTH, MERGE):
        return force
    if resolve is None:
        return KEEP_BOTH
    dst_is_dir = os.path.isdir(dst) and not os.path.islink(dst)
    answer = resolve(src, dst, is_dir, dst_is_dir)
    return answer or SKIP


def _unique(dst: str) -> str:
    parent = os.path.dirname(dst) or "."
    return util.unique_path(parent, os.path.basename(dst), " (copy)")


def copy_move_one(src: str, dest_dir: str, mode: str, resolve=None, progress=None,
                  cancel=None, total: int | None = None, written=None, force=None):
    """Copy or move one path into dest_dir. Returns (outcome, final_path)."""
    tick = _reporthook(progress, cancel)
    if written is None:
        written = [0]
    if total is None:
        total = tree_stats(src)[0]
    base = os.path.basename(src.rstrip(os.sep)) or "unnamed"
    dst = os.path.join(dest_dir, base)
    if util.same_path(src, dst):
        if mode == MOVE:
            return Outcome.SKIPPED, src
        # Copying a folder into itself: put the copy beside it.
        dst = _unique(dst)
    st = os.lstat(src)
    is_dir = stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)
    decision = _decide(dst, resolve, src, is_dir, force)
    if decision == SKIP:
        return Outcome.SKIPPED, dst
    if decision == MERGE:
        if not is_dir:
            return copy_move_one(src, dest_dir, mode, resolve, progress, cancel, total,
                                 written, force=REPLACE)
        outcome = Outcome.MERGED
    elif decision == KEEP_BOTH:
        dst = _unique(dst)
        outcome = Outcome.COPIED if mode != MOVE else Outcome.MOVED
    elif decision == REPLACE:
        outcome = Outcome.REPLACED
    else:
        outcome = Outcome.COPIED if mode != MOVE else Outcome.MOVED

    src_dev = os.lstat(src).st_dev
    try:
        dest_dev = os.stat(dest_dir).st_dev
    except OSError:
        dest_dev = src_dev

    if is_dir and decision == MERGE:
        _merge_dir(src, dst, tick, written, total, cancel, resolve)
        if mode == MOVE:
            _remove(src)
            return Outcome.MOVED, dst
        return Outcome.MERGED, dst

    if is_dir and decision == REPLACE:
        # Swap in a finished tree so a failure never leaves half a folder.
        if mode == MOVE and src_dev == dest_dev:
            try:
                os.rename(src, dst)
                tick(total, total, src, True)
                return Outcome.MOVED, dst
            except OSError:
                pass
        staging = os.path.join(dest_dir, f".glass-stage-{os.getpid()}-{random.randrange(1 << 30):x}")
        try:
            _copy_dir(src, staging, tick, written, total, cancel, resolve)
            old = None
            if os.path.lexists(dst):
                old = dst + f".glass-old-{random.randrange(1 << 30):x}"
                os.rename(dst, old)
            try:
                os.rename(staging, dst)
            except OSError:
                if old:
                    os.rename(old, dst)
                raise
            if old:
                _remove(old)
            if mode == MOVE:
                _remove(src)
                return Outcome.MOVED, dst
            return outcome, dst
        except BaseException:
            if os.path.isdir(staging):
                try:
                    _remove(staging)
                except OSError:
                    pass
            raise

    if is_dir:
        _copy_dir(src, dst, tick, written, total, cancel, resolve)
        if mode == MOVE:
            _remove(src)
            return Outcome.MOVED, dst
        return outcome, dst

    if stat.S_ISLNK(st.st_mode):
        _copy_symlink(src, dst)
        if mode == MOVE:
            _remove(src)
            tick(total, total, src, True)
            return Outcome.MOVED, dst
        tick(total, total, src, True)
        return outcome, dst

    if not stat.S_ISREG(st.st_mode):
        return Outcome.SKIPPED, dst

    if mode == MOVE and src_dev == dest_dev and decision != KEEP_BOTH:
        try:
            os.rename(src, dst)
            tick(total, total, src, True)
            return Outcome.MOVED, dst
        except OSError as e:
            if e.errno not in (errno.EXDEV, errno.EBUSY):
                raise OpError(f"{src}: {e.strerror}") from e

    _copy_file(src, dst, tick, written, total, cancel)
    if mode == MOVE:
        try:
            _remove(src)
        except OSError as e:
            raise OpError(f"Copied but could not remove {src}: {e.strerror}") from e
        return Outcome.MOVED, dst
    return outcome, dst


def copy_move(sources, dest_dir: str, mode: str, resolve=None, progress=None,
              cancel=None) -> list[dict]:
    if not os.path.isdir(dest_dir):
        raise OpError(f"Not a folder: {dest_dir}")
    total = sum(tree_stats(s)[0] for s in sources)
    written = [0]
    results = []
    for src in sources:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if not os.path.lexists(src):
            results.append({"src": src, "outcome": Outcome.FAILED, "dest": None,
                            "error": "missing"})
            continue
        try:
            outcome, final = copy_move_one(src, dest_dir, mode, resolve, progress, cancel,
                                           total, written)
        except Cancelled:
            raise
        except (OpError, OSError) as e:
            results.append({"src": src, "outcome": Outcome.FAILED, "dest": None,
                            "error": str(e)})
            continue
        results.append({"src": src, "outcome": outcome, "dest": final})
    return results


def rename(path: str, new_name: str) -> str:
    new_name = (new_name or "").strip()
    if not new_name or new_name in (".", "..") or "/" in new_name or "\x00" in new_name:
        raise OpError("That is not a valid name.")
    parent = os.path.dirname(path.rstrip(os.sep)) or "/"
    target = os.path.join(parent, new_name)
    if target == path:
        return path
    if util.same_path(target, path):
        return path
    if os.path.lexists(target):
        raise OpError("A file with that name already exists.")
    os.rename(path, target)
    return target


def duplicate(path: str, progress=None, cancel=None, suffix=" (copy)") -> str:
    parent = os.path.dirname(path.rstrip(os.sep)) or "/"
    target = util.unique_path(parent, os.path.basename(path.rstrip(os.sep)), suffix)
    total = tree_stats(path)[0]
    written = [0]
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            _copy_dir(path, target, _reporthook(progress, cancel), written, total, cancel, None)
        elif os.path.islink(path):
            _copy_symlink(path, target)
        else:
            _copy_file(path, target, _reporthook(progress, cancel), written, total, cancel)
    except BaseException:
        try:
            _remove(target)
        except OSError:
            pass
        raise
    return target


def move_to(path: str, new_path: str, progress=None, cancel=None) -> str:
    """Atomic rename when possible, safe copy+delete otherwise."""
    if os.path.lexists(new_path):
        raise OpError("Destination already exists.")
    try:
        os.rename(path, new_path)
        return new_path
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise OpError(e.strerror or str(e)) from e
    parent = os.path.dirname(new_path)
    total = tree_stats(path)[0]
    written = [0]
    tick = _reporthook(progress, cancel)
    if os.path.isdir(path) and not os.path.islink(path):
        _copy_dir(path, new_path, tick, written, total, cancel, None)
    else:
        _copy_file(path, new_path, tick, written, total, cancel)
    _remove(path)
    return new_path


def delete(paths, progress=None, cancel=None) -> list[str]:
    errors = []
    total = max(1, len(paths))
    for i, path in enumerate(paths):
        try:
            _remove(path)
        except OSError as e:
            errors.append(f"{path}: {e.strerror}")
        if progress:
            progress((i + 1) / total, path)
    return errors


def create_folder(parent: str, name: str = "New Folder", unique: bool = True) -> str:
    target = os.path.join(parent, name)
    if unique:
        target = util.unique_path(parent, name)
    os.makedirs(target, exist_ok=False)
    return target


def create_file(parent: str, name: str = "Untitled", content: bytes = b"",
                unique: bool = True) -> str:
    target = os.path.join(parent, name)
    if unique:
        target = util.unique_path(parent, name)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as f:
        if content:
            f.write(content)
    return target


def symlink(target: str, link_path: str) -> str:
    if os.path.lexists(link_path):
        raise OpError("A file with that name already exists.")
    os.symlink(target, link_path)
    return link_path


def chmod(path: str, mode: int) -> None:
    os.chmod(path, mode)


def copy_path_text(path: str) -> str:
    return path


# ---------------------------------------------------------------- archives --

ARCHIVE_FORMATS = {
    "zip": ("zip", ".zip", ["zip"]),
    "tar.gz": ("tar", ".tar.gz", ["gzip"]),
    "tar.zst": ("tar", ".tar.zst", ["zstd"]),
    "tar.xz": ("tar", ".tar.xz", ["xz"]),
    "7z": ("7zip", ".7z", []),
}


def _bsdtar(*args, cancel=None) -> subprocess.CompletedProcess:
    cmd = ["bsdtar", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=util.clean_env())
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            continue


def compress(paths, dest: str, fmt: str = "zip", progress=None, cancel=None) -> str:
    if fmt not in ARCHIVE_FORMATS:
        raise OpError("Unknown archive format.")
    _, ext, _ = ARCHIVE_FORMATS[fmt]
    if not dest.endswith(ext):
        dest += ext
    dest = util.unique_path(os.path.dirname(dest), os.path.basename(dest)) if os.path.lexists(dest) else dest
    if len(paths) == 1:
        parent = os.path.dirname(os.path.abspath(paths[0])) or "/"
    else:
        parent = os.path.commonpath([os.path.abspath(p) for p in paths])
        if os.path.isfile(parent):
            parent = os.path.dirname(parent)
    names = [os.path.relpath(os.path.abspath(p), parent) for p in paths]
    out_dir = os.path.dirname(dest) or "."
    tmp = os.path.join(out_dir, f".glass-archive-{random.randrange(1 << 30):x}{ext}")
    try:
        if fmt == "7z":
            proc = subprocess.run(["7z", "a", "-y", "-bd", tmp, *names], cwd=parent,
                                  capture_output=True, env=util.clean_env())
            ok = proc.returncode == 0
        else:
            proc = subprocess.run(["bsdtar", "-a", "-c", "-f", tmp, *names], cwd=parent,
                                  capture_output=True, env=util.clean_env())
            ok = proc.returncode == 0
        if not ok:
            raise OpError((proc.stderr or b"").decode("utf-8", "replace")[:400] or "Archive failed")
        if os.path.lexists(dest):
            os.unlink(dest)
        os.rename(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if progress:
        progress(1.0, dest, True)
    return dest


def _unsafe_member(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return any(p == ".." for p in parts) or name.startswith("/")


def list_archive(path: str, limit: int = 500) -> list[str]:
    if path.lower().endswith(".7z"):
        proc = subprocess.run(["7z", "l", "-ba", path], capture_output=True,
                              env=util.clean_env())
        lines = proc.stdout.decode("utf-8", "replace").splitlines()
        out = []
        for line in lines:
            parts = line.split("  ")
            if len(parts) >= 2 and parts[-1].strip():
                out.append(parts[-1].strip())
        return out[:limit]
    proc = _bsdtar("-tf", path)
    if proc.returncode != 0:
        raise OpError((proc.stderr or b"").decode("utf-8", "replace")[:300])
    names = proc.stdout.decode("utf-8", "replace").splitlines()
    return names[:limit]


def extract(archive: str, dest_dir: str | None = None, into_folder: bool = True,
            progress=None, cancel=None) -> str:
    if not os.path.isfile(archive):
        raise OpError("Archive not found.")
    base = os.path.basename(archive)
    if dest_dir is None:
        dest_dir = os.path.dirname(archive) or "."
    if into_folder:
        stem = base
        for suffix in (".tar.gz", ".tar.zst", ".tar.xz", ".tar.bz2", ".7z", ".zip", ".tar"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        dest_dir = util.unique_path(dest_dir, stem) if os.path.lexists(os.path.join(dest_dir, stem)) else os.path.join(dest_dir, stem)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        members = list_archive(archive, limit=200000)
    except OpError:
        members = []
    if any(_unsafe_member(m) for m in members):
        raise OpError("Archive contains unsafe paths; refusing to extract.")
    if archive.lower().endswith(".7z"):
        proc = subprocess.run(["7z", "x", "-y", "-bd", f"-o{dest_dir}", archive],
                              capture_output=True, env=util.clean_env())
        ok = proc.returncode == 0
        err = proc.stderr
    else:
        proc = subprocess.run(["bsdtar", "-xf", archive, "-C", dest_dir],
                              capture_output=True, env=util.clean_env())
        ok = proc.returncode == 0
        err = proc.stderr
    if not ok:
        raise OpError((err or b"").decode("utf-8", "replace")[:400] or "Extraction failed")
    if progress:
        progress(1.0, dest_dir, True)
    return dest_dir


# ---------------------------------------------------------------- checksum --

def checksum(path: str, algorithm: str = "sha256", cancel=None) -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            buf = f.read(1024 * 1024)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def archive_name_for(paths, fmt: str) -> str:
    if len(paths) == 1:
        stem = os.path.basename(paths[0].rstrip(os.sep)) or "archive"
    else:
        stem = "Archive"
    return stem + ARCHIVE_FORMATS[fmt][1]


def iso_zip_ok() -> bool:
    return zipfile is not None
