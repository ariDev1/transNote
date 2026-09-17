import json
import re
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

    def test_unshare_uses_descriptor_helper_for_synced_attachments(self):
        start = self.panel.index("  function toggleShare(id) {")
        end = self.panel.index("\n  function touchLocalNotes()", start)
        body = self.panel[start:end]

        self.assertIn(
            "queueSafeRemove(syncAttachDir(), id)",
            body,
        )
        self.assertNotIn("rm -rf", body)

    def test_remove_attachment_uses_descriptor_safe_unlink(self):
        start = self.panel.index("  function removeAttachment(noteId, attId) {")
        end = self.panel.index(
            "\n  // Re-verify every peer attachment:",
            start,
        )
        body = self.panel[start:end]

        self.assertIn(
            "queueSafeUnlink(localAttachDir, noteId,",
            body,
        )
        self.assertIn(
            "queueSafeUnlink(syncAttachDir(), noteId,",
            body,
        )
        self.assertNotIn("rm -f", body)

    def test_shared_attachment_mirror_uses_descriptor_safe_copy(self):
        start = self.panel.index("  function mirrorSharedAttachments() {")
        end = self.panel.index("\n  function persist() {", start)
        body = self.panel[start:end]

        self.assertIn("queueSafeCopy(", body)
        self.assertNotIn("cp --", body)
        self.assertNotIn("mkdir -p", body)
        self.assertNotIn("chmod 600", body)

    def test_peer_attachment_verification_uses_descriptor_safe_verify_copy(self):
        start = self.panel.index("  function refreshAttachmentStates() {")
        end = self.panel.index("\n  function applyVerifyOutput(output) {", start)
        body = self.panel[start:end]

        self.assertIn('"verify-copy"', body)
        self.assertIn("secureRemoveHelper", body)
        self.assertIn("Store.MAX_ATTACHMENT_BYTES", body)

        self.assertNotIn("sha256sum", body)
        self.assertNotIn("test -f", body)

    def test_changed_peer_snapshot_invalidates_verified_attachment_state(self):
        start = self.panel.index("  function applyPeerFetch(output) {")
        end = self.panel.index(
            "\n  Process {\n    id: peerFetchProcess",
            start,
        )
        body = self.panel[start:end]

        self.assertIn(
            "var snapshotsChanged = JSON.stringify(next) !== JSON.stringify(peerSnapshots)",
            body,
        )
        self.assertIn("if (snapshotsChanged) {", body)
        self.assertIn("peerSnapshots = next", body)
        self.assertIn("verifiedAtts = ({})", body)

    def test_peer_attachment_reads_use_verified_local_copy(self):
        start = self.panel.index("  function attPathFor(note, att) {")
        end = self.panel.index("\n  function attUrl(path) {", start)
        body = self.panel[start:end]

        self.assertIn("ownAttachSubdir(note.id)", body)
        self.assertIn("verifiedAttachDir", body)
        self.assertIn("verifiedAtts[key]", body)
        self.assertNotIn("syncAttachSubdir(note.id)", body)

    def test_empty_attachment_path_does_not_create_file_url(self):
        start = self.panel.index("  function attUrl(path) {")
        end = self.panel.index("\n  function formatSize(b) {", start)
        body = self.panel[start:end]

        self.assertIn('if (p === "") return ""', body)

    def test_remove_attach_dirs_rejects_unsafe_id_before_deletion(self):
        self.assertIn("if (!Store.isSafeId(noteId)) return", self.panel)

    def test_gc_queue_preserves_argv_commands(self):
        self.assertIn("gcProcess.command = q[0]", self.panel)
        self.assertIn("pendingGc = q.slice(1)", self.panel)
        self.assertNotIn("var scripts = q.map(function (c)", self.panel)

    def test_peer_tombstones_do_not_enter_global_deleted_state(self):
        start = self.panel.index("  function rebuildPeerNotes() {")
        body = self.panel[start:]

        self.assertNotIn(
            "Store.mergeDeleted(deletedIds, peerTomb)",
            body,
        )
        self.assertNotIn(
            "deletedIds = effective",
            body,
        )
        self.assertNotIn(
            "pendingDeletes = Object.keys(effective)",
            body,
        )

    def test_normal_setup_applies_pairing_safe_device_id_grammar(self):
        self.assertIn("function isSafeDeviceId(value)", self.panel)

        my_id_start = self.panel.index("  readonly property string myId:")
        my_id_end = self.panel.index("\n  readonly property var allowList:", my_id_start)
        my_id_body = self.panel[my_id_start:my_id_end]

        self.assertIn("isSafeDeviceId(s)", my_id_body)
        self.assertIn("isSafeDeviceId(detected)", my_id_body)

        save_start = self.panel.index("  function saveSetupDevice() {")
        save_end = self.panel.index("\n  function saveSetupDir()", save_start)
        save_body = self.panel[save_start:save_end]

        self.assertIn("isSafeDeviceId(v)", save_body)

    def test_peer_limits_are_explicit_and_bounded(self):
        self.assertIn("readonly property int maxPeerFiles: 32", self.panel)
        self.assertIn("readonly property int maxPeerFileBytes: 2097152", self.panel)
        self.assertIn("readonly property int maxPeerAggregateBytes: 8388608", self.panel)

    def test_peer_list_overflow_is_rejected(self):
        self.assertIn("===TRANSNOTE_PEER_LIST_OVERFLOW===", self.panel)
        self.assertIn("peer scan rejected: too many JSON files", self.panel)


    def test_peer_fetch_uses_descriptor_safe_reader(self):
        start = self.panel.index("  function fetchPeerSnapshots() {")
        end = self.panel.index("\n  function applyPeerFetch(output) {", start)
        body = self.panel[start:end]

        self.assertIn('"peer-read"', body)
        self.assertIn("secureRemoveHelper", body)
        self.assertIn("maxPeerFileBytes", body)
        self.assertIn("maxPeerAggregateBytes", body)

        self.assertNotIn("/usr/bin/stat -Lc%s", body)
        self.assertNotIn('/usr/bin/head -c "$size"', body)

    def test_rejected_peer_chunks_are_not_parsed(self):
        self.assertIn('c.trim().indexOf("REJECTED:") === 0', self.panel)




class LanHardeningRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("Panel.qml").read_text(
            encoding="utf-8"
        )

    def function_block(self, name):
        start = self.source.find(f"  function {name}(")
        self.assertGreaterEqual(
            start,
            0,
            f"Panel.qml has no function {name}()",
        )

        end = self.source.find("\n  function ", start + 1)
        if end < 0:
            end = len(self.source)

        return self.source[start:end]

    def test_rebuild_peer_notes_has_no_stale_effective_identifier(self):
        block = self.function_block("rebuildPeerNotes")

        self.assertIsNone(
            re.search(r"\beffective\b", block),
            "rebuildPeerNotes() still references removed 'effective' state",
        )

    def test_attachment_authorization_is_bound_to_current_metadata(self):
        signature = self.function_block("attachmentSignature")

        self.assertRegex(signature, r"\batt\.name\b")
        self.assertRegex(signature, r"\batt\.size\b")
        self.assertRegex(signature, r"\batt\.sha256\b")

        path_block = self.function_block("attPathFor")

        self.assertIn(
            "attachmentSignature(att)",
            path_block,
            "attPathFor() must calculate the current metadata signature",
        )
        self.assertIn(
            "verifyJobs[key]",
            path_block,
            "trusted-path authorization must remain bound to the verified job",
        )
        self.assertIn(
            '"ok"',
            path_block,
            "trusted-path authorization must still require successful verification",
        )

    def test_old_verification_result_cannot_authorize_new_metadata(self):
        self.assertIn(
            "function currentPeerAttachmentSignature(key)",
            self.source,
            "Panel.qml needs a deterministic lookup of current peer metadata",
        )

        block = self.function_block("applyVerifyOutput")

        self.assertIn(
            "currentPeerAttachmentSignature(idx)",
            block,
            "verification completion must compare against current metadata",
        )
        self.assertIn(
            "var current = currentPeerAttachmentSignature(idx)",
            block,
            "applyVerifyOutput() must resolve the current peer metadata "
            "signature",
        )
        self.assertIn(
            "current !== exp[idx]",
            block,
            "applyVerifyOutput() must reject a completed job whose metadata "
            "signature is no longer current",
        )

    def test_verified_cache_cleanup_runs_when_peer_snapshots_disappear(self):
        block = self.function_block("fetchPeerSnapshots")

        self.assertIn(
            "refreshAttachmentStates()",
            block,
            "fetchPeerSnapshots() must refresh attachment state when peer "
            "snapshots disappear so stale verified-cache files are pruned",
        )

    def test_dead_mirror_process_is_removed(self):
        self.assertNotIn(
            "id: mirrorProcess",
            self.source,
            "dead mirrorProcess Process object is still present",
        )
        self.assertNotIn(
            "mirrorProcess.",
            self.source,
            "mirrorProcess still has a live reference",
        )

if __name__ == "__main__":
    unittest.main()
