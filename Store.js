// TransNote store logic — pure JS, no Qt imports, Node-testable.
// Schema:
//   note: { id, title, body, author, createdAt, updatedAt, shared, comments: [], attachments: [] }
//   comment: { id, author, text, createdAt }
// Attachments ride the note as strict metadata records (see
// sanitizeAttachment) with bytes synced as folder sidecars; peers verify
// the SHA-256 hash before trusting them.

function nowIso() {
  return new Date().toISOString()
}

function uid(prefix) {
  return (prefix || "id") + "-" + Date.now().toString(36) + "-" + Math.floor(Math.random() * 0xffffff).toString(36)
}

function normalizeText(value) {
  return String(value === undefined || value === null ? "" : value).trim()
}

// IDs that cross a sync boundary can become filesystem path components.
// Accept only the grammar produced by TransNote's uid() helper.
var SAFE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/

function isSafeId(value) {
  return SAFE_ID_RE.test(normalizeText(value))
}

function sanitizeId(value) {
  var s = normalizeText(value)
  return isSafeId(s) || splitNostrNoteId(s) ? s : ""
}

// Nostr IDs are application identities, never filesystem components. Raw
// wire IDs stay within the original grammar; the signed author supplies the
// namespace. No metadata supplied by a peer can choose another namespace.
function nostrNoteId(author, wireId) {
  var hex = normalizePubkey(author)
  var id = normalizeText(wireId)
  return hex !== "" && isSafeId(id) ? "nostr:" + hex + ":" + id : ""
}

function splitNostrNoteId(value) {
  var match = /^nostr:([0-9a-f]{64}):([A-Za-z0-9][A-Za-z0-9_-]{0,127})$/.exec(normalizeText(value))
  return match ? { author: match[1], noteId: match[2] } : null
}

function nostrTimestamp(value) {
  var stamp = Date.parse(normalizeText(value))
  return isFinite(stamp) ? new Date(stamp).toISOString() : "1970-01-01T00:00:00.000Z"
}

function nostrReshareTimestamp(id, myHex, deletedMap, receivedDeleted) {
  var stamp = Date.now()
  function after(value) {
    var deletedAt = Date.parse(normalizeText(value))
    if (isFinite(deletedAt)) stamp = Math.max(stamp, (Math.floor(deletedAt / 1000) + 1) * 1000)
  }
  var local = sanitizeDeleted(deletedMap)
  after(local[id])
  after(local[nostrNoteId(myHex, id)])
  sanitizeNostrDeleted(receivedDeleted).forEach(function (entry) {
    if (entry.noteId === id && entry.author === normalizePubkey(myHex)) after(entry.deletedAt)
  })
  return new Date(stamp).toISOString()
}

// Parse the allowList setting, which may be an array, a comma-separated
// string, or empty.
function parseAllowList(value) {
  if (Array.isArray(value)) {
    return value.map(function (v) { return normalizeText(v) }).filter(function (v) { return v !== "" })
  }
  return String(value || "").split(",").map(function (v) { return normalizeText(v) }).filter(function (v) { return v !== "" })
}

// Private local fallback for the three Omarchy widget settings.
// This state is never part of note, LAN, or Nostr payloads.
function sanitizeSetupBackup(raw) {
  var parsed = Object.create(null)

  try {
    if (typeof raw === "string") parsed = JSON.parse(raw || "")
    else if (raw && typeof raw === "object" && !Array.isArray(raw)) parsed = raw
  } catch (e) {
    parsed = {}
  }

  var allow = parsed && parsed.allowList
  if (Array.isArray(allow)) allow = parseAllowList(allow).join(", ")

  return {
    version: 1,
    deviceId: normalizeText(parsed && parsed.deviceId),
    syncDir: normalizeText(parsed && parsed.syncDir),
    allowList: normalizeText(allow)
  }
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
    attachments: [],
    // A fresh random tint per note (cycle back to plain any time).
    color: NOTE_COLORS[Math.floor(Math.random() * NOTE_COLORS.length)]
  }
}

