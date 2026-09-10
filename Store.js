// TransNote store logic — pure JS, no Qt imports, Node-testable.
// Schema:
//   note: { id, title, body, author, createdAt, updatedAt, shared, comments: [], attachments: [] }
//   comment: { id, author, text, createdAt }
// Attachments are reserved for later: notes always carry `attachments: []`
// and peers ignore entries they do not understand.

function nowIso() {
  return new Date().toISOString()
}

function uid(prefix) {
  return (prefix || "id") + "-" + Date.now().toString(36) + "-" + Math.floor(Math.random() * 0xffffff).toString(36)
}

function normalizeText(value) {
  return String(value === undefined || value === null ? "" : value).trim()
}

// Parse the allowList setting, which may be an array, a comma-separated
// string, or empty.
function parseAllowList(value) {
  if (Array.isArray(value)) {
    return value.map(function (v) { return normalizeText(v) }).filter(function (v) { return v !== "" })
  }
  return String(value || "").split(",").map(function (v) { return normalizeText(v) }).filter(function (v) { return v !== "" })
}

// A peer is qualified when its device id is on the owner's allow-list.
// Allow-list entries may be device ids ("laptop") or Nostr pubkeys
// (64-char hex). npub values must be converted to hex first — see
// `node nostr/sync.mjs npub-to-hex --npub <npub>` — because this file
// stays dependency-free for QML.
function isHexPubkey(value) {
  return /^[0-9a-fA-F]{64}$/.test(normalizeText(value))
}

function normalizePubkey(value) {
  var s = normalizeText(value).toLowerCase()
  return isHexPubkey(s) ? s : ""
}

function isQualified(peerId, allowList) {
  var list = parseAllowList(allowList)
  var peer = normalizeText(peerId)
  if (peer === "") return false
  // Hex pubkeys compare case-insensitively; device ids compare exactly.
  if (isHexPubkey(peer)) {
    peer = peer.toLowerCase()
    for (var i = 0; i < list.length; i++) {
      if (normalizeText(list[i]).toLowerCase() === peer) return true
    }
    return false
  }
  return list.indexOf(peer) !== -1
}

function createNote(title, body, author) {
  var now = nowIso()
  return {
    id: uid("note"),
    title: normalizeText(title) || "Untitled",
    body: normalizeText(body),
    author: normalizeText(author) || "local",
    createdAt: now,
    updatedAt: now,
    shared: false,
    comments: [],
    attachments: []
  }
}

function sanitizeNote(raw) {
  if (!raw || typeof raw !== "object") return null
  var note = {
    id: normalizeText(raw.id),
    title: normalizeText(raw.title) || "Untitled",
    body: normalizeText(raw.body),
    author: normalizeText(raw.author) || "unknown",
    createdAt: normalizeText(raw.createdAt) || nowIso(),
    updatedAt: normalizeText(raw.updatedAt) || normalizeText(raw.createdAt) || nowIso(),
    shared: raw.shared === true,
    comments: [],
    attachments: []
  }
  if (note.id === "") return null
  var comments = Array.isArray(raw.comments) ? raw.comments : []
  for (var i = 0; i < comments.length; i++) {
    var c = sanitizeComment(comments[i])
    if (c) note.comments.push(c)
  }
  // Attachments are accepted and preserved verbatim so a future version can
  // render them; unknown entry shapes are dropped.
  var atts = Array.isArray(raw.attachments) ? raw.attachments : []
  for (var j = 0; j < atts.length; j++) {
    if (atts[j] && typeof atts[j] === "object" && normalizeText(atts[j].id) !== "") note.attachments.push(atts[j])
  }
  return note
}

function sanitizeComment(raw) {
  if (!raw || typeof raw !== "object") return null
  var c = {
    id: normalizeText(raw.id),
    author: normalizeText(raw.author) || "unknown",
    text: normalizeText(raw.text),
    createdAt: normalizeText(raw.createdAt) || nowIso()
  }
  if (c.id === "" || c.text === "") return null
  return c
}

function createComment(author, text) {
  var t = normalizeText(text)
  if (t === "") return null
  return {
    id: uid("c"),
    author: normalizeText(author) || "local",
    text: t,
    createdAt: nowIso()
  }
}

