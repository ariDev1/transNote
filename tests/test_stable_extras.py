"""Stability extras on top of upstream delete-everywhere (0.5.5).

Covers what the extras add: local-only Hide for peer notes, device-rename
migration, unshare tombstones, the sidecar-cleanup queue, the
load-failure guard, and the image-loader fix.
"""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "Store.js"
PANEL = ROOT / "Panel.qml"


def node_eval(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class HiddenStoreTests(unittest.TestCase):
    def test_sanitize_hidden_dedups_and_ignores_junk(self):
        out = node_eval(
            "const S = require('./Store.js');"
            "console.log(JSON.stringify(S.sanitizeHidden(['a','b','a','',null])))")
        self.assertEqual(out, ["a", "b"])

    def test_sanitize_hidden_accepts_id_objects(self):
        out = node_eval(
            "const S = require('./Store.js');"
            "console.log(JSON.stringify(S.sanitizeHidden([{id:'x'},{id:'x'},{noid:1}])))")
        self.assertEqual(out, ["x"])


class HiddenWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()

    def test_hidden_state_and_actions_exist(self):
        for token in (
            "property var hiddenIds: []",
            "function hideNote(id)",
            "function unhideAll()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

    def test_hide_is_local_only_and_never_deletes(self):
        # hideNote must refuse local notes (they have Delete) and must not
        # touch tombstones — hiding publishes nothing.
        self.assertIn("if (nid === \"\" || isLocalNote(nid)) return", self.panel)

    def test_display_filters_hidden(self):
        self.assertIn("!hidden[n.id]", self.panel)

    def test_hidden_persisted_and_loaded(self):
        self.assertIn("hidden: Store.sanitizeHidden(hiddenIds)", self.panel)
        self.assertIn("sanitizeHidden(parsed && parsed.hidden)", self.panel)

    def test_delete_clears_hide_entry(self):
        self.assertIn("drop any local hide entry", self.panel)

    def test_unhide_banner_exists(self):
        self.assertIn("Unhide all", self.panel)

    def test_cursor_delete_falls_back_to_hide(self):
        self.assertIn("else hideNote(n.id)", self.panel)


class RenameMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()

    def test_migration_resigns_on_load_and_on_rename(self):
        self.assertIn("function migrateAuthors()", self.panel)
        self.assertIn("onMyIdChanged: root.migrateAuthors()", self.panel)

    def test_share_and_tint_dont_depend_on_author_string(self):
        self.assertIn("visible: root.isLocalNote(note.id)", self.panel)
        self.assertIn("function setLocalShareState(id, shared)", self.panel)
        self.assertIn("Store.setShared(localNotes[i], wantShared, \"\")", self.panel)
        self.assertIn(
            "setLocalShareState(clean, !(localNotes[i].shared === true))",
            self.panel,
        )

    def test_stale_snapshot_removed_after_rename(self):
        self.assertIn("property string lastSnapshotId", self.panel)
        self.assertIn("rm -f \" + shellQuote(syncDir + \"/\" + lastSnapshotId + \".json\")", self.panel)


class UnshareTombstoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()

    def function_block(self, name, next_name):
        start = self.panel.index(f"  function {name}(")
        end = self.panel.index(f"\n  function {next_name}(", start)
        return self.panel[start:end]

    def test_unshare_tombstones_and_reshare_clears(self):
        self.assertIn("tombstones the note so peers drop their copy", self.panel)
        self.assertIn("Re-sharing clears the tombstone", self.panel)
        self.assertIn("pendingDeletes.indexOf(clean) === -1", self.panel)

    def test_common_share_transition_is_idempotent(self):
        body = self.function_block("setLocalShareState", "toggleShare")

        self.assertIn(
            "if (localNotes[i].shared === wantShared) return true",
            body,
        )
        self.assertIn(
            'Store.setShared(localNotes[i], wantShared, "")',
            body,
        )
        self.assertIn("persist()", body)

    def test_toggle_share_uses_common_share_transition(self):
        body = self.function_block("toggleShare", "touchLocalNotes")

        self.assertIn(
            "setLocalShareState(clean, !(localNotes[i].shared === true))",
            body,
        )
        self.assertNotIn("Store.setShared", body)

    def test_unshare_tombstone_filters_remote_notes_not_local_display(self):
        body = self.function_block("refreshDisplay", "allPeerNotes")

        self.assertIn(
            "Store.filterDeletedNotes((peerNotes || []).concat(nostrPeerNotes || []), deletedIds)",
            body,
        )
        self.assertIn(
            "var union = (localNotes || []).concat(remote)",
            body,
        )
        self.assertNotIn(
            "Store.filterDeletedNotes(union, deletedIds)",
            body,
        )

    def test_reload_keeps_local_note_when_unshare_tombstone_exists(self):
        body = self.function_block("loadLocal", "migrateAuthors")

        self.assertIn("localNotes = notes", body)
        self.assertNotIn(
            "localNotes = Store.filterDeletedNotes(notes, tomb)",
            body,
        )

    def test_real_delete_still_removes_local_note_and_adds_tombstone(self):
        body = self.function_block("deleteNote", "hideNote")

        self.assertIn(
            "localNotes = localNotes.filter(function (n) { return n && n.id !== clean })",
            body,
        )
        self.assertIn(
            "deletedIds = Store.addTombstone(deletedIds, clean)",
            body,
        )

    def test_peer_notes_still_obey_local_tombstones(self):
        body = self.function_block("rebuildPeerNotes", "loadNostrFetch")

        self.assertIn(
            "all = Store.filterDeletedNotes(all, deletedIds)",
            body,
        )

    def test_lan_snapshot_still_retracts_unshared_note(self):
        body = self.function_block("writeSnapshot", "mirrorSharedAttachments")

        self.assertIn(
            "var shared = localNotes.filter(function (n) { return n && n.shared === true })",
            body,
        )

    def test_nostr_deletions_persist_without_entering_publish_queue(self):
        fetch = self.function_block("loadNostrFetch", "refilterNostr")
        persist = self.function_block("persist", "loadLocal")
        load = self.function_block("loadLocal", "migrateAuthors")
        out = node_eval("""
const Store = require('./Store.js');
const Agent = {sanitizeProvenance: x => x || {}};
const alice = 'a'.repeat(64), bob = 'b'.repeat(64);
const root = {myHex: 'c'.repeat(64), nostrFetchRaw: ''};
const nostrAllowList = [alice, bob], allowList = [alice, bob], myId = 'local';
let deletedIds = {}, nostrDeleted = [], pendingDeletes = [], localNotes = [], peerNotes = [];
let nostrPeerNotes = [], foreignComments = {}, nostrComments = {}, outbox = [], hiddenIds = [], agentProvenance = {};
let localLoadFailed = false, lastLocalRaw = '', localLoaded = false;
const setupIdentityReady = false;
const localFile = {setText: text => {localFile.text = text}};
const notesBakFile = {setText: () => {}};
const nostrPublishFile = {setText: text => {nostrPublishFile.text = text}};
const writeSnapshot = () => {}, refreshDisplay = () => {}, secureFiles = () => {}, mergePeers = () => {}, refilterNostr = () => {};
const allPeerNotes = () => peerNotes.concat(nostrPeerNotes);
""" + fetch + persist + load + """
const note = {id: 'victim', title: 'keep', authorHex: alice};
loadNostrFetch(JSON.stringify({notes: [note], deleted: [{noteId: 'victim', author: bob}]}));
const unauthorizedKept = nostrPeerNotes.length;
loadNostrFetch(JSON.stringify({notes: [note], deleted: [{noteId: 'victim', author: alice}]}));
const saved = localFile.text;
const queued = JSON.parse(nostrPublishFile.text).deletes.length;
nostrDeleted = []; deletedIds = {}; pendingDeletes = [];
loadLocal(saved);
loadNostrFetch(JSON.stringify({notes: [note]}));
console.log(JSON.stringify({unauthorizedKept, keptAfterReload: nostrPeerNotes.length,
  global: Object.keys(deletedIds).length, queued, pending: pendingDeletes.length,
  savedAuthors: JSON.parse(saved).nostrDeleted.map(d => d.author).sort()}));
""")
        self.assertEqual(out['unauthorizedKept'], 1)
        self.assertEqual(out['keptAfterReload'], 0)
        self.assertEqual(out['global'], 0)
        self.assertEqual(out['queued'], 0)
        self.assertEqual(out['pending'], 0)
        self.assertEqual(out['savedAuthors'], ['a' * 64, 'b' * 64])


class CleanupAndGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()

    def test_gc_queue_exists_and_flushes(self):
        for token in (
            "property var pendingGc: []",
            "function queueGc(cmd)",
            "function flushGc()",
            "onExited: root.flushGc()",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

    def test_no_direct_gc_overwrite_remains(self):
        # Only flushGc (the queue drain) may assign gcProcess.command:
        # attach/note cleanup must go through queueGc. The queue now drains
        # one argv command at a time, so there is one assignment site.
        self.assertEqual(self.panel.count("gcProcess.command"), 1)
        self.assertEqual(self.panel.count("queueGc(["), 5)

    def test_load_failure_keeps_memory(self):
        self.assertIn("property bool localLoadFailed: false", self.panel)
        self.assertIn("root.localLoadFailed = true", self.panel)
        self.assertIn("if (!localLoadFailed)", self.panel)

    def test_image_source_restricted_to_images(self):
        self.assertIn("att.kind === \"image\" ? root.attUrl(attPath) : \"\"", self.panel)


if __name__ == "__main__":
    unittest.main()
