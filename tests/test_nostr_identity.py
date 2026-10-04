"""Security contracts across Nostr's signed author and application identity."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def node_eval(script):
    result = subprocess.run(['node', '-e', script], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


PRELUDE = """
const S = require('./Store.js');
const alice = 'a'.repeat(64), bob = 'b'.repeat(64), me = 'c'.repeat(64);
const allow = [alice, bob];
const scoped = (author, id) => 'nostr:' + author + ':' + id;
const note = (author, title, updatedAt = '2026-10-04T01:00:00.000Z') =>
  ({id: 'same', authorHex: author, title, updatedAt});
"""


class NostrIdentityTests(unittest.TestCase):
    def test_panel_fetch_display_persistence_and_authorized_deletion(self):
        result = subprocess.run(['node', 'tests/nostr_panel_identity.mjs'], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Panel Nostr ownership flow passed', result.stdout)

    def test_signed_helper_fetch_and_publish_preserve_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['node', 'tests/nostr_identity_flow.mjs', directory],
                                    cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Signed Nostr ownership flow passed', result.stdout)

    def test_same_wire_id_is_independent_for_each_authenticated_author(self):
        out = node_eval(PRELUDE + """
const f = S.sanitizeNostrFetch({notes: [note(alice, 'old'), note(bob, 'attack', '2099-01-01T00:00:00.000Z'),
  note(alice, 'new', '2026-10-04T02:00:00.000Z')]}, allow, me, {});
console.log(JSON.stringify(f.notes.map(n => ({id:n.id, author:n.author, title:n.title})).sort((a,b) => a.author.localeCompare(b.author))));
""")
        self.assertEqual(out, [
            {'id': 'nostr:' + 'a' * 64 + ':same', 'author': 'a' * 64, 'title': 'new'},
            {'id': 'nostr:' + 'b' * 64 + ':same', 'author': 'b' * 64, 'title': 'attack'},
        ])

    def test_author_deletion_does_not_select_the_other_raw_id_host(self):
        out = node_eval(PRELUDE + """
const f = S.sanitizeNostrFetch({notes:[note(alice, 'victim'), note(bob, 'attack')],
  deleted:[{noteId:'same',author:bob,deletedAt:'2026-10-04T03:00:00.000Z'}]}, allow, me, {});
console.log(JSON.stringify(f.notes.map(n => n.author)));
""")
        self.assertEqual(out, ['a' * 64])

    def test_local_raw_tombstone_has_no_authority_over_a_friend(self):
        out = node_eval(PRELUDE + """
const f = S.sanitizeNostrFetch({notes:[note(alice,'friend'),note(me,'self')]}, allow, me,
  {same:'2026-10-04T03:00:00.000Z'});
console.log(JSON.stringify(f.notes.map(n => n.author)));
""")
        self.assertEqual(out, ['a' * 64])

    def test_comments_route_by_target_author_and_comment_identity_by_signer(self):
        out = node_eval(PRELUDE + """
const pairs = [
  {noteId:'same',noteAuthor:alice,comment:{id:'ref',author:alice,text:'first'}},
  {noteId:'same',noteAuthor:alice,comment:{id:'ref',author:bob,text:'second'}},
  {noteId:'same',noteAuthor:bob,comment:{id:'ref',author:alice,text:'other'}},
  {noteId:'same',comment:{id:'legacy',author:bob,text:'ambiguous'}},
];
const f = S.sanitizeNostrFetch({notes:[note(alice,'a'),note(bob,'b')],pairs},allow,me,{});
const m = S.mergeForeignComments({},f.pairs,allow,'local');
console.log(JSON.stringify({keys:Object.keys(m).sort(),
  alice:(m[scoped(alice,'same')]||[]).map(c=>({id:c.id,text:c.text})),
  bob:(m[scoped(bob,'same')]||[]).map(c=>c.text)}));
""")
        self.assertEqual(out['keys'], ['nostr:' + 'a' * 64 + ':same', 'nostr:' + 'b' * 64 + ':same'])
        self.assertEqual(out['alice'], [
            {'id': 'nostr-comment:' + 'a' * 64 + ':ref', 'text': 'first'},
            {'id': 'nostr-comment:' + 'b' * 64 + ':ref', 'text': 'second'},
        ])
        self.assertEqual(out['bob'], ['other'])

    def test_only_authenticated_self_target_can_alias_local_note(self):
        out = node_eval(PRELUDE + """
