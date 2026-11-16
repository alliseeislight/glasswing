"""Core tests. Everything happens in temp directories; never real files."""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from glassfiles import accent, ops, trash, undo, util


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self._old_home = util.HOME
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        util.HOME = self.home
        os.environ["XDG_DATA_HOME"] = os.path.join(self.home, ".local", "share")

    def tearDown(self):
        util.HOME = self._old_home
        if self._old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg
        self.tmp.cleanup()

    def make(self, rel, content=b"hello"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path


class TestUtil(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(util.human_size(0), "0 B")
        self.assertEqual(util.human_size(999), "999 B")
        self.assertEqual(util.human_size(1000), "1 kB")
        self.assertEqual(util.human_size(1536), "1.5 kB")
        self.assertEqual(util.human_size(None), "--")

    def test_natural_sort(self):
        names = ["file10", "file2", "File1", ".hidden", "apple"]
        got = sorted(names, key=util.entry_key)
        self.assertEqual(got, [".hidden", "apple", "File1", "file2", "file10"])

    def test_expand(self):
        old = util.HOME
        util.HOME = "/home/x"
        try:
            self.assertEqual(util.expand_path("~/a/b"), "/home/x/a/b")
            self.assertEqual(util.expand_path("  \"~/a\"  "), "/home/x/a")
        finally:
            util.HOME = old

    def test_modes(self):
        mode = 0o100644
        self.assertEqual(util.perm_string(mode), "rw-r--r--")
        self.assertEqual(util.octal_mode(mode), "0644")
        self.assertEqual(util.parse_octal("0755"), 0o755)
        self.assertIsNone(util.parse_octal("9x9"))

    def test_uri_roundtrip(self):
        p = "/tmp/a b/ünïcode.txt"
        self.assertEqual(util.uri_to_path(util.path_to_uri(p)), p)

    def test_accent_shape(self):
        rgb = accent.compute()
        self.assertEqual(len(rgb), 3)
        self.assertTrue(all(0 <= v <= 255 for v in rgb))
        self.assertIn("glass_accent", accent.defines(rgb))


class TestTrash(TempCase):
    def test_trash_list_restore(self):
        p = self.make("home/doc.txt", b"precious")
        recs = trash.trash([p])
        self.assertEqual(len(recs), 1)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(trash.trash_count(), 1)
        items = trash.list_trash()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["original"], os.path.abspath(p))
        restored = trash.restore(items)
        self.assertEqual(len(restored), 1)
        self.assertTrue(os.path.exists(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"precious")
        self.assertEqual(trash.trash_count(), 0)

    def test_restore_never_overwrites(self):
        p = self.make("home/doc.txt", b"old")
        trash.trash([p])
        with open(p, "wb") as f:
            f.write(b"new")
        items = trash.list_trash()
        restored = trash.restore(items)
        self.assertTrue(os.path.exists(p))
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"new")
        new_path = restored[0]["restored"]
        self.assertNotEqual(new_path, p)
        with open(new_path, "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_empty_and_purge(self):
        a = self.make("home/a.txt")
        b = self.make("home/b.txt")
        trash.trash([a, b])
        items = trash.list_trash()
        self.assertEqual(len(items), 2)
        trash.purge(items[:1])
        self.assertEqual(trash.trash_count(), 1)
        self.assertEqual(trash.empty(), 1)
        self.assertEqual(trash.trash_count(), 0)

    def test_weird_names(self):
        p = self.make("home/a b (1) [x].txt")
        trash.trash([p])
        items = trash.list_trash()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["original"], os.path.abspath(p))
        self.assertEqual(len(trash.restore(items)), 1)
        self.assertTrue(os.path.exists(p))


class TestOps(TempCase):
    def test_copy_file_conflict_policies(self):
        src = self.make("src/a.txt", b"one")
        dest = os.path.join(self.root, "dst")
        os.makedirs(dest)
        self.make("dst/a.txt", b"two")
        res = ops.copy_move([src], dest, ops.COPY, resolve=lambda *a: ops.SKIP)
        self.assertEqual(res[0]["outcome"], ops.Outcome.SKIPPED)
        with open(os.path.join(dest, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"two")
        res = ops.copy_move([src], dest, ops.COPY, resolve=lambda *a: ops.KEEP_BOTH)
        self.assertEqual(res[0]["outcome"], ops.Outcome.COPIED)
        self.assertTrue(os.path.exists(os.path.join(dest, "a (copy).txt")))
        res = ops.copy_move([src], dest, ops.COPY, resolve=lambda *a: ops.REPLACE)
        self.assertEqual(res[0]["outcome"], ops.Outcome.REPLACED)
        with open(os.path.join(dest, "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"one")

    def test_copy_directory_tree_and_symlink(self):
        os.makedirs(os.path.join(self.root, "src/sub"))
        self.make("src/sub/deep.txt", b"deep")
        os.symlink("sub/deep.txt", os.path.join(self.root, "src/link"))
        dest = os.path.join(self.root, "dst")
        os.makedirs(dest)
        ops.copy_move([os.path.join(self.root, "src")], dest, ops.COPY)
        self.assertTrue(os.path.isfile(os.path.join(dest, "src/sub/deep.txt")))
        self.assertTrue(os.path.islink(os.path.join(dest, "src/link")))

    def test_merge_keeps_existing_files(self):
        os.makedirs(os.path.join(self.root, "src"))
        self.make("src/one.txt", b"1")
        self.make("src/shared.txt", b"new")
        os.makedirs(os.path.join(self.root, "dst/src"))
        self.make("dst/src/two.txt", b"2")
        self.make("dst/src/shared.txt", b"old")
        def res(src, dst, is_dir, dst_is_dir):
            return ops.MERGE if (is_dir and dst_is_dir) else ops.SKIP

        res = ops.copy_move([os.path.join(self.root, "src")], os.path.join(self.root, "dst"),
                            ops.COPY, resolve=res)
        self.assertEqual(res[0]["outcome"], ops.Outcome.MERGED)
        self.assertTrue(os.path.exists(os.path.join(self.root, "dst/src/one.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "dst/src/two.txt")))
        with open(os.path.join(self.root, "dst/src/shared.txt"), "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_move_is_atomic_and_complete(self):
        src = self.make("src/move.txt", b"data")
        dest = os.path.join(self.root, "dst")
        os.makedirs(dest)
        res = ops.copy_move([src], dest, ops.MOVE)
        self.assertEqual(res[0]["outcome"], ops.Outcome.MOVED)
        self.assertFalse(os.path.exists(src))
        with open(os.path.join(dest, "move.txt"), "rb") as f:
            self.assertEqual(f.read(), b"data")

    def test_move_into_same_folder_is_skipped(self):
        src = self.make("src/a.txt")
        res = ops.copy_move([src], os.path.dirname(src), ops.MOVE)
        self.assertEqual(res[0]["outcome"], ops.Outcome.SKIPPED)
        self.assertTrue(os.path.exists(src))

    def test_rename_and_duplicate(self):
        p = self.make("src/a.txt", b"x")
        new = ops.rename(p, "b.txt")
        self.assertTrue(os.path.exists(new))
        dup = ops.duplicate(new)
        self.assertEqual(os.path.basename(dup), "b (copy).txt")

    def test_delete(self):
        p = self.make("src/a.txt")
        os.makedirs(os.path.join(self.root, "src/dir"))
        ops.delete([p, os.path.join(self.root, "src/dir")])
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(os.path.join(self.root, "src/dir")))

    def test_archive_roundtrip(self):
        src = self.make("src/dir/a.txt", b"archived")
        for fmt in ("zip", "tar.gz"):
            out = os.path.join(self.root, f"out-{fmt.replace('.', '-')}")
            os.makedirs(out)
            archive = ops.compress([os.path.join(self.root, "src/dir")], os.path.join(out, "pack"), fmt)
            self.assertTrue(os.path.isfile(archive), archive)
            listed = ops.list_archive(archive)
            self.assertTrue(any("a.txt" in n for n in listed))
            target = os.path.join(self.root, "x-" + fmt.replace(".", "-"))
            os.makedirs(target)
            ops.extract(archive, target, into_folder=False)
            self.assertTrue(os.path.isfile(os.path.join(target, "dir/a.txt")))

    def test_extract_refuses_traversal(self):
        import subprocess
        bad = os.path.join(self.root, "bad.zip")
        src = os.path.join(self.root, "evil")
        os.makedirs(src)
        with open(os.path.join(src, "x.txt"), "w") as f:
            f.write("x")
        subprocess.run(["bsdtar", "-a", "-cf", bad, "-C", src, "x.txt"], check=True)
        # A well-formed zip is fine; we only assert the guard function itself.
        self.assertFalse(ops._unsafe_member("a/b.txt"))
        self.assertTrue(ops._unsafe_member("../escape.txt"))
        self.assertTrue(ops._unsafe_member("/abs.txt"))

    def test_checksum(self):
        p = self.make("src/a.txt", b"abc")
        self.assertEqual(ops.checksum(p, "sha256"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_cancel_aborts_copy(self):
        import threading
        big = self.make("src/big.bin", b"x" * 3_000_000)
        dest = os.path.join(self.root, "dst")
        os.makedirs(dest)
        ev = threading.Event()
        ev.set()
        with self.assertRaises(ops.Cancelled):
            ops.copy_move([big], dest, ops.COPY, cancel=ev)
        self.assertFalse(os.path.exists(os.path.join(dest, "big.bin")))


class TestUndo(TempCase):
    def test_rename_undo_redo(self):
        p = self.make("src/a.txt")
        new = ops.rename(p, "b.txt")
        stack = undo.UndoStack()
        stack.push(undo.RenameAction([(p, new)]))
        stack.undo()
        self.assertTrue(os.path.exists(p))
        stack.redo()
        self.assertTrue(os.path.exists(new))

    def test_trash_undo(self):
        p = self.make("home/a.txt", b"keep")
        recs = trash.trash([p])
        stack = undo.UndoStack()
        stack.push(undo.TrashAction(recs))
        stack.undo()
        self.assertTrue(os.path.exists(p))
        stack.redo()
        self.assertFalse(os.path.exists(p))

    def test_move_undo(self):
        src = self.make("home/a.txt", b"data")
        dest = os.path.join(self.root, "other")
        os.makedirs(dest)
        res = ops.copy_move([src], dest, ops.MOVE)
        stack = undo.UndoStack()
        stack.push(undo.MoveAction(res))
        stack.undo()
        self.assertTrue(os.path.exists(src))
        stack.redo()
        self.assertTrue(os.path.exists(os.path.join(dest, "a.txt")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