function addComment(note, author, text) {
  if (!note) return null
  var c = createComment(author, text)
  if (!c) return null
  if (!Array.isArray(note.comments)) note.comments = []
  note.comments.push(c)
  note.updatedAt = nowIso()
  return c
}

// Only the note author (owner) flips the shared flag; peers cannot
// re-share someone else's note.
function setShared(note, shared, requester) {
  if (!note) return false
  if (normalizeText(requester) !== "" && normalizeText(requester) !== note.author) return false
  note.shared = shared === true
  note.updatedAt = nowIso()
  return true
}

// Notes visible to `viewerId`: own notes always, plus shared notes whose
// author qualifies the viewer OR whose owner (me) qualified the author.
// `myId` is this device; `allowList` is my allow-list.
function visibleNotes(notes, viewerId, myId, allowList) {
  var list = Array.isArray(notes) ? notes : []
  var me = normalizeText(myId)
  var viewer = normalizeText(viewerId)
  return list.filter(function (n) {
    if (!n) return false
    if (viewer === me) return true
    if (n.shared !== true) return false
    // My shared notes: viewer must be qualified by me.
    if (n.author === me) return isQualified(viewer, allowList)
    // A peer's shared note: I must have qualified its author.
    return isQualified(n.author, allowList)
  })
}

// Merge an incoming peer snapshot into local notes.
// Rules: union by note id, last-updated wins for note fields, union comments
// by id. Incoming notes are only accepted when they are shared AND their
// author is qualified by my allow-list — except notes authored by myId
// itself, which is how a second device of the same user syncs.
// Incoming comments on my notes are only accepted from qualified peers
// (or myself).
function mergeNotes(localNotes, incomingNotes, myAllowList, myId) {
  var me = normalizeText(myId)
  var allowed = function (author) {
    var a = normalizeText(author)
    if (a !== "" && a === me) return true
    return isQualified(a, myAllowList)
  }
  var local = (Array.isArray(localNotes) ? localNotes : []).map(sanitizeNote).filter(function (n) { return !!n })
  var incoming = (Array.isArray(incomingNotes) ? incomingNotes : []).map(sanitizeNote).filter(function (n) { return !!n })
  var byId = {}
  local.forEach(function (n) { byId[n.id] = n })

  incoming.forEach(function (peer) {
    if (peer.shared !== true) return
    if (!allowed(peer.author)) return
    var existing = byId[peer.id]
    if (!existing) {
      byId[peer.id] = peer
      return
    }
    // Last write wins for the note envelope; comments merge by id so no
    // comment is ever lost by an older envelope overwriting a newer one.
    var knownComments = {}
    existing.comments.forEach(function (c) { knownComments[c.id] = true })
    peer.comments.forEach(function (c) {
      if (!knownComments[c.id]) {
        // Only accept peer comments from qualified authors (or myself).
        if (allowed(c.author) || c.author === peer.author) {
          existing.comments.push(c)
          knownComments[c.id] = true
        }
      }
    })
    if (peer.updatedAt >= existing.updatedAt) {
      existing.title = peer.title
      existing.body = peer.body
      existing.updatedAt = peer.updatedAt
      existing.shared = peer.shared
      existing.attachments = peer.attachments
    }
    existing.comments.sort(function (a, b) { return a.createdAt < b.createdAt ? -1 : 1 })
  })

  var out = Object.keys(byId).map(function (k) { return byId[k] })
  out.sort(function (a, b) { return a.updatedAt < b.updatedAt ? 1 : -1 })
  return out
}

function sortNotes(notes) {
  var out = (Array.isArray(notes) ? notes.slice() : [])
  out.sort(function (a, b) { return (a.updatedAt || "") < (b.updatedAt || "") ? 1 : -1 })
  return out
}

// Outbox entries: my comments on peers' notes, published in my snapshot as
// { noteId, comment } pairs so the note author can merge them in.
// Sanitize to a clean [{ noteId, comment }] array.
function sanitizeOutbox(raw) {
  var out = []
  var arr = Array.isArray(raw) ? raw : []
  for (var i = 0; i < arr.length; i++) {
    var entry = arr[i]
    if (!entry || typeof entry !== "object") continue
    var noteId = normalizeText(entry.noteId)
    var c = sanitizeComment(entry.comment)
    if (noteId === "" || !c) continue
    out.push({ noteId: noteId, comment: c })
  }
  return out
}

