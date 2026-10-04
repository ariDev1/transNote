// Exercise the real helper with signed, encrypted events. Only relay I/O is
// replaced; parsing, ownership, encryption and publication are production code.
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { dirname, join } from 'node:path';
import { createRequire } from 'node:module';
import * as nostr from 'nostr-tools';

const Store = createRequire(import.meta.url)('../Store.js');
const dir = process.argv[2];
const keys = [1, 2, 3].map(n => Uint8Array.from({length:32}, (_,i) => i === 31 ? n : 0));
const [alice, bob, me] = keys.map(nostr.getPublicKey);
const keyFile = join(dir, 'key');
const outFile = join(dir, 'fetch.json');
fs.writeFileSync(keyFile, Buffer.from(keys[2]).toString('hex'), {mode:0o600});
let events = [], publications = [];
const query = nostr.SimplePool.prototype.querySync;
const publish = nostr.SimplePool.prototype.publish;
nostr.SimplePool.prototype.querySync = async () => events;
nostr.SimplePool.prototype.publish = (_relays, event) => {
  publications.push(event);
  return [Promise.resolve('accepted')];
};
const source = fs.readFileSync(new URL('../nostr/sync.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').split('const [cmd, ...rest]')[0];
const env = {existsSync:fs.existsSync, mkdirSync:fs.mkdirSync, readFileSync:fs.readFileSync,
  writeFileSync:fs.writeFileSync, chmodSync:fs.chmodSync, dirname, ...nostr, console: {log() {}}};
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const helper = await new AsyncFunction(...Object.keys(env), source + '\nreturn {cmdFetch,cmdPublish};')(...Object.values(env));
const fetchArgs = {'key-file':keyFile, relays:'wss://fixture.invalid', 'allow-list':[alice,bob].join(','), out:outFile};
const encrypted = (key, kind, time, tags, content) => nostr.finalizeEvent({kind,created_at:time,
  tags:[['p',me],['t','transnote'],['enc','nip44-v2'],...tags],
  content:nostr.nip44.encrypt(JSON.stringify(content), nostr.nip44.getConversationKey(key,me))},key);
const note = (key, time, title) => encrypted(key,30078,time,[['d','same:'+me]],{title,body:title});
const comment = (key, target, text, withOwner = true) => encrypted(key,1,100,
  [['i','same'], ...(withOwner ? [['a',`30078:${target}:same`]] : [])],
  {ref:'ref',text,...(withOwner ? {noteAuthor:target} : {})});
const del = (key,time) => nostr.finalizeEvent({kind:5,created_at:time,
  tags:[['p',me],['t','transnote'],['i','same']],content:''},key);
async function fetch(extra = {}) {
  await helper.cmdFetch({...fetchArgs,...extra});
  return JSON.parse(fs.readFileSync(outFile,'utf8'));
}
try {
  events=[note(keys[0],90,'alice'),note(keys[1],200,'bob'),
    comment(keys[1],alice,'on alice'),comment(keys[0],bob,'on bob'),
    comment(keys[1],alice,'legacy',false)];
  let raw=await fetch();
  let clean=Store.sanitizeNostrFetch(raw,[alice,bob],me,{});
  assert.equal(clean.notes.length,2,'colliding signed note IDs retain both owners');
  assert.deepEqual(raw.pairs.map(p=>p.noteAuthor).sort(),[alice,bob].sort(),
    'target author survives helper decryption; ownerless legacy comments are rejected');
  assert.deepEqual(clean.pairs.map(p=>p.noteId).sort(),[alice,bob].map(a=>`nostr:${a}:same`).sort());

  events=[encrypted(keys[0],30078,100,[['d','same:'+me]],null),
    encrypted(keys[0],30078,100,[['d','same:'+me]],{title:{toString:null},body:'malformed'}),
    encrypted(keys[0],1,100,[['i','same']],{text:{toString:null},noteAuthor:alice}),
    encrypted(keys[1],1,100,[['i','same'],['a',`30078:${alice}:same`]],{ref:'ref',text:'conflict',noteAuthor:bob}),
    encrypted(keys[0],30078,100,[['d',`nostr:${bob}:same:${me}`]],{title:'forged namespace'}),
    note(keys[0],90,'valid')];
  raw=await fetch();
  assert.deepEqual(raw.notes.map(n=>n.title),['valid'],'malformed content and wire namespaces are rejected');
  assert.deepEqual(raw.pairs,[],'conflicting target declarations fail closed');

  events=[note(keys[0],90,'alice'),note(keys[1],200,'bob'),del(keys[1],300),
    comment(keys[1],alice,'keep'),comment(keys[0],bob,'drop')];
  raw=await fetch();
  assert.deepEqual(raw.notes.map(n=>n.authorHex),[alice]);
  assert.deepEqual(raw.pairs.map(p=>p.noteAuthor),[alice]);

  events=[note(keys[0],90,'alice'),del(keys[0],100),note(keys[0],110,'reshare')];
  raw=await fetch();
  assert.deepEqual(raw.notes.map(n=>n.title),['reshare']);

  const forged=JSON.parse(JSON.stringify(note(keys[1],200,'bob')));
  forged.pubkey=alice;
  events=[forged];
  raw=await fetch();
  assert.equal(raw.notes.length,0,'invalid signature cannot assert another author');

  // Public legacy comments require an author-qualified signed address too.
  const publicEvent=(tags)=>nostr.finalizeEvent({kind:1,created_at:100,
    tags:[['t','transnote'],['i','same'],...tags],content:'public'},keys[1]);
  events=[publicEvent([['a',`30078:${alice}:same`]]),publicEvent([])];
  raw=await fetch({'include-public':'1'});
  assert.deepEqual(raw.pairs.map(p=>p.noteAuthor),[alice]);

  const job=Store.buildNostrPublish([], [{noteId:`nostr:${alice}:same`,
    comment:{id:'outgoing-ref',author:'local',text:'hello'}}],
    {[`nostr:${me}:same`]:'2026-10-04T00:00:00.000Z'},undefined,me);
  const jobFile=join(dir,'publish.json');
  fs.writeFileSync(jobFile,JSON.stringify(job));
  await helper.cmdPublish({'key-file':keyFile,relays:'wss://fixture.invalid',in:jobFile,recipients:alice});
  const outgoing=publications.find(e=>e.kind===1);
  assert(nostr.verifyEvent(outgoing));
  assert(outgoing.tags.some(t=>t[0]==='i' && t[1]==='same'));
  assert(outgoing.tags.some(t=>t[0]==='a' && t[1]===`30078:${alice}:same`));
  const clear=JSON.parse(nostr.nip44.decrypt(outgoing.content,
    nostr.nip44.getConversationKey(keys[0],me)));
  assert.deepEqual(clear,{text:'hello',ref:'outgoing-ref',noteAuthor:alice});
  const outgoingDelete=publications.find(e=>e.kind===5);
  assert(outgoingDelete.tags.some(t=>t[0]==='i' && t[1]==='same'));
  assert(outgoingDelete.tags.some(t=>t[0]==='a' && t[1]===`30078:${me}:same:${alice}`));
  console.log('Signed Nostr ownership flow passed');
} finally {
  nostr.SimplePool.prototype.querySync=query;
  nostr.SimplePool.prototype.publish=publish;
}
// The production relay timeout races retain timers for 20 seconds.
process.exit(0);
