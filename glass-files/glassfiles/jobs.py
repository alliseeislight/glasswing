"""Background jobs with cancellation, speed/ETA and main-loop marshalling."""

from __future__ import annotations

import concurrent.futures
import os
import threading
import time

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from . import util


class Job:
    def __init__(self, title: str, worker, on_done=None, on_update=None):
        self.title = title
        self.worker = worker
        self.on_done = on_done
        self.on_update = on_update
        self.cancel_event = threading.Event()
        self.progress = 0.0
        self.text = ""
        self.speed = 0.0
        self.eta = None
        self.status = "queued"
        self.error = None
        self.result = None
        self.started = 0.0
        self._last_emit = 0.0
        self._start_bytes = 0
        self._start_time = 0.0

    # called from worker threads
    def set_progress(self, fraction: float, text: str = "", speed: float | None = None):
        self.progress = max(0.0, min(1.0, float(fraction)))
        if text:
            self.text = text
        if speed is not None:
            self.speed = speed
            if speed > 1 and self.progress > 0:
                remaining = (1.0 - self.progress) * (self._total_bytes or 0)
                self.eta = remaining / speed if self._total_bytes else None
        now = time.monotonic()
        if now - self._last_emit >= 0.1:
            self._last_emit = now
            self._notify()

    _total_bytes = 0

    def _notify(self):
        if self.on_update:
            GLib.idle_add(self._emit)

    def _emit(self):
        try:
            self.on_update(self)
        except Exception:
            pass
        return False

    def cancel(self):
        self.cancel_event.set()
        self.status = "cancelling"
        self._notify()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()


class JobQueue:
    """Runs at most two jobs at a time; extra jobs wait in order."""

    def __init__(self, on_update, max_workers: int = 2):
        self.on_update = on_update
        self._exec = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: list[Job] = []
        self._lock = threading.Lock()
        self._active = 0
        self._max = max_workers

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    def active_jobs(self) -> list[Job]:
        return [j for j in self.jobs() if j.status in ("queued", "running", "cancelling")]

    def submit(self, title: str, worker, on_done=None) -> Job:
        job = Job(title, worker, on_done=on_done, on_update=self._update)
        with self._lock:
            self._jobs.append(job)
        self._pump()
        return job

    def _update(self, job: Job):
        try:
            self.on_update(job)
        except Exception:
            pass

    def _pump(self):
        with self._lock:
            if self._active >= self._max:
                return
            nxt = next((j for j in self._jobs if j.status == "queued"), None)
            if nxt is None:
                return
            nxt.status = "running"
            self._active += 1
        self._exec.submit(self._run, nxt)

    def _run(self, job: Job):
        job.started = time.monotonic()
        job._notify()
        error = None
        try:
            job.result = job.worker(job)
            if job.cancelled:
                job.status = "cancelled"
            else:
                job.status = "done"
        except Exception as e:
            if job.cancelled or e.__class__.__name__ in ("Cancelled",):
                job.status = "cancelled"
            else:
                job.status = "failed"
                job.error = str(e)
                error = e
        finally:
            with self._lock:
                self._active -= 1
            GLib.idle_add(self._finish, job, error)
            self._pump()

    def _finish(self, job: Job, error):
        try:
            if job.on_done:
                job.on_done(job, error)
            self.on_update(job)
        except Exception:
            pass
        self._prune()
        return False

    def _prune(self):
        with self._lock:
            keep = [j for j in self._jobs if j.status in ("queued", "running", "cancelling")]
            done = [j for j in self._jobs if j not in keep]
            self._jobs = keep + done[-8:]

    def cancel(self, job: Job):
        job.cancel()

    def cancel_all(self):
        for j in self.jobs():
            if j.status in ("queued", "running"):
                j.cancel()

    def shutdown(self):
        self.cancel_all()
        self._exec.shutdown(wait=False, cancel_futures=True)


def copy_progress(job: Job):
    """Build a progress callback for ops.copy_move from a Job."""
    job._start_time = time.monotonic()
    state = {"last_bytes": 0, "last_time": time.monotonic()}

    def cb(copied, total, path):
        job._total_bytes = total
        now = time.monotonic()
        frac = (copied / total) if total else 0.0
        dt = now - state["last_time"]
        if dt >= 0.35:
            speed = (copied - state["last_bytes"]) / dt
            state["last_bytes"] = copied
            state["last_time"] = now
            job.set_progress(frac, util.fsdec(os.path.basename(path)), speed)
        else:
            job.progress = frac
            job.text = util.fsdec(os.path.basename(path))

    return cb