// Merge incoming { noteId, comment } pairs into a { noteId: [comment] } map.
// Only comments from qualified authors (or myself) are accepted; union by
// comment id so repeats across snapshots never duplicate.
function mergeForeignComments(existingMap, incomingPairs, myAllowList, myId) {
  var me = normalizeText(myId)
  var merged = {}
  var src = existingMap && typeof existingMap === "object" ? existingMap : {}
  Object.keys(src).forEach(function (k) {
    merged[k] = (Array.isArray(src[k]) ? src[k] : []).map(sanitizeComment).filter(function (c) { return !!c })
  })
  sanitizeOutbox(incomingPairs).forEach(function (entry) {
    var author = normalizeText(entry.comment.author)
    if (author === "" || !(author === me || isQualified(author, myAllowList))) return
    if (!merged[entry.noteId]) merged[entry.noteId] = []
    var known = false
    for (var i = 0; i < merged[entry.noteId].length; i++) {
      if (merged[entry.noteId][i].id === entry.comment.id) { known = true; break }
    }
    if (!known) merged[entry.noteId].push(entry.comment)
    merged[entry.noteId].sort(function (a, b) { return a.createdAt < b.createdAt ? -1 : 1 })
  })
  return merged
}

// Drop outbox entries whose note is gone from both local and peer notes,
// so deleted peer notes don't accumulate stale comments forever.
function pruneOutbox(outbox, localNotes, peerNotes) {
  var alive = {}
  ;(Array.isArray(localNotes) ? localNotes : []).forEach(function (n) { if (n) alive[n.id] = true })
  ;(Array.isArray(peerNotes) ? peerNotes : []).forEach(function (n) { if (n) alive[n.id] = true })
  return sanitizeOutbox(outbox).filter(function (entry) { return !!alive[entry.noteId] })
}

// Hex recipients among the allow-list — the only entries usable for
// encrypted Nostr publish. Device ids are for folder sync and ignored here.
function hexRecipients(allowList) {
  return parseAllowList(allowList).filter(function (v) { return isHexPubkey(v) }).map(function (v) { return normalizePubkey(v) })
}

// Short preview of a note body for the collapsed list view. Returns
// { text, truncated }. Plain truncation (no QML maximumLineCount) so a long
// note can never overflow its delegate and paint over the footer.
function previewBody(body, maxLines, maxChars) {
  var src = String(body === undefined || body === null ? "" : body)
  var lines = maxLines === undefined ? 6 : maxLines
  var chars = maxChars === undefined ? 600 : maxChars
  if (src === "") return { text: "", truncated: false }
  var parts = src.split("\n")
  var cutByLines = parts.length > lines
  var text = parts.slice(0, lines).join("\n")
  var cutByChars = false
  if (text.length > chars) {
    var cut = text.slice(0, chars)
    var sp = cut.lastIndexOf(" ")
    text = (sp > chars * 0.5 ? cut.slice(0, sp) : cut) + "…"
    cutByChars = true
  } else if (cutByLines) {
    text = text + "…"
  }
  return { text: text, truncated: cutByLines || cutByChars }
}
// Friends file (managed in the panel UI, no terminal needed):
// { version: 1, friends: [{ hex, name }] }. Accepts the raw file text,
// the parsed object, or an already-clean array (idempotent).
function sanitizeFriends(raw) {
  var out = []
  try {
    var parsed = typeof raw === "string" ? JSON.parse(raw || "") : (raw || {})
    var arr = parsed && Array.isArray(parsed.friends) ? parsed.friends : (Array.isArray(parsed) ? parsed : [])
    var seen = {}
    for (var i = 0; i < arr.length; i++) {
      var e = arr[i]
      if (!e || typeof e !== "object") continue
      var hex = normalizePubkey(e.hex || e.pubkey)
      if (hex === "" || seen[hex]) continue
      seen[hex] = true
      var name = normalizeText(e.name).slice(0, 40)
      out.push({ hex: hex, name: name || hex.slice(0, 8) })
    }
  } catch (e) { /* ignore bad friends file */ }
  return out
}