function sanitizeNote(raw) {
  if (!raw || typeof raw !== "object") return null
  var note = {
    id: sanitizeId(raw.id),
    title: normalizeText(raw.title) || "Untitled",
    body: normalizeText(raw.body),
    author: normalizeText(raw.author) || "unknown",
    createdAt: normalizeText(raw.createdAt) || nowIso(),
    updatedAt: normalizeText(raw.updatedAt) || normalizeText(raw.createdAt) || nowIso(),
    shared: raw.shared === true,
    comments: [],
    attachments: [],
    color: sanitizeColor(raw.color)
  }
  if (note.id === "") return null
  var comments = Array.isArray(raw.comments) ? raw.comments : []
  for (var i = 0; i < comments.length; i++) {
    var c = sanitizeComment(comments[i])
    if (c) note.comments.push(c)
  }
  // Attachments are accepted only as strict records (see
  // sanitizeAttachment): unknown or oversized entries are dropped, so a
  // hostile snapshot cannot smuggle paths or giant blobs into the UI.
  var atts = Array.isArray(raw.attachments) ? raw.attachments : []
  for (var j = 0; j < atts.length; j++) {
    var a = sanitizeAttachment(atts[j])
    if (a) note.attachments.push(a)
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

// Same ownership for the tint: only the author recolors (it syncs to
// everyone). Unknown keys are rejected, "" clears back to plain.
function setColor(note, color, requester) {
  if (!note) return false
  if (normalizeText(requester) !== "" && normalizeText(requester) !== note.author) return false
  note.color = sanitizeColor(color)
  note.updatedAt = nowIso()
  return true
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
    var noteId = sanitizeId(entry.noteId)
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
  var merged = Object.create(null)
  var src = existingMap && typeof existingMap === "object" ? existingMap : {}
  Object.keys(src).forEach(function (k) {
    merged[k] = (Array.isArray(src[k]) ? src[k] : []).map(sanitizeComment).filter(function (c) {
      return c && (c.author === me || isQualified(c.author, myAllowList))
    })
  })
  sanitizeOutbox(incomingPairs).forEach(function (entry) {
    var author = normalizeText(entry.comment.author)
    if (author === "" || !(author === me || isQualified(author, myAllowList))) return
    if (!merged[entry.noteId]) merged[entry.noteId] = []
    var known = false
    for (var i = 0; i < merged[entry.noteId].length; i++) {
      if (merged[entry.noteId][i].id === entry.comment.id && merged[entry.noteId][i].author === author) { known = true; break }
    }
    if (!known) merged[entry.noteId].push(entry.comment)
    merged[entry.noteId].sort(function (a, b) { return a.createdAt < b.createdAt ? -1 : 1 })
  })
  return merged
}

// Drop outbox entries whose note is gone from both local and peer notes,
// so deleted peer notes don't accumulate stale comments forever.
function pruneOutbox(outbox, localNotes, peerNotes) {
  var alive = Object.create(null)
  ;(Array.isArray(localNotes) ? localNotes : []).forEach(function (n) { if (n) alive[n.id] = true })
  ;(Array.isArray(peerNotes) ? peerNotes : []).forEach(function (n) { if (n) alive[n.id] = true })
  return sanitizeOutbox(outbox).filter(function (entry) { return !!alive[entry.noteId] })
}

// Deletion tombstones: { "<noteId>": "<deletedAtIso>" }.
// A local delete must survive the next sync — otherwise folder peers with
// stale snapshots and Nostr relays (which keep ciphertext) resurrect the
// note on the next fetch. Tombstones are published in the LAN snapshot
// (deletedIds) and as NIP-09 kind-5 events on Nostr, and every merge path
// filters against them. Delete-wins over concurrent edits.
function sanitizeDeleted(raw) {
  var out = Object.create(null)
  try {
    if (Array.isArray(raw)) {
      raw.forEach(function (entry) {
        if (typeof entry === "string") {
          var id = sanitizeId(entry)
          if (id !== "") out[id] = nowIso()
        } else if (entry && typeof entry === "object") {
          var eid = sanitizeId(entry.id || entry.noteId)
          if (eid !== "") out[eid] = normalizeText(entry.deletedAt) || nowIso()
        }
      })
    } else if (raw && typeof raw === "object") {
      Object.keys(raw).forEach(function (k) {
        var id = sanitizeId(k)
        if (id === "") return
        var v = raw[k]
        out[id] = normalizeText(typeof v === "string" ? v : (v && v.deletedAt)) || nowIso()
      })
    }
  } catch (e) { /* ignore bad tombstone block */ }
  return out
}

function addTombstone(deletedMap, id) {
  var out = Object.create(null)
  var src = sanitizeDeleted(deletedMap)
  Object.keys(src).forEach(function (k) { out[k] = src[k] })
  var clean = sanitizeId(id)
  if (clean !== "") out[clean] = nowIso()
  return out
}

function mergeDeleted() {
  var out = Object.create(null)
  for (var i = 0; i < arguments.length; i++) {
    var m = sanitizeDeleted(arguments[i])
    Object.keys(m).forEach(function (k) {
      if (!out[k] || m[k] > out[k]) out[k] = m[k]
    })
  }
  return out
}

function isDeleted(deletedMap, id) {
  if (!deletedMap || typeof deletedMap !== "object") return false
  return Object.prototype.hasOwnProperty.call(deletedMap, normalizeText(id)) && !!deletedMap[normalizeText(id)]
}

function filterDeletedNotes(notes, deletedMap) {
  if (!deletedMap || typeof deletedMap !== "object") return notes
  return (Array.isArray(notes) ? notes : []).filter(function (n) {
    return n && !isDeleted(deletedMap, n.id)
  })
}

// Local-only hides: dismissing a peer's note hides it on this machine only
// (never published, never affects others). Stored as a plain id array in
// the local file, capped so it stays small.
var MAX_HIDDEN = 1000

function sanitizeHidden(raw) {
  var out = []
  var seen = Object.create(null)
  var arr = Array.isArray(raw) ? raw : []
  for (var i = 0; i < arr.length; i++) {
    var entry = arr[i]
    var id
    if (typeof entry === "string") id = sanitizeId(entry)
    else if (entry && typeof entry === "object" && entry.id !== undefined) id = sanitizeId(entry.id)
    else continue
    if (id === "" || seen[id]) continue
    seen[id] = true
    out.push(id)
    if (out.length >= MAX_HIDDEN) break
  }
  return out
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
// Note tint keys (UI maps them to translucent theme-safe colors).
// Stored on the note and synced like any other field.
var NOTE_COLORS = ["red", "orange", "yellow", "green", "blue", "violet"]

function sanitizeColor(value) {
  var s = normalizeText(value).toLowerCase()
  return NOTE_COLORS.indexOf(s) !== -1 ? s : ""
}
// Plain-text rendering of a note for clipboard copy: body only, never the
// headline (titles are labels, not content).
function copyText(note) {
  if (!note || typeof note !== "object") return ""
  return String(note.body === undefined || note.body === null ? "" : note.body).replace(/\r\n/g, "\n")
}
// Sync-artifact filenames that must never be treated as peer snapshots:
// Syncthing conflict copies (`<id>.sync-conflict-<date>.json`), Dropbox
// conflict copies (`<id> (conflicted copy …).json`), and hidden files.
// Without this, a conflict file would impersonate a peer device (it ends
// in .json) and could resurrect deleted notes on merge.
function isSyncArtifact(name) {
  var s = String(name === undefined || name === null ? "" : name)
  if (s === "") return true
  var base = s.split("/").pop()
  if (base.charAt(0) === ".") return true
  var lower = base.toLowerCase()
  if (lower.indexOf(".sync-conflict-") !== -1) return true
  if (lower.indexOf("conflicted copy") !== -1) return true
  if (lower.slice(-4) === ".tmp" || lower.slice(-4) === ".bak") return true
  return false
}
// Split a note body into [{ type: "text"|"code", lang, content }] on
// triple-backtick fences. The fence remainder is the language tag (trimmed,
// max 20 chars). An unclosed fence runs to the end. Fences indented 4+
// spaces are plain text. Empty segments are dropped.
function parseSegments(body) {
  var src = String(body === undefined || body === null ? "" : body).replace(/\r\n/g, "\n")
  if (src === "") return []
  var lines = src.split("\n")
  var segs = []
  var buf = []
  var inCode = false
  var lang = ""
  function fenceOf(line) {
    var t = String(line).replace(/^\s{0,3}/, "")
    if (t.slice(0, 3) !== "```") return null
    return t.slice(3).trim().slice(0, 20)
  }
  function flush(type, content) {
    if (content !== "") segs.push({ type: type, lang: type === "code" ? lang : "", content: content })
  }
  for (var i = 0; i < lines.length; i++) {
    var f = fenceOf(lines[i])
    if (f !== null && !inCode) {
      flush("text", buf.join("\n"))
      buf = []
      inCode = true
      lang = f
    } else if (f !== null && inCode) {
      flush("code", buf.join("\n"))
      buf = []
      inCode = false
      lang = ""
    } else {
      buf.push(lines[i])
    }
  }
  flush(inCode ? "code" : "text", buf.join("\n"))
  return segs
}
// Attachments (MVP: folder-sync sidecars, metadata inline in the note).
// Per-file cap keeps every 15s sync snappy; bytes live in
// <syncDir>/.attachments/<noteId>/<attId>-<name>, never in JSON.
var MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

// Basename only, traversal-proof: strips directories, whitelists chars,
// never leading-dot, max 100 chars. "" = unusable, caller must reject.
function sanitizeFileName(name) {
  var s = String(name === undefined || name === null ? "" : name)
  s = s.split("/").pop().split("\\").pop()
  s = s.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^\.+/, "").slice(0, 100)
  if (s === "" || s === "." || s === "..") return ""
  return s
}

function attachmentKindFor(name) {
  var ext = String(name || "").split(".").pop().toLowerCase()
  var images = { png: 1, jpg: 1, jpeg: 1, gif: 1, webp: 1, bmp: 1, svg: 1 }
  var texts = {
    txt: 1, md: 1, markdown: 1, log: 1, json: 1, js: 1, mjs: 1, ts: 1,
    qml: 1, sh: 1, py: 1, rb: 1, java: 1, c: 1, h: 1, cpp: 1, hpp: 1,
    rs: 1, go: 1, css: 1, html: 1, htm: 1, xml: 1, yml: 1, yaml: 1,
    toml: 1, ini: 1, cfg: 1, conf: 1, csv: 1, tsv: 1, diff: 1, patch: 1,
    tex: 1, vue: 1
  }
  if (images[ext]) return "image"
  if (texts[ext]) return "text"
  return "file"
}

function mimeForName(name) {
  var ext = String(name || "").split(".").pop().toLowerCase()
  if (attachmentKindFor(name) === "image") return "image/" + (ext === "svg" ? "svg+xml" : (ext === "jpg" ? "jpeg" : ext))
  if (attachmentKindFor(name) === "text") return "text/plain"
  return "application/octet-stream"
}

// Strict receipt validation: recomputes mime/kind, never trusts them.
// Returns a clean record or null.
function sanitizeAttachment(raw) {
  if (!raw || typeof raw !== "object") return null
  var id = isSafeId(raw.id) ? normalizeText(raw.id) : ""
  var name = sanitizeFileName(raw.name)
  var size = Math.floor(Number(raw.size))
  var sha = normalizeText(raw.sha256).toLowerCase()
  if (id === "" || name === "") return null
  if (!isFinite(size) || size < 0 || size > MAX_ATTACHMENT_BYTES) return null
  if (!/^[0-9a-f]{64}$/.test(sha)) return null
  return { id: id, name: name, size: size, sha256: sha, mime: mimeForName(name), kind: attachmentKindFor(name) }
}

// Local construction after hashing. Null when unusable (caller messages).
// Pass the pre-generated attId so concurrent panel runs can match their
// own completion; falls back to a fresh uid when omitted.
function createAttachment(name, size, sha256, id) {
  var clean = sanitizeFileName(name)
  var s = Math.floor(Number(size))
  var sha = normalizeText(sha256).toLowerCase()
  var attId = normalizeText(id) !== "" ? (isSafeId(id) ? normalizeText(id) : "") : uid("att")
  if (attId === "" || clean === "" || !isFinite(s) || s < 0 || s > MAX_ATTACHMENT_BYTES) return null
  if (!/^[0-9a-f]{64}$/.test(sha)) return null
  return { id: attId, name: clean, size: s, sha256: sha, mime: mimeForName(clean), kind: attachmentKindFor(clean) }
}

// Extensions the panel will save but never Open (save-only + notice).
function isRiskyExecutable(name) {
  var ext = String(name || "").split(".").pop().toLowerCase()
  return { sh: 1, exe: 1, bin: 1, run: 1, appimage: 1, deb: 1, rpm: 1, bat: 1, cmd: 1, ps1: 1, com: 1, scr: 1, msi: 1 }[ext] === 1
}
// Friends file (managed in the panel UI, no terminal needed):
// { version: 1, friends: [{ hex, name }] }. Accepts the raw file text,
// the parsed object, or an already-clean array (idempotent).
function sanitizeFriends(raw) {
  var out = []
  try {
    var parsed = typeof raw === "string" ? JSON.parse(raw || "") : (raw || {})
    var arr = parsed && Array.isArray(parsed.friends) ? parsed.friends : (Array.isArray(parsed) ? parsed : [])
    var seen = Object.create(null)
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
  var seen = Object.create(null)
  var out = []
  hexRecipients(allowList).forEach(function (h) { if (!seen[h]) { seen[h] = true; out.push(h) } })
  sanitizeFriends(friends).forEach(function (f) { if (!seen[f.hex]) { seen[f.hex] = true; out.push(f.hex) } })
  return out
}

// Convert `fetch --out` JSON into internal { notes, pairs, deleted }.
// fetch output: { notes:[{id,title,body,authorHex,updatedAt,eventId}],
//                 pairs:[{noteId,comment:{id,author,text,createdAt}}],
//                 deleted:[{noteId,eventId,author}] }.
// Returned notes are marked shared=true and carry the hex author so the
// normal allow-list filter applies. Unknown authors are dropped unless
// they are myHex itself (second device of the same user).
// Received deletions retain their signed author and stay separate from
// locally authored tombstones: they must never be re-signed by this device.
function sanitizeNostrDeleted(raw) {
  var byId = Object.create(null)
  ;(Array.isArray(raw) ? raw : []).forEach(function (entry) {
    if (!entry || typeof entry !== "object") return
    var id = normalizeText(entry.noteId)
    var author = normalizePubkey(entry.author)
    var key = nostrNoteId(author, id)
    if (key === "") return
    var deletedAt = nostrTimestamp(entry.deletedAt || nowIso())
    if (!byId[key] || deletedAt > byId[key].deletedAt)
      byId[key] = { noteId: id, author: author, deletedAt: deletedAt }
  })
  return Object.keys(byId).map(function (key) { return byId[key] })
}

function sanitizeNostrFetch(raw, allowList, myHex, knownDeleted, knownNostrDeleted, localNotes) {
  var notes = []
  var pairs = []
  var me = normalizePubkey(myHex)
  var localIds = Object.create(null)
  ;(Array.isArray(localNotes) ? localNotes : []).forEach(function (n) {
    if (n && isSafeId(n.id)) localIds[n.id] = true
  })
  // Keep already accepted state even before identity/friends load or if the
  // latest fetch is malformed. Only new arrivals need current qualification.
  var deleted = sanitizeNostrDeleted(knownNostrDeleted)
  try {
    var parsed = typeof raw === "string" ? JSON.parse(raw || "") : (raw || {})
    var arr = parsed && Array.isArray(parsed.notes) ? parsed.notes : []
    for (var i = 0; i < arr.length; i++) {
      var n = arr[i]
      if (!n || typeof n !== "object") continue
      var author = normalizePubkey(n.authorHex || n.author)
      if (author === "" || !(author === me || isQualified(author, allowList))) continue
      var id = nostrNoteId(author, n.id)
      if (id === "") continue
      var clean = sanitizeNote({ id: id, title: n.title, body: n.body, author: author,
        createdAt: nostrTimestamp(n.createdAt || n.updatedAt),
        updatedAt: nostrTimestamp(n.updatedAt || n.createdAt), shared: true })
      if (clean) notes.push(clean)
    }
    var rawPairs = parsed && Array.isArray(parsed.pairs) ? parsed.pairs : []
    for (var j = 0; j < rawPairs.length; j++) {
      var e = rawPairs[j]
      if (!e || !e.comment) continue
      var ca = normalizePubkey(e.comment.author)
      if (ca === "" || !(ca === me || isQualified(ca, allowList))) continue
      var target = normalizePubkey(e.noteAuthor)
      var targetId = nostrNoteId(target, e.noteId)
      // An ownerless legacy comment cannot be routed without allowing a
      // second author to hijack its target by reusing the same wire ID.
      if (targetId === "" || !(target === me || isQualified(target, allowList))) continue
      var ref = normalizeText(e.comment.id)
      if (!isSafeId(ref)) continue
      var sc = sanitizeComment({ id: "nostr-comment:" + ca + ":" + ref,
        author: ca, text: e.comment.text, createdAt: nostrTimestamp(e.comment.createdAt) })
      if (sc) pairs.push({ noteId: targetId, comment: sc })
    }
    var rawDeleted = parsed && Array.isArray(parsed.deleted) ? parsed.deleted : []
    for (var d = 0; d < rawDeleted.length; d++) {
      var del = rawDeleted[d]
      if (!del || typeof del !== "object") continue
      var da = normalizePubkey(del.author || del.authorHex)
      var wireId = normalizeText(del.noteId || del.id || del.d)
      if (nostrNoteId(da, wireId) === "" || !(da === me || isQualified(da, allowList))) continue
      deleted.push({ noteId: wireId, author: da, deletedAt: del.deletedAt || nowIso() })
    }
  } catch (e) { /* ignore bad fetch file */ }
  deleted = sanitizeNostrDeleted(deleted)
  var tomb = sanitizeDeleted(knownDeleted)
  var remoteTomb = Object.create(null)
  deleted.forEach(function (entry) { remoteTomb[nostrNoteId(entry.author, entry.noteId)] = entry.deletedAt })
  var notesById = Object.create(null)
  notes.forEach(function (n) {
    var prev = notesById[n.id]
    if (!prev || n.updatedAt > prev.updatedAt || (n.updatedAt === prev.updatedAt &&
        JSON.stringify(n) < JSON.stringify(prev))) notesById[n.id] = n
  })
  function locallyDeleted(id) {
    var target = splitNostrNoteId(id)
    return isDeleted(tomb, id) || (target && target.author === me && isDeleted(tomb, target.noteId))
  }
  function remotelyDeleted(id) {
    var stamp = remoteTomb[id]
    // A strictly newer note from the same signer is an intentional reshare.
    // Stale copies and missing timestamps never override a deletion.
    return !!stamp && (!notesById[id] || notesById[id].updatedAt <= stamp)
  }
  notes = Object.keys(notesById).filter(function (id) {
    return !locallyDeleted(id) && !remotelyDeleted(id)
  }).map(function (id) { return notesById[id] })
  pairs = dedupNostrPairs(pairs).filter(function (p) {
    return !locallyDeleted(p.noteId) && !remotelyDeleted(p.noteId)
  }).map(function (p) {
    var target = splitNostrNoteId(p.noteId)
    // Only the target's authenticated pubkey can alias a locally authored
    // note. LAN names and another signer's same wire ID never authorize it.
    if (target.author === me && localIds[target.noteId]) p.noteId = target.noteId
    return p
  })
  return { notes: notes, pairs: pairs, deleted: deleted, tombstones: tomb, nostrTombstones: deleted }
}

// 64-hex ids are Nostr event ids (legacy relay duplicates); anything
// else is a stable outbox id (e.g. "c-...").
function isEventId(value) {
  var raw = normalizeText(value).replace(/^nostr-comment:[0-9a-f]{64}:/, "")
  return /^[0-9a-fA-F]{64}$/.test(raw)
}

function dedupNostrPairs(pairs) {
  var groups = Object.create(null)
  var order = []
  for (var i = 0; i < pairs.length; i++) {
    var p = pairs[i]
    if (!p || !p.comment) continue
    var key = p.noteId + "\0" + p.comment.author + "\0" + p.comment.text
    if (!groups[key]) { groups[key] = []; order.push(key) }
    groups[key].push(p)
  }
  var out = []
  for (var g = 0; g < order.length; g++) {
    var entries = groups[order[g]]
    var stable = []
    var seenStable = Object.create(null)
    var legacy = []
    for (var j = 0; j < entries.length; j++) {
      var id = entries[j].comment.id
      if (isEventId(id)) {
        legacy.push(entries[j])
      } else if (!seenStable[id]) {
        seenStable[id] = true
        stable.push(entries[j])
      }
    }
    if (stable.length > 0) {
      // Stable copies win; legacy shadows of the same text are dropped.
      out = out.concat(stable)
    } else if (legacy.length > 0) {
      // No stable copy yet: show the earliest legacy copy only.
      legacy.sort(function (a, b) { return a.comment.createdAt < b.comment.createdAt ? -1 : 1 })
      out.push(legacy[0])
    }
  }
  return out
}

// Build publish.json for `sync.mjs publish` from shared local notes +
// outbox comments + deletion tombstones pending upload.
// sync.mjs encrypts one copy per --recipients pubkey. `pendingDeletes`
// is an array of noteIds deleted since the last successful publish;
// when omitted, all tombstones are queued (safe, idempotent).
function buildNostrPublish(localNotes, outbox, deletedMap, pendingDeletes, myHex) {
  var notes = []
  var comments = []
  ;(Array.isArray(localNotes) ? localNotes : []).forEach(function (n) {
    if (!n || n.shared !== true) return
    var clean = sanitizeNote(n)
    if (!clean || !isSafeId(clean.id)) return
    notes.push({ ref: clean.id, d: clean.id, title: clean.title, body: clean.body, updatedAt: clean.updatedAt })
  })
  sanitizeOutbox(outbox).forEach(function (entry) {
    var target = splitNostrNoteId(entry.noteId)
    if (!target) return // LAN-only or ambiguous legacy target: never send to Nostr.
    comments.push({ ref: entry.comment.id, noteD: target.noteId, noteAuthor: target.author, text: entry.comment.text })
  })
  var tomb = sanitizeDeleted(deletedMap)
  var queue = Array.isArray(pendingDeletes)
    ? pendingDeletes.map(sanitizeId).filter(function (id) { return id !== "" && !!tomb[id] })
    : Object.keys(tomb)
  var me = normalizePubkey(myHex)
  var deletes = []
  queue.forEach(function (id) {
    var target = splitNostrNoteId(id)
    if (target && (me === "" || target.author !== me)) return
    deletes.push({ ref: "del-" + id, noteId: target ? target.noteId : id, deletedAt: tomb[id] })
  })
  return { notes: notes, comments: comments, deletes: deletes }
}

if (typeof module !== "undefined") {
  // Node test seam: every function the panel calls as Store.<fn>, plus the
  // pure helpers covered by tests/*.py. Internal-only helpers (used solely
  // inside this file) are intentionally NOT exported.
  module.exports = {
    nowIso: nowIso,
    uid: uid,
    normalizeText: normalizeText,
    isSafeId: isSafeId,
    parseAllowList: parseAllowList,
    sanitizeSetupBackup: sanitizeSetupBackup,
    isHexPubkey: isHexPubkey,
    normalizePubkey: normalizePubkey,
    nostrNoteId: nostrNoteId,
    splitNostrNoteId: splitNostrNoteId,
    nostrReshareTimestamp: nostrReshareTimestamp,
    isQualified: isQualified,
    createNote: createNote,
    createComment: createComment,
    sanitizeNote: sanitizeNote,
    sanitizeOutbox: sanitizeOutbox,
    mergeForeignComments: mergeForeignComments,
    pruneOutbox: pruneOutbox,
    previewBody: previewBody,
    parseSegments: parseSegments,
    sanitizeAttachment: sanitizeAttachment,
    createAttachment: createAttachment,
    sanitizeFileName: sanitizeFileName,
    isRiskyExecutable: isRiskyExecutable,
    MAX_ATTACHMENT_BYTES: MAX_ATTACHMENT_BYTES,
    copyText: copyText,
    isSyncArtifact: isSyncArtifact,
    sanitizeFriends: sanitizeFriends,
    effectiveNostrAllow: effectiveNostrAllow,
    sanitizeNostrFetch: sanitizeNostrFetch,
    buildNostrPublish: buildNostrPublish,
    sanitizeDeleted: sanitizeDeleted,
    sanitizeHidden: sanitizeHidden,
    addTombstone: addTombstone,
    mergeDeleted: mergeDeleted,
    isDeleted: isDeleted,
    filterDeletedNotes: filterDeletedNotes,
    addComment: addComment,
    setShared: setShared,
    setColor: setColor,
    sanitizeColor: sanitizeColor,
    sortNotes: sortNotes
  }
}
