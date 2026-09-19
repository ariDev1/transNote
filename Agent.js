// TransNote agent presentation model.
//
// This module is intentionally pure.
// It does not read files, write files, access sync state, or modify notes.
// It only converts already-trusted TransNote state into the public agent
// representation and performs deterministic presentation filtering.

var PROTOCOL_VERSION = 1
var PUBLIC_SOURCES = ["local", "lan", "nostr"]


function text(value) {
  if (value === undefined || value === null) return ""
  return String(value)
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


if (typeof module !== "undefined") {
  module.exports = {
    PROTOCOL_VERSION: PROTOCOL_VERSION,
    serializeComment: serializeComment,
    serializeNote: serializeNote,
    searchNotes: searchNotes
  }
}
