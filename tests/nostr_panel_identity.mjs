// Run the committed QML JavaScript functions, replacing only UI/file I/O.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const Store=require('../Store.js'), Agent=require('../Agent.js');
const panel=readFileSync(new URL('../Panel.qml',import.meta.url),'utf8');
const names=['persist','loadLocal','loadPeerSnapshot','loadNostrFetch','refilterNostr',
  'mergePeers','commentsFor','refreshDisplay','isLocalNote','isDeletable','deleteNote',
  'hideNote','lanDeletedIds','setLocalShareState','touchLocalNotes'];
const functions=names.map(name=>{
  const match=panel.match(new RegExp('^  function '+name+'\\([\\s\\S]*?^  \\}', 'm'));
  assert(match, 'QML function exists: '+name);
  return match[0];
}).join('\n');
new Function('Store','Agent','assert',`
const alice='a'.repeat(64),bob='b'.repeat(64),me='c'.repeat(64);
const scoped=(author,id)=>'nostr:'+author+':'+id;
const root={myHex:me,myId:'local',nostrFetchRaw:''};
const myHex=me,myId='local';
let nostrAllowList=[alice,bob],allowList=['lan',alice,bob];
let localNotes=[{id:'same',author:'local',title:'local',body:'local',shared:true,comments:[]}];
let peerNotes=[{id:'folder',author:'lan',title:'LAN',shared:true,comments:[]}],nostrPeerNotes=[],displayNotes=[];
let deletedIds={},nostrDeleted=[],pendingDeletes=[],foreignComments={},nostrComments={},outbox=[],hiddenIds=[];
let agentProvenance={},localLoaded=true,localLoadFailed=false,lastLocalRaw='',setupIdentityReady=false;
let selectedNoteId='',gridSelectedNoteId='',unreadIds={},syncConfigured=false;
const setupStage='local',friends=[],syncAttachDir=()=>'';
const copies=[];
const removeAttachDirs=id=>copies.push(id), queueSafeRemove=()=>{},secureFiles=()=>{},trackFreshness=()=>{},writeSnapshot=()=>{},startPublish=()=>{};
const allPeerNotes=()=>peerNotes.concat(nostrPeerNotes);
const localFile={setText:text=>localFile.text=text},notesBakFile={setText:()=>{}},nostrPublishFile={setText:text=>nostrPublishFile.text=text};
${functions}
const note=(author,id,title)=>({id,authorHex:author,title,updatedAt:'2026-10-04T00:00:00.000Z'});
const pair=(author,target,text)=>({noteId:'same',noteAuthor:target,comment:{id:'ref',author,text}});
const raw={notes:[note(alice,'same','Alice'),note(bob,'same','Bob'),note(me,'same','self mirror'),
  note(alice,'folder','Nostr folder'),note(me,'remote','own remote')],
  pairs:[pair(bob,alice,'for Alice'),pair(alice,bob,'for Bob'),pair(bob,me,'for local')]};
loadNostrFetch(JSON.stringify(raw));
assert.deepEqual(displayNotes.map(n=>n.id).sort(),['same','folder',scoped(alice,'same'),scoped(bob,'same'),
  scoped(alice,'folder'),scoped(me,'remote')].sort());
assert.equal(displayNotes.find(n=>n.id==='same').title,'local');
assert.deepEqual(commentsFor(scoped(alice,'same')).map(c=>c.text),['for Alice']);
assert.deepEqual(commentsFor(scoped(bob,'same')).map(c=>c.text),['for Bob']);
assert.deepEqual(commentsFor('same').map(c=>c.text),['for local']);

// Hostile LAN data cannot import a Nostr namespace or claim a verified key.
const lan=loadPeerSnapshot(JSON.stringify({notes:[
  {id:scoped(alice,'same'),author:'lan',shared:true},
  {id:'same',author:me,shared:true},
  {id:'valid',author:'lan',shared:true}],noteComments:[
  {noteId:scoped(alice,'same'),comment:{id:'forged',author:'lan',text:'forged'}},
  {noteId:'same',comment:{id:'forged',author:me,text:'forged'}}]}));
assert.deepEqual(lan.notes.map(n=>n.id),['valid']);
assert.deepEqual(lan.pairs,[]);
assert.equal(isDeletable({id:'untrusted',author:myId}),false);
assert.equal(isDeletable({id:'untrusted',author:me}),false);

hideNote(scoped(alice,'same'));
assert(!displayNotes.some(n=>n.id===scoped(alice,'same')));
assert(displayNotes.some(n=>n.id===scoped(bob,'same')));
outbox=[{noteId:scoped(alice,'folder'),comment:{id:'c-local',author:'local',text:'outgoing'}}];
persist();
const saved=localFile.text;
outbox=[];hiddenIds=[];nostrComments={};
loadLocal(saved);
assert.deepEqual(hiddenIds,[scoped(alice,'same')]);
assert.equal(outbox[0].noteId,scoped(alice,'folder'));
const sent=JSON.parse(nostrPublishFile.text).comments[0];
assert.equal(sent.noteD,'folder');
assert.equal(sent.noteAuthor,alice);
assert(!displayNotes.some(n=>n.id===scoped(alice,'same')));

deleteNote(scoped(bob,'same'));
assert(displayNotes.some(n=>n.id===scoped(bob,'same')),'foreign deletion must be denied inside the action');
assert.deepEqual(Object.keys(deletedIds),[]);
deleteNote(scoped(me,'remote'));
assert(!displayNotes.some(n=>n.id===scoped(me,'remote')));
assert.deepEqual(copies,[],'Nostr identities must never reach filesystem operations');
assert.deepEqual(JSON.parse(nostrPublishFile.text).deletes.map(d=>d.noteId),['remote']);
assert.deepEqual(Object.keys(lanDeletedIds()),[],'Nostr tombstones must not leak into LAN identity');

loadNostrFetch(JSON.stringify({...raw,deleted:[{noteId:'same',author:bob,deletedAt:'2026-10-04T01:00:00.000Z'}]}));
assert(!displayNotes.some(n=>n.id===scoped(bob,'same')));
assert.deepEqual(commentsFor(scoped(bob,'same')),[],'cached comments obey target deletion');
nostrAllowList=[alice];
refilterNostr();
assert.deepEqual(commentsFor(scoped(alice,'same')),[],'revoked signer comments disappear');

// A prior self deletion must not permanently hide a later intentional share.
nostrDeleted=[{noteId:'same',author:me,deletedAt:'2026-10-04T01:00:00.000Z'}];
deletedIds={};pendingDeletes=[];
localNotes[0].shared=false;
const deletionTime = new Date(Math.ceil(Date.now()/1000)*1000).toISOString();
deletedIds={same:deletionTime,[scoped(me,'same')]:deletionTime};
pendingDeletes=['same',scoped(me,'same')];
setLocalShareState('same',true);
assert.deepEqual(Object.keys(deletedIds),[],'reshare clears both raw local and authenticated self aliases');
assert.deepEqual(pendingDeletes,[]);
assert(Math.floor(Date.parse(localNotes[0].updatedAt)/1000)>Math.floor(Date.parse(deletionTime)/1000),
  'reshare must be newer than deletion at Nostr whole-second resolution');
loadNostrFetch(JSON.stringify({notes:[{...note(me,'same','reshared'),updatedAt:localNotes[0].updatedAt}],
  pairs:[pair(alice,me,'after reshare')]}));
assert.deepEqual(commentsFor('same').map(c=>c.text),['after reshare']);
`)(Store,Agent,assert);
console.log('Panel Nostr ownership flow passed');
