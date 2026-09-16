import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "Store.js"
PANEL = ROOT / "Panel.qml"


def run_store(expression):
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("Node.js is required for Store.js security tests")
    script = (
        "const Store = require(" + json.dumps(str(STORE)) + ");"
        "const result = (" + expression + ");"
        "process.stdout.write(JSON.stringify(result));"
    )
    completed = subprocess.run(
        [node, "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class LanIdSecurityTests(unittest.TestCase):
    def test_received_note_ids_reject_path_syntax(self):
        bad_ids = ["../outside", "..", ".", "a/b", r"a\b", "note.good"]
        for bad_id in bad_ids:
            raw = json.dumps(
                {
                    "id": bad_id,
                    "title": "peer",
                    "body": "x",
                    "author": "peer",
                    "shared": True,
                }
            )
            with self.subTest(note_id=bad_id):
                self.assertIsNone(run_store("Store.sanitizeNote(" + raw + ")"))

    def test_received_attachment_ids_reject_path_syntax(self):
        bad_ids = ["../outside", "..", ".", "a/b", r"a\b", "att.good"]
        for bad_id in bad_ids:
            raw = json.dumps(
                {
                    "id": bad_id,
                    "name": "safe.txt",
                    "size": 1,
                    "sha256": "a" * 64,
                }
            )
            with self.subTest(attachment_id=bad_id):
                self.assertIsNone(run_store("Store.sanitizeAttachment(" + raw + ")"))

    def test_generated_id_shape_remains_valid(self):
        sha = "a" * 64
        result = run_store(
            "({"
            "note: Store.sanitizeNote({id:'note-abc-123', title:'x'}),"
            "att: Store.sanitizeAttachment({id:'att-abc-123', name:'x.txt', size:1, sha256:'"
            + sha
            + "'})"
            "})"
        )
        self.assertEqual(result["note"]["id"], "note-abc-123")
        self.assertEqual(result["att"]["id"], "att-abc-123")

    def test_outbox_and_tombstones_reject_unsafe_note_ids(self):
        outbox = run_store(
            "Store.sanitizeOutbox([{noteId:'../outside', "
            "comment:{id:'c-safe-1', author:'peer', text:'x'}}])"
        )
        tomb = run_store(
            "Store.sanitizeDeleted({'../outside':'2026-09-16T00:00:00.000Z', "
            "'note-safe-1':'2026-09-16T00:00:00.000Z'})"
        )
        self.assertEqual(outbox, [])
        self.assertNotIn("../outside", tomb)
        self.assertIn("note-safe-1", tomb)

    def test_local_attachment_constructor_rejects_unsafe_explicit_id(self):
        sha = "a" * 64
        result = run_store(
            "Store.createAttachment('x.txt', 1, '" + sha + "', '../outside')"
        )
        self.assertIsNone(result)


class PanelSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()
        # QML JavaScript double-quoted strings escape embedded shell quotes.
        # Normalize only this representation detail for static assertions.
        cls.shell_view = cls.panel.replace(r'\"', '"')

    def test_recursive_deletion_uses_descriptor_helper(self):
        self.assertIn(
            'readonly property string secureRemoveHelper: pluginDir + "/lan/secure_remove.py"',
            self.panel,
        )
        self.assertIn("function queueSafeRemove(rootDir, noteId)", self.panel)
        self.assertIn(
            'queueGc([envBin, "-i", "/usr/bin/python3", secureRemoveHelper, rootDir, noteId])',
            self.panel,
        )
        self.assertNotIn("/usr/bin/realpath -m --", self.panel)
        self.assertNotIn('/usr/bin/rm -rf -- "$target"', self.shell_view)

    def test_remove_attach_dirs_rejects_unsafe_id_before_deletion(self):
        self.assertIn("if (!Store.isSafeId(noteId)) return", self.panel)

    def test_gc_queue_preserves_argv_commands(self):
        self.assertIn("gcProcess.command = q[0]", self.panel)
        self.assertIn("pendingGc = q.slice(1)", self.panel)
        self.assertNotIn("var scripts = q.map(function (c)", self.panel)

    def test_peer_limits_are_explicit_and_bounded(self):
        self.assertIn("readonly property int maxPeerFiles: 32", self.panel)
        self.assertIn("readonly property int maxPeerFileBytes: 2097152", self.panel)
        self.assertIn("readonly property int maxPeerAggregateBytes: 8388608", self.panel)

    def test_peer_list_overflow_is_rejected(self):
        self.assertIn("===TRANSNOTE_PEER_LIST_OVERFLOW===", self.panel)
        self.assertIn("peer scan rejected: too many JSON files", self.panel)

    def test_peer_bytes_are_bounded_before_stdout(self):
        stat_pos = self.shell_view.find("/usr/bin/stat -Lc%s")
        per_file_pos = self.shell_view.find('if [ "$size" -gt " + maxPeerFileBytes')
        aggregate_pos = self.shell_view.find(
            'if [ $((total + size)) -gt " + maxPeerAggregateBytes'
        )
        head_pos = self.shell_view.find('/usr/bin/head -c "$size" -- "$p"')
        self.assertGreaterEqual(stat_pos, 0)
        self.assertGreaterEqual(per_file_pos, 0)
        self.assertGreaterEqual(aggregate_pos, 0)
        self.assertGreaterEqual(head_pos, 0)
        self.assertLess(stat_pos, head_pos)
        self.assertLess(per_file_pos, head_pos)
        self.assertLess(aggregate_pos, head_pos)
        self.assertIn("REJECTED:FILE_BYTES", self.panel)
        self.assertIn("REJECTED:AGGREGATE_BYTES", self.panel)

    def test_rejected_peer_chunks_are_not_parsed(self):
        self.assertIn('c.trim().indexOf("REJECTED:") === 0', self.panel)


if __name__ == "__main__":
    unittest.main()