const local = [{id:'same',author:'local'}];
const f = S.sanitizeNostrFetch({pairs:[alice,me].map(noteAuthor => ({noteId:'same',noteAuthor,
  comment:{id:'ref',author:bob,text:'hello'}}))}, allow, me, {}, [], local);
console.log(JSON.stringify(f.pairs.map(p => p.noteId)));
""")
        self.assertEqual(out, ['nostr:' + 'a' * 64 + ':same', 'same'])

    def test_publish_preserves_comment_target_and_limits_scoped_delete_to_self(self):
        out = node_eval(PRELUDE + """
const outbox = [{noteId:scoped(alice,'same'),comment:{id:'c-1',author:'local',text:'hello'}}];
const deleted = {[scoped(alice,'same')]:'2026-10-04T03:00:00.000Z',
  [scoped(me,'mine')]:'2026-10-04T03:00:00.000Z',local:'2026-10-04T03:00:00.000Z'};
const job = S.buildNostrPublish([],outbox,deleted,undefined,me);
console.log(JSON.stringify({comment:job.comments[0],ids:job.deletes.map(d=>d.noteId).sort()}));
""")
        self.assertEqual(out['comment'], {'ref':'c-1','noteD':'same','noteAuthor':'a'*64,'text':'hello'})
        self.assertEqual(out['ids'], ['local', 'mine'])

    def test_comment_cache_rechecks_current_permission(self):
        out = node_eval(PRELUDE + """
const cache = {target:[{id:'c-1',author:alice,text:'gone'},{id:'c-2',author:bob,text:'keep'}]};
console.log(JSON.stringify(S.mergeForeignComments(cache,[],[bob],'local').target.map(c=>c.text)));
""")
        self.assertEqual(out, ['keep'])

    def test_reserved_keys_do_not_behave_as_deleted_or_throw_on_comments(self):
        out = node_eval(PRELUDE + """
const ids = ['constructor','__proto__','toString'];
const m = S.mergeForeignComments({},ids.map(id=>({noteId:id,comment:{id,author:alice,text:'safe'}})),allow,'local');
console.log(JSON.stringify({deleted:ids.map(id=>S.isDeleted({},id)),
  comments:ids.map(id=>(m[id]||[]).length), tombs:Object.keys(S.sanitizeDeleted(JSON.parse('{"__proto__":"2026-10-04T03:00:00.000Z"}')))}));
""")
        self.assertEqual(out, {'deleted':[False]*3,'comments':[1,0,1],'tombs':[]})

    def test_newer_author_note_can_be_reshared_but_stale_copy_stays_deleted(self):
        out = node_eval(PRELUDE + """
const saved = [{noteId:'same',author:alice,deletedAt:'2026-10-04T03:00:00.000Z'}];
const old = S.sanitizeNostrFetch({notes:[note(alice,'stale')]},allow,me,{},saved);
const fresh = S.sanitizeNostrFetch({notes:[note(alice,'reshared','2026-10-04T04:00:00.000Z')]},allow,me,{},saved);
console.log(JSON.stringify({old:old.notes.length,fresh:fresh.notes.length}));
""")
        self.assertEqual(out, {'old':0,'fresh':1})

    def test_longest_wire_id_roundtrips_without_becoming_a_filesystem_id(self):
        out = node_eval(PRELUDE + """
const rawId='x'.repeat(128);
const f=S.sanitizeNostrFetch({notes:[{id:rawId,authorHex:alice}]},allow,me,{});
const id=f.notes[0].id;
const hidden=S.sanitizeHidden([id]);
const box=S.sanitizeOutbox([{noteId:id,comment:{id:'c',author:'local',text:'hello'}}]);
console.log(JSON.stringify({id,hidden,box:box.map(p=>p.noteId),filesystem:S.isSafeId(id)}));
""")
        scoped = 'nostr:' + 'a'*64 + ':' + 'x'*128
        self.assertEqual(out, {'id':scoped,'hidden':[scoped],'box':[scoped],'filesystem':False})
