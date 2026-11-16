"""Undo/redo for filesystem actions. No GTK imports."""

from __future__ import annotations

import os

from . import ops, thumbs, trash, util


class UndoAction:
    label = "Action"

    def undo(self):
        raise NotImplementedError

    def redo(self):
        raise NotImplementedError


class CreateAction(UndoAction):
    label = "Create"

    def __init__(self, paths, label="Create"):
        self.paths = list(paths)
        self.label = label

    def undo(self):
        # Created things go to the trash, not the void: undo should also be undoable.
        return trash.trash([p for p in self.paths if os.path.lexists(p)])

    def redo(self):
        return []


class RenameAction(UndoAction):
    label = "Rename"

    def __init__(self, pairs):
        # pairs: [(old_path, new_path), ...]
        self.pairs = list(pairs)

    def _apply(self, src, dst):
        try:
            os.rename(src, dst)
            return True
        except OSError:
            return False

    def undo(self):
        return [self._apply(new, old) for old, new in self.pairs]

    def redo(self):
        return [self._apply(old, new) for old, new in self.pairs]


class RotateAction(UndoAction):
    def __init__(self, paths, degrees):
        self.paths = list(paths)
        self.degrees = int(degrees)
        n = len(self.paths)
        self.label = f"Rotate {n} image{'s' if n != 1 else ''}"

    def _apply(self, degrees):
        out = []
        for path in self.paths:
            if not os.path.isfile(path):
                out.append(False)
                continue
            try:
                ops.rotate_image(path, degrees)
                thumbs.forget(path)
                out.append(True)
            except Exception:
                out.append(False)
        return out

    def undo(self):
        return self._apply(-self.degrees)

    def redo(self):
        return self._apply(self.degrees)


class MoveAction(UndoAction):
    def __init__(self, results, label="Move"):
        self.label = label
        self.moves = [(r["src"], r["dest"]) for r in results
                      if r.get("dest") and r.get("outcome") in (ops.Outcome.MOVED, ops.Outcome.COPIED,
                                                                ops.Outcome.REPLACED, ops.Outcome.MERGED)]
        self.results = list(results)

    def undo(self):
        out = []
        for src, dst in reversed(self.moves):
            if not os.path.lexists(dst):
                out.append(False)
                continue
            try:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                if os.path.lexists(src):
                    src = util.unique_path(os.path.dirname(src), os.path.basename(src), " (undone)")
                os.rename(dst, src)
                out.append(True)
            except OSError:
                out.append(False)
        return out

    def redo(self):
        out = []
        for src, dst in self.moves:
            if not os.path.lexists(src):
                out.append(False)
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.lexists(dst):
                    dst = util.unique_path(os.path.dirname(dst), os.path.basename(dst), " (redone)")
                os.rename(src, dst)
                out.append(True)
            except OSError:
                out.append(False)
        return out


class CopyAction(UndoAction):
    label = "Copy"

    def __init__(self, results):
        self.dests = [r["dest"] for r in results if r.get("dest") and r.get("outcome")
                      in (ops.Outcome.COPIED, ops.Outcome.MERGED)]

    def undo(self):
        return trash.trash([p for p in self.dests if os.path.lexists(p)])

    def redo(self):
        return []


class TrashAction(UndoAction):
    label = "Move to Trash"

    def __init__(self, records):
        self.records = list(records)

    def undo(self):
        return trash.restore(self.records)

    def redo(self):
        return trash.trash([r["original"] for r in self.records if os.path.lexists(r["original"])])


class UndoStack:
    def __init__(self, limit: int = 100, on_change=None):
        self._undo: list[UndoAction] = []
        self._redo: list[UndoAction] = []
        self.limit = limit
        self.on_change = on_change

    def _changed(self):
        if self.on_change:
            self.on_change()

    def push(self, action: UndoAction):
        if action is None:
            return
        self._undo.append(action)
        del self._undo[: max(0, len(self._undo) - self.limit)]
        self._redo.clear()
        self._changed()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def peek_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    def undo(self):
        if not self._undo:
            return None
        action = self._undo.pop()
        try:
            action.undo()
        except Exception:
            pass
        self._redo.append(action)
        self._changed()
        return action

    def redo(self):
        if not self._redo:
            return None
        action = self._redo.pop()
        try:
            action.redo()
        except Exception:
            pass
        self._undo.append(action)
        self._changed()
        return action

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self._changed()
