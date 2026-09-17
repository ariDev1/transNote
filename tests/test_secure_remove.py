import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
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


def run_peer_read_helper(root, max_file_bytes, max_aggregate_bytes, *names):
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "peer-read",
            str(root),
            str(max_file_bytes),
            str(max_aggregate_bytes),
            *names,
        ],
        capture_output=True,
        text=True,
    )


def run_verify_copy_helper(
    source_root,
    note_id,
    file_name,
    declared_size,
    max_size,
    expected_sha,
    trusted_root,
):
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify-copy",
            str(source_root),
            note_id,
            file_name,
            str(declared_size),
            str(max_size),
            expected_sha,
            str(trusted_root),
        ],
        capture_output=True,
        text=True,
    )


def run_copy_helper(source, root, note_id, file_name):
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "copy",
            str(source),
            str(root),
            note_id,
            file_name,
        ],
        capture_output=True,
        text=True,
    )


def run_unlink_helper(root, note_id, file_name):
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "unlink",
            str(root),
            note_id,
            file_name,
        ],
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

    def test_rejects_symlink_in_intermediate_attachment_root_component(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            real_parent = base / "real-parent"
            root = real_parent / "attachments"
            note = root / "note-safe-1"
            note.mkdir(parents=True)
            (note / "keep.txt").write_text("inside")

            linked_parent = base / "linked-parent"
            os.symlink(real_parent, linked_parent)

            result = run_helper(
                linked_parent / "attachments",
                "note-safe-1",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                (note / "keep.txt").read_text(),
                "inside",
            )

    def test_copy_does_not_replace_identical_destination(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source.txt"
            source.write_text("same payload")

            root = base / "sync-attachments"
            note = root / "note-safe-1"
            note.mkdir(parents=True)

            target = note / "att-safe-1-file.txt"
            target.write_text("same payload")
            before = target.stat()

            result = run_copy_helper(
                source,
                root,
                "note-safe-1",
                "att-safe-1-file.txt",
            )

            after = target.stat()

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(after.st_ino, before.st_ino)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
            self.assertEqual(target.read_text(), "same payload")

    def test_peer_read_returns_regular_json_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sync"
            root.mkdir()

            payload = '{"version":2,"notes":[]}\n'
            (root / "peer.json").write_text(payload)

            result = run_peer_read_helper(
                root,
                2097152,
                8388608,
                "peer.json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("===TRANSNOTEPEER:0===", result.stdout)
            self.assertIn(payload.strip(), result.stdout)
            self.assertNotIn("REJECTED:", result.stdout)

    def test_peer_read_enforces_per_file_byte_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sync"
            root.mkdir()

            (root / "peer.json").write_text("1234567890")

            result = run_peer_read_helper(
                root,
                5,
                100,
                "peer.json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("===TRANSNOTEPEER:0===", result.stdout)
            self.assertIn("REJECTED:FILE_BYTES", result.stdout)
            self.assertNotIn("1234567890", result.stdout)

    def test_peer_read_enforces_aggregate_byte_limit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sync"
            root.mkdir()

            (root / "peer-a.json").write_text("AAAAAA")
            (root / "peer-b.json").write_text("BBBBBB")

            result = run_peer_read_helper(
                root,
                100,
                10,
                "peer-a.json",
                "peer-b.json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("===TRANSNOTEPEER:0===", result.stdout)
            self.assertIn("AAAAAA", result.stdout)
            self.assertIn("===TRANSNOTEPEER:1===", result.stdout)
            self.assertIn("REJECTED:AGGREGATE_BYTES", result.stdout)
            self.assertNotIn("BBBBBB", result.stdout)

    def test_peer_read_rejects_symlinked_json_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "sync"
            root.mkdir()

            outside = base / "outside.json"
            outside.write_text('{"notes":[{"id":"outside"}]}')

            os.symlink(outside, root / "peer.json")

            result = run_peer_read_helper(
                root,
                2097152,
                8388608,
                "peer.json",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("===TRANSNOTEPEER:0===", result.stdout)
            self.assertIn("REJECTED:READFAIL", result.stdout)
            self.assertNotIn('"outside"', result.stdout)

    def test_verify_copy_accepts_matching_regular_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            source_root = base / "sync-attachments"
            source_note = source_root / "note-safe-1"
            source_note.mkdir(parents=True)

            file_name = "att-safe-1-file.txt"
            payload = b"verified payload"
            source = source_note / file_name
            source.write_bytes(payload)

            trusted_root = base / "verified-attachments"
            expected_sha = hashlib.sha256(payload).hexdigest()

            result = run_verify_copy_helper(
                source_root,
                "note-safe-1",
                file_name,
                len(payload),
                1024,
                expected_sha,
                trusted_root,
            )

            trusted = trusted_root / "note-safe-1" / file_name

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "VERIFIED")
            self.assertEqual(trusted.read_bytes(), payload)
            self.assertEqual(trusted.stat().st_mode & 0o777, 0o600)

    def test_verify_copy_rejects_actual_size_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            source_root = base / "sync-attachments"
            source_note = source_root / "note-safe-1"
            source_note.mkdir(parents=True)

            file_name = "att-safe-1-file.txt"
            source = source_note / file_name
            source.write_bytes(b"AB")

            trusted_root = base / "verified-attachments"
            expected_sha = hashlib.sha256(b"AB").hexdigest()

            result = run_verify_copy_helper(
                source_root,
                "note-safe-1",
                file_name,
                1,
                1024,
                expected_sha,
                trusted_root,
            )

            trusted = trusted_root / "note-safe-1" / file_name

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "BAD_SIZE")
            self.assertFalse(trusted.exists())

    def test_copies_one_attachment_into_safe_note_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source.txt"
            source.write_text("payload")

            root = base / "sync-attachments"

            result = run_copy_helper(
                source,
                root,
                "note-safe-1",
                "att-safe-1-file.txt",
            )

            target = root / "note-safe-1" / "att-safe-1-file.txt"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(), "payload")

    def test_unlinks_one_attachment_from_safe_note_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "attachments"
            note = root / "note-safe-1"
            note.mkdir(parents=True)
            target = note / "att-safe-1-file.txt"
            target.write_text("inside")

            result = run_unlink_helper(
                root,
                "note-safe-1",
                "att-safe-1-file.txt",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(target.exists())
            self.assertTrue(note.is_dir())

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




class SecureRemoveRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helper_path = Path(
            "lan/secure_remove.py"
        ).resolve()

        spec = importlib.util.spec_from_file_location(
            "transnote_secure_remove_review",
            helper_path,
        )
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)
        cls.helper_path = helper_path

    def make_attachment(self, base, payload=b"trusted payload"):
        source_root = base / "incoming"
        verified_root = base / "verified"

        note_id = "note-review"
        att_id = "att-review"
        name = "sample.txt"
        file_name = f"{att_id}-{name}"

        note_dir = source_root / note_id
        note_dir.mkdir(parents=True)

        source = note_dir / file_name
        source.write_bytes(payload)

        digest = hashlib.sha256(payload).hexdigest()

        return (
            source_root,
            verified_root,
            note_id,
            att_id,
            name,
            file_name,
            payload,
            digest,
        )

    def verify_copy(self, layout, digest=None):
        (
            source_root,
            verified_root,
            note_id,
            _att_id,
            _name,
            file_name,
            payload,
            expected_digest,
        ) = layout

        return self.helper.secure_verify_copy(
            str(source_root),
            note_id,
            file_name,
            len(payload),
            25 * 1024 * 1024,
            digest if digest is not None else expected_digest,
            str(verified_root),
        )

    def test_verify_copy_does_not_rewrite_unchanged_trusted_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            layout = self.make_attachment(base)

            rc = self.verify_copy(layout)
            self.assertEqual(rc, 0)

            (
                _source_root,
                verified_root,
                note_id,
                _att_id,
                _name,
                file_name,
                _payload,
                _digest,
            ) = layout

            trusted = (
                verified_root
                / note_id
                / file_name
            )

            self.assertTrue(trusted.is_file())

            first = trusted.stat()

            time.sleep(0.05)

            rc = self.verify_copy(layout)
            self.assertEqual(rc, 0)

            second = trusted.stat()

            self.assertEqual(
                first.st_ino,
                second.st_ino,
                "unchanged verification replaced the trusted file",
            )
            self.assertEqual(
                first.st_mtime_ns,
                second.st_mtime_ns,
                "unchanged verification rewrote the trusted file",
            )

    def test_bad_hash_creates_no_trusted_cache_payload(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            layout = self.make_attachment(base)

            created = []
            real_open = self.helper.os.open

            def tracked_open(*args, **kwargs):
                flags = (
                    args[1]
                    if len(args) > 1
                    else kwargs.get("flags", 0)
                )

                if flags & os.O_CREAT:
                    created.append(args[0] if args else None)

                return real_open(*args, **kwargs)

            self.helper.os.open = tracked_open

            try:
                self.verify_copy(layout, "0" * 64)
            finally:
                self.helper.os.open = real_open

            self.assertEqual(
                created,
                [],
                "bad-hash input created a trusted-cache payload before "
                "SHA-256 validation completed",
            )

    def test_rejected_peer_json_consumes_aggregate_budget(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            bad = root / "bad.json"
            good = root / "good.json"

            bad.write_bytes(b"\xff" * 8)
            good.write_bytes(b"{}")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.helper_path),
                    "peer-read",
                    str(root),
                    "64",
                    "9",
                    bad.name,
                    good.name,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(
                proc.returncode,
                0,
                proc.stderr,
            )
            self.assertIn(
                "REJECTED:AGGREGATE_BYTES",
                proc.stdout,
                "the rejected 8-byte file did not consume aggregate budget",
            )

    def test_prune_verified_removes_only_stale_cache_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "verified"

            keep_dir = root / "note-keep"
            stale_dir = root / "note-stale"

            keep_dir.mkdir(parents=True)
            stale_dir.mkdir(parents=True)

            keep = keep_dir / "att-keep-file.txt"
            stale_same_note = keep_dir / "att-old-file.txt"
            stale_other_note = stale_dir / "att-old-file.txt"

            keep_payload = b"keep"
            keep.write_bytes(keep_payload)
            stale_same_note.write_bytes(b"stale")
            stale_other_note.write_bytes(b"stale")

            keep_sha = hashlib.sha256(
                keep_payload
            ).hexdigest()

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.helper_path),
                    "prune-verified",
                    str(root),
                    "note-keep",
                    "att-keep-file.txt",
                    str(len(keep_payload)),
                    keep_sha,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(
                proc.returncode,
                0,
                proc.stderr or proc.stdout,
            )
            self.assertTrue(
                keep.is_file(),
                "current trusted attachment was deleted",
            )
            self.assertFalse(
                stale_same_note.exists(),
                "stale attachment in a current note was not removed",
            )
            self.assertFalse(
                stale_other_note.exists(),
                "orphaned peer-note cache directory was not removed",
            )

    def test_prune_verified_rejects_test_only_path_entry_shape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "verified"
            root.mkdir()

            proc = subprocess.run(
                [
                    sys.executable,
                    str(self.helper_path),
                    "prune-verified",
                    str(root),
                    "note-keep/att-keep-file.txt",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(
                proc.returncode,
                2,
                "prune-verified must accept only the runtime metadata "
                "entry shape",
            )

if __name__ == "__main__":
    unittest.main()
