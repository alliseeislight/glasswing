"""Thumbnail cache: reads the freedesktop cache, fills it lazily off-thread."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

from . import util

CACHE_HOME = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.join(util.HOME, ".cache"), "thumbnails"
)
SIZES = {"normal": 128, "large": 256, "x-large": 512}

IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".avif", ".heic", ".jxl", ".svg", ".ico",
}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg"}
PDF_EXT = {".pdf"}


def _key(uri: str) -> str:
    return hashlib.md5(uri.encode("utf-8", "replace")).hexdigest()


def size_dir(size: str = "large") -> str:
    return os.path.join(CACHE_HOME, size if size in SIZES else "large")


def _fresh(path: str, cache: str) -> bool:
    """A cached thumbnail is only valid while the source is not newer."""
    try:
        return os.stat(cache).st_mtime >= os.stat(path).st_mtime
    except OSError:
        return False


def existing(path: str, size: str = "large") -> str | None:
    uri = util.path_to_uri(path)
    cand = os.path.join(size_dir(size), _key(uri) + ".png")
    return cand if os.path.isfile(cand) and _fresh(path, cand) else None


def forget(path: str) -> int:
    """Drop every cached size for a file, e.g. after rotating it."""
    uri = util.path_to_uri(path)
    key = _key(uri)
    removed = 0
    for size in SIZES:
        cand = os.path.join(size_dir(size), key + ".png")
        try:
            os.unlink(cand)
            removed += 1
        except OSError:
            pass
    return removed


def can_rotate(path: str) -> bool:
    return (bool(path) and os.path.splitext(path)[1].lower() in util.ROTATE_EXT
            and os.path.isfile(path) and not os.path.islink(path))


def is_thumbnailable(path: str, mime: str = "") -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT or ext in VIDEO_EXT or ext in PDF_EXT:
        return True
    return mime.startswith(("image/", "video/")) or mime == "application/pdf"


def _write_png(img, dest: str, uri: str, mtime: int) -> None:
    """Write atomically, with the freedesktop Thumb::URI/MTime metadata."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".glass-thumb-", suffix=".png",
                               dir=os.path.dirname(dest))
    os.close(fd)
    try:
        from PIL import PngImagePlugin

        meta = PngImagePlugin.PngInfo()
        meta.add_text("Thumb::URI", uri)
        meta.add_text("Thumb::MTime", str(int(mtime)))
        meta.add_text("Software", "Glass Files")
        img.save(tmp, "PNG", pnginfo=meta, optimize=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _scaled(img, px: int):
    from PIL import Image

    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError("empty image")
    scale = min(px / w, px / h)
    if scale < 1:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    return img


def generate(path: str, size: str = "large") -> str | None:
    """Blocking thumbnail generation. Returns the cache path or None."""
    px = SIZES.get(size, 256)
    ext = os.path.splitext(path)[1].lower()
    uri = util.path_to_uri(path)
    dest = os.path.join(size_dir(size), _key(uri) + ".png")
    if os.path.isfile(dest) and _fresh(path, dest):
        return dest
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size == 0 or not os.path.isfile(path):
        return None
    tmpdir = tempfile.mkdtemp(prefix=".glass-thumb-")
    try:
        from PIL import Image, ImageOps

        if ext in IMAGE_EXT and ext != ".svg":
            try:
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im)
                    im.thumbnail((px, px), Image.LANCZOS)
                    _write_png(im, dest, uri, st.st_mtime)
                    return dest
            except Exception:
                pass

        if ext == ".svg":
            out = os.path.join(tmpdir, "svg.png")
            proc = subprocess.run(
                ["rsvg-convert", "-w", str(px), "-h", str(px), "-o", out, path],
                capture_output=True, env=util.clean_env(), timeout=20,
            )
            if proc.returncode == 0 and os.path.isfile(out):
                with Image.open(out) as im:
                    _write_png(im.convert("RGBA"), dest, uri, st.st_mtime)
                    return dest

        if ext in VIDEO_EXT:
            out = os.path.join(tmpdir, "video.png")
            proc = subprocess.run(
                ["ffmpegthumbnailer", "-i", path, "-o", out, "-s", str(px),
                 "-t", "10%", "-q", "6"],
                capture_output=True, env=util.clean_env(), timeout=30,
            )
            if proc.returncode != 0 or not os.path.isfile(out):
                proc = subprocess.run(
                    ["ffmpeg", "-y", "-ss", "2", "-i", path, "-frames:v", "1",
                     "-vf", f"scale='min({px},iw)':-1", out],
                    capture_output=True, env=util.clean_env(), timeout=30,
                )
            if proc.returncode == 0 and os.path.isfile(out):
                with Image.open(out) as im:
                    _write_png(_scaled(im.convert("RGBA"), px), dest, uri, st.st_mtime)
                return dest

        if ext in PDF_EXT:
            prefix = os.path.join(tmpdir, "pdf")
            proc = subprocess.run(
                ["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to", str(px),
                 "-png", path, prefix],
                capture_output=True, env=util.clean_env(), timeout=45,
            )
            out = prefix + ".png"
            if proc.returncode == 0 and os.path.isfile(out):
                with Image.open(out) as im:
                    _write_png(im.convert("RGBA"), dest, uri, st.st_mtime)
                return dest
    except Exception:
        return None
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    return None


def clear(size: str | None = None) -> int:
    sizes = [size] if size else list(SIZES)
    n = 0
    for s in sizes:
        d = size_dir(s)
        try:
            for name in os.listdir(d):
                if not name.endswith(".png"):
                    continue
                try:
                    os.unlink(os.path.join(d, name))
                    n += 1
                except OSError:
                    pass
        except OSError:
            pass
    return n


class ThumbPool:
    """Small GObject-friendly wrapper: generate off-thread, deliver a texture."""

    def __init__(self, max_workers: int = 2, max_pending: int = 24):
        import concurrent.futures
        import threading

        self._exec = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._pending = set()
        self._generation = 0
        self.max_pending = max_pending

    def cancel_all(self):
        with self._lock:
            self._generation += 1
            self._pending.clear()

    def request(self, path: str, size: str, callback, mtime=None):
        """callback(path, cache_path_or_None) runs on the main loop."""
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        with self._lock:
            if path in self._pending or len(self._pending) >= self.max_pending:
                return False
            self._pending.add(path)
            gen = self._generation

        def work():
            cache = generate(path, size)
            with self._lock:
                self._pending.discard(path)
                alive = gen == self._generation
            if alive:
                GLib.idle_add(_deliver, path, cache, callback, gen, self)
            return cache

        def _deliver(p, cache, cb, g, pool):
            with pool._lock:
                if g != pool._generation:
                    return False
            try:
                cb(p, cache)
            except Exception:
                pass
            return False

        try:
            self._exec.submit(work)
        except Exception:
            with self._lock:
                self._pending.discard(path)
            return False
        return True

    def shutdown(self):
        self.cancel_all()
        self._exec.shutdown(wait=False, cancel_futures=True)


def texture_from_file(path: str):
    import gi

    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    try:
        return Gdk.Texture.new_from_filename(path)
    except Exception:
        return None