// Everyone allowed on the internet path: hex entries from the allow-list
// setting plus friends added in the panel UI. De-duplicated hex array.
function effectiveNostrAllow(allowList, friends) {
  var seen = {}
  var out = []
  hexRecipients(allowList).forEach(function (h) { if (!seen[h]) { seen[h] = true; out.push(h) } })
  sanitizeFriends(friends).forEach(function (f) { if (!seen[f.hex]) { seen[f.hex] = true; out.push(f.hex) } })
  return out
}

// Convert `fetch --out` JSON into internal { notes, pairs }.
// fetch output: { notes:[{id,title,body,authorHex,updatedAt,eventId}],
//                 pairs:[{noteId,comment:{id,author,text,createdAt}}] }.
// Returned notes are marked shared=true and carry the hex author so the
// normal allow-list filter applies. Unknown authors are dropped unless
// they are myHex itself (second device of the same user).
function sanitizeNostrFetch(raw, allowList, myHex) {
  var notes = []
  var pairs = []
  try {
    var parsed = typeof raw === "string" ? JSON.parse(raw || "") : (raw || {})
    var me = normalizePubkey(myHex)
    var arr = parsed && Array.isArray(parsed.notes) ? parsed.notes : []
    for (var i = 0; i < arr.length; i++) {
      var n = arr[i]
      if (!n || typeof n !== "object") continue
      var authorHex = normalizePubkey(n.authorHex || n.author)
      if (authorHex === "") continue
      if (!(authorHex === me || isQualified(authorHex, allowList))) continue
      var clean = sanitizeNote({
        id: n.id,
        title: n.title,
        body: n.body,
        author: authorHex,
        createdAt: n.updatedAt || n.createdAt,
        updatedAt: n.updatedAt,
        shared: true,
        comments: [],
        attachments: []
      })
      if (clean) notes.push(clean)
    }
    var rawPairs = parsed && Array.isArray(parsed.pairs) ? parsed.pairs : []
    for (var j = 0; j < rawPairs.length; j++) {
      var e = rawPairs[j]
      if (!e || typeof e !== "object") continue
      var c = e.comment
      if (!c || typeof c !== "object") continue
      var ca = normalizePubkey(c.author)
      if (ca === "") continue
      if (!(ca === me || isQualified(ca, allowList))) continue
      var sc = sanitizeComment({ id: c.id, author: ca, text: c.text, createdAt: c.createdAt })
      var noteId = normalizeText(e.noteId)
      if (noteId === "" || !sc) continue
      pairs.push({ noteId: noteId, comment: sc })
    }
  } catch (e) { /* ignore bad fetch file */ }
  return { notes: notes, pairs: pairs }
}

// Build publish.json for `sync.mjs publish` from shared local notes +
// outbox comments. sync.mjs encrypts one copy per --recipients pubkey.
function buildNostrPublish(localNotes, outbox) {
  var notes = []
  var comments = []
  ;(Array.isArray(localNotes) ? localNotes : []).forEach(function (n) {
    if (!n || n.shared !== true) return
    var clean = sanitizeNote(n)
    if (!clean) return
    notes.push({ ref: clean.id, d: clean.id, title: clean.title, body: clean.body, updatedAt: clean.updatedAt })
  })
  sanitizeOutbox(outbox).forEach(function (entry) {
    comments.push({ ref: entry.comment.id, noteD: entry.noteId, text: entry.comment.text })
  })
  return { notes: notes, comments: comments }
}

if (typeof module !== "undefined") {
  module.exports = {
    nowIso: nowIso,
    uid: uid,
    normalizeText: normalizeText,
    parseAllowList: parseAllowList,
    isHexPubkey: isHexPubkey,
    normalizePubkey: normalizePubkey,
    isQualified: isQualified,
    createNote: createNote,
    createComment: createComment,
    sanitizeNote: sanitizeNote,
    sanitizeComment: sanitizeComment,
    sanitizeOutbox: sanitizeOutbox,
    mergeForeignComments: mergeForeignComments,
    pruneOutbox: pruneOutbox,
    previewBody: previewBody,
    hexRecipients: hexRecipients,
    sanitizeFriends: sanitizeFriends,
    effectiveNostrAllow: effectiveNostrAllow,
    sanitizeNostrFetch: sanitizeNostrFetch,
    buildNostrPublish: buildNostrPublish,
    addComment: addComment,
    setShared: setShared,
    visibleNotes: visibleNotes,
    mergeNotes: mergeNotes,
    sortNotes: sortNotes
  }
}
