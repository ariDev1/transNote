// TransNote agent presentation model.
//
// This module is intentionally pure.
// It does not read files, write files, access sync state, or modify notes.
// It only converts already-trusted TransNote state into the public agent
// representation and performs deterministic presentation filtering.

var PROTOCOL_VERSION = 1
var PUBLIC_SOURCES = ["local", "lan", "nostr"]
var MAX_PROVENANCE_IDS = 2000
var SAFE_PROVENANCE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/


function text(value) {
  if (value === undefined || value === null) return ""
  return String(value)
}


function provenanceIds(value) {
  var out = []
  var seen = {}
  var input = Array.isArray(value) ? value : []

  for (var i = 0; i < input.length; i++) {
    var id = text(input[i]).trim()
    if (!SAFE_PROVENANCE_ID_RE.test(id) || seen[id]) continue

    seen[id] = true
    out.push(id)

    if (out.length >= MAX_PROVENANCE_IDS) break
  }

  return out
}


function sanitizeProvenance(raw) {
  var source = raw && typeof raw === "object" ? raw : {}

  return {
    notes: provenanceIds(source.notes),
    comments: provenanceIds(source.comments)
  }
}


function markProvenance(raw, kind, id) {
  var clean = sanitizeProvenance(raw)
  var candidate = provenanceIds([id])

  if (candidate.length === 0) return clean

  var key = kind === "note"
    ? "notes"
    : (kind === "comment" ? "comments" : "")

  if (key === "") return clean

  if (clean[key].indexOf(candidate[0]) === -1) {
    clean[key].unshift(candidate[0])

    if (clean[key].length > MAX_PROVENANCE_IDS) {
      clean[key] = clean[key].slice(0, MAX_PROVENANCE_IDS)
    }
  }

  return clean
}


function hasProvenance(raw, kind, id) {
  var clean = sanitizeProvenance(raw)
  var candidate = provenanceIds([id])

  if (candidate.length === 0) return false

  var list = kind === "note"
    ? clean.notes
    : (kind === "comment" ? clean.comments : [])

  return list.indexOf(candidate[0]) !== -1
}


function serializeComment(comment) {
  if (!comment || typeof comment !== "object") return null

  return {
    id: text(comment.id),
    author: text(comment.author),
    text: text(comment.text),
    createdAt: text(comment.createdAt)
  }
}


function serializeNote(note, source) {
  if (!note || typeof note !== "object") return null
  if (PUBLIC_SOURCES.indexOf(source) === -1) return null

  var comments = []
  var rawComments = Array.isArray(note.comments) ? note.comments : []

  for (var i = 0; i < rawComments.length; i++) {
    var clean = serializeComment(rawComments[i])
    if (clean) comments.push(clean)
  }

  return {
    id: text(note.id),
    title: text(note.title),
    body: text(note.body),
    author: text(note.author),
    createdAt: text(note.createdAt),
    updatedAt: text(note.updatedAt),
    shared: note.shared === true,
    source: source,
    comments: comments
  }
}


function searchNotes(notes, query) {
  if (!Array.isArray(notes)) return []

  var needle = text(query).trim().toLowerCase()
  if (needle === "") return []

  return notes.filter(function (note) {
    if (!note || typeof note !== "object") return false

    var title = text(note.title).toLowerCase()
    var body = text(note.body).toLowerCase()

    return title.indexOf(needle) !== -1
      || body.indexOf(needle) !== -1
  })
}


function capabilities() {
  return {
    commands: {
      status: {
        mutates: false,
        arguments: [],
        errors: []
      },
      capabilities: {
        mutates: false,
        arguments: [],
        errors: []
      },
      list: {
        mutates: false,
        arguments: [],
        errors: [
          "TRANSNOTE_NOT_READY"
        ]
      },
      get: {
        mutates: false,
        arguments: [{
          name: "noteId",
          kind: "positional",
          required: true,
          nonEmpty: true
        }],
        errors: [
          "TRANSNOTE_NOT_READY",
          "NOTE_NOT_FOUND"
        ]
      },
      search: {
        mutates: false,
        arguments: [{
          name: "query",
          kind: "positional",
          required: true,
          nonEmpty: true
        }],
        errors: [
          "TRANSNOTE_NOT_READY",
          "INVALID_ARGUMENT"
        ]
      },
      create: {
        mutates: true,
        arguments: [{
          name: "title",
          kind: "option",
          flag: "--title",
          required: false
        }, {
          name: "body",
          kind: "option",
          flag: "--body",
          required: false
        }],
        constraints: [{
          kind: "atLeastOneNonEmpty",
          arguments: ["title", "body"]
        }],
        errors: [
          "TRANSNOTE_NOT_READY",
          "EMPTY_NOTE"
        ]
      },
      comment: {
        mutates: true,
        arguments: [{
          name: "noteId",
          kind: "positional",
          required: true,
          nonEmpty: true
        }, {
          name: "text",
          kind: "option",
          flag: "--text",
          required: true,
          nonEmpty: true
        }],
        errors: [
          "TRANSNOTE_NOT_READY",
          "NOTE_NOT_FOUND",
          "EMPTY_COMMENT"
        ]
      }
    },
    errorExitCodes: {
      MISSING_ARGUMENT: 2,
      INVALID_ARGUMENT: 2,
      UNKNOWN_OPTION: 2,
      UNKNOWN_COMMAND: 2,
      EMPTY_NOTE: 2,
      EMPTY_COMMENT: 2,
      TRANSNOTE_NOT_READY: 3,
      TRANSNOTE_UNAVAILABLE: 3,
      NOTE_NOT_FOUND: 4,
      PROTOCOL_ERROR: 5
    },
    unsupported: [
      "delete",
      "share",
      "unshare",
      "hide",
      "pairing",
      "syncAdministration",
      "attachmentMutation",
      "filesystemAccess",
      "commandForwarding",
      "identityOverride"
    ]
  }
}


if (typeof module !== "undefined") {
  module.exports = {
    PROTOCOL_VERSION: PROTOCOL_VERSION,
    capabilities: capabilities,
    sanitizeProvenance: sanitizeProvenance,
    markProvenance: markProvenance,
    hasProvenance: hasProvenance,
    serializeComment: serializeComment,
    serializeNote: serializeNote,
    searchNotes: searchNotes
  }
}
