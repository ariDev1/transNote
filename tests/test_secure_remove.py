import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "lan" / "secure_remove.py"


def run_helper(root, note_id):
    return subprocess.run(
        [sys.executable, str(HELPER), str(root), note_id],
        capture_output=True,
        text=True,
    )


class SecureRemoveTests(unittest.TestCase):
    def setUp(self):
        if not HELPER.exists():
            self.fail("lan/secure_remove.py is missing")

    def test_removes_tree_without_following_nested_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "attachments"
            note = root / "note-safe-1"
            outside = base / "outside"
            note.mkdir(parents=True)
            outside.mkdir()
            (note / "nested").mkdir()
            (note / "nested" / "payload.txt").write_text("inside")
            (outside / "keep.txt").write_text("outside")
            os.symlink(outside, note / "escape")

            result = run_helper(root, "note-safe-1")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(note.exists())
            self.assertEqual((outside / "keep.txt").read_text(), "outside")

    def test_rejects_symlink_as_note_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "attachments"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "keep.txt").write_text("outside")
            os.symlink(outside, root / "note-safe-1")

            result = run_helper(root, "note-safe-1")

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((root / "note-safe-1").is_symlink())
            self.assertEqual((outside / "keep.txt").read_text(), "outside")

    def test_rejects_symlink_as_attachment_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            real_root = base / "real-attachments"
            linked_root = base / "attachments"
            note = real_root / "note-safe-1"
            note.mkdir(parents=True)
            (note / "keep.txt").write_text("inside")
            os.symlink(real_root, linked_root)

            result = run_helper(linked_root, "note-safe-1")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((note / "keep.txt").read_text(), "inside")

    def test_rejects_unsafe_id(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "attachments"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "keep.txt").write_text("outside")

            result = run_helper(root, "../outside")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((outside / "keep.txt").read_text(), "outside")

    def test_missing_note_directory_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "attachments"
            root.mkdir()
            result = run_helper(root, "note-safe-1")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_uses_fd_relative_no_follow_traversal(self):
        source = HELPER.read_text()
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("dir_fd=root_fd", source)
        self.assertIn("dir_fd=dir_fd", source)
        self.assertIn("follow_symlinks=False", source)
        self.assertNotIn("shutil.rmtree", source)
        self.assertNotIn("os.path.realpath", source)


if __name__ == "__main__":
    unittest.main()
