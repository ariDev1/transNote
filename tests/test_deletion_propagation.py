import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "Store.js"


def node_eval(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class DeletionPropagationTests(unittest.TestCase):
    def test_tombstone_suppresses_nostr_resurrection(self):
        out = node_eval(
            """
const S = require('./Store.js');
const author = 'a'.repeat(64);
const me = 'b'.repeat(64);
const raw = JSON.stringify({notes: [{id: 'note-1', title: 't', body: 'b', authorHex: author, updatedAt: '2026-09-14T00:00:00.000Z'}], pairs: [], deleted: []});
const before = S.sanitizeNostrFetch(raw, [author], me, {});
const after = S.sanitizeNostrFetch(raw, [author], me, {'note-1': '2026-09-14T01:00:00.000Z'});
console.log(JSON.stringify({before: before.notes.length, after: after.notes.length}));
"""
        )
        self.assertEqual(out["before"], 1)
        self.assertEqual(out["after"], 0)

    def test_relay_kind5_tombstone_filters_note(self):
        out = node_eval(
            """
const S = require('./Store.js');
const author = 'a'.repeat(64);
const me = 'b'.repeat(64);
const raw = JSON.stringify({
  notes: [{id: 'note-2', title: 't', body: 'b', authorHex: author, updatedAt: '2026-09-14T00:00:00.000Z'}],
  pairs: [{noteId: 'note-2', comment: {id: 'c-1', author, text: 'hi', createdAt: '2026-09-14T00:00:00.000Z'}}],
  deleted: [{noteId: 'note-2', author}]
});
const f = S.sanitizeNostrFetch(raw, [author], me, {});
console.log(JSON.stringify({notes: f.notes.length, pairs: f.pairs.length, deleted: f.deleted.length}));
"""
        )
        self.assertEqual(out["notes"], 0)
        self.assertEqual(out["pairs"], 0)
        self.assertEqual(out["deleted"], 1)

    def test_publish_queues_deletes(self):
        out = node_eval(
            """
const S = require('./Store.js');
const note = {id: 'note-3', title: 't', body: 'b', author: 'me', createdAt: '2026-09-14T00:00:00.000Z', updatedAt: '2026-09-14T00:00:00.000Z', shared: true, comments: [], attachments: [], color: ''};
const job = S.buildNostrPublish([note], [], {});
const job2 = S.buildNostrPublish([], [], {'note-3': '2026-09-14T01:00:00.000Z'});
console.log(JSON.stringify({notes: job.notes.length, deletesEmpty: job.deletes.length, deletesQueued: job2.deletes.length}));
"""
        )
        self.assertEqual(out["notes"], 1)
        self.assertEqual(out["deletesEmpty"], 0)
        self.assertEqual(out["deletesQueued"], 1)

    def test_merge_deleted_union(self):
        out = node_eval(
            """
const S = require('./Store.js');
const m = S.mergeDeleted({a: '2026-01-01T00:00:00.000Z'}, {b: '2026-01-02T00:00:00.000Z'});
const filtered = S.filterDeletedNotes([{id: 'a'}, {id: 'b'}, {id: 'c'}], m);
console.log(JSON.stringify({keys: Object.keys(m).length, kept: filtered.length}));
"""
        )
        self.assertEqual(out["keys"], 2)
        self.assertEqual(out["kept"], 1)

    def test_sync_mjs_supports_delete_flow(self):
        source = (ROOT / "nostr" / "sync.mjs").read_text()
        for token in (
            "const DELETE_KIND = 5;",
            "job.deletes",
            '["k", String(NOTE_KIND)]',
            '["i", noteId]',
            "deletedByNote",
        ):
            with self.subTest(token=token):
                self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
