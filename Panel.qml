import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Store.js" as Store

// TransNote: fast shared text notes.
// - Many notes, each with comments.
// - Own snapshot syncs through a shared folder (Syncthing/Dropbox/rsync).
// - Only peers on your allow-list can read your shared notes / comment.
// - Attachments: schema-reserved (`attachments: []`), UI placeholder only.
Panel {
  id: root
  moduleName: "rene.transnote"
  ipcTarget: "rene.transnote"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---------------------------------------------------------- settings
  // setting() is inherited from the qs.Ui Panel base (reads this widget's
  // inline shell.json entry with fallback).
  property string deviceIdSetting: String(setting("deviceId", ""))
  property string syncDirSetting: String(setting("syncDir", ""))
  property string allowListSetting: String(setting("allowList", ""))

  property string detectedHostname: ""
  readonly property string myId: {
    var s = Store.normalizeText(deviceIdSetting)
    if (s !== "") return s
    if (detectedHostname !== "") return detectedHostname
    return "local"
  }
  readonly property var allowList: Store.parseAllowList(allowListSetting)
  readonly property string syncDir: {
    var d = Store.normalizeText(syncDirSetting)
    if (d === "") return ""
    if (d[0] === "~") return (Quickshell.env("HOME") || "") + d.slice(1)
    return d
  }
  readonly property bool syncConfigured: syncDir !== ""
  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string dataDir: (Quickshell.env("XDG_DATA_HOME") || home + "/.local/share") + "/transnote"
  readonly property string notesPath: dataDir + "/notes.json"
  readonly property string syncSnapshotPath: syncConfigured ? syncDir + "/" + myId + ".json" : ""
  // Internet (Nostr) sync files in the private data dir. The panel runs
  // nostr/sync.mjs itself (no terminal needed): it writes
  // nostr_publish.json for upload and reads nostr_fetch.json for downloads.
  readonly property string nostrFetchPath: dataDir + "/nostr_fetch.json"
  readonly property string nostrPublishPath: dataDir + "/nostr_publish.json"
  readonly property string friendsPath: dataDir + "/friends.json"
  readonly property string keyFile: dataDir + "/nostr_key"
  // Folder this Panel.qml lives in — the plugin dir, wherever it is
  // installed. Used to find nostr/sync.mjs without hardcoding paths.
  readonly property string pluginDir: {
    var u = String(Qt.resolvedUrl("./"))
    if (u.indexOf("file://") === 0) u = u.slice(7)
    if (u.length > 1 && u[u.length - 1] === "/") u = u.slice(0, -1)
    return u
  }
  readonly property string syncScript: pluginDir + "/nostr/sync.mjs"
  readonly property string relays: "wss://relay.damus.io,wss://nos.lol,wss://relay.nostr.band"
  property string myHex: ""
  property string myNpub: ""
  property string nostrFetchRaw: ""
  // Shown subtly in the footer so you can check you're on the latest
  // version. Read from manifest.json (single source of truth).
  property string pluginVersion: ""
  // Internet sync state machine: init → findnode → depcheck → depinstall →
  // key → ready. "node-missing" / "depfailed" show a plain-language error.
  property string setupStage: "init"
  property int nodeCandidate: 0
  property string nodeBin: ""
  property string npmBin: "npm"
  property string netStatus: ""
  property bool syncRunning: false
  // Friends added in the UI (hex + name). Merged with the allowList setting
  // for internet filtering — nobody edits config files by hand.
  property var friends: []
  property string friendInput: ""
  property string friendName: ""
  property string friendError: ""
  property string copyNote: ""
  property bool wlCopyOk: false
  // Visible section of the panel (the card is capped at 520px with no
  // scrolling, so Notes and Share take turns instead of stacking).
  property string panelView: "notes"
  // Folder-sync setup wizard (no terminal): drafts for the three widget
  // settings. Saved through the official `omarchy bar set` writer, so the
  // shell persists + hot-reloads them safely — the panel never edits
  // shell.json itself.
  property string setupDevice: ""
  property string setupDir: ""
  property string setupPeers: ""
  property string setupMessage: ""
  property bool setupSaving: false
  readonly property string omarchyBin: (Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/bin/omarchy"
  function openSetup() {
    setupDevice = myId
    setupDir = Store.normalizeText(syncDirSetting) !== "" ? Store.normalizeText(syncDirSetting) : "~/transnote-lan"
    setupPeers = Store.normalizeText(allowListSetting)
    if (setupDeviceField) setupDeviceField.text = setupDevice
    if (setupDirField) setupDirField.text = setupDir
    if (setupPeersField) setupPeersField.text = setupPeers
    setupMessage = ""
    panelView = "setup"
    checkSetupFolder()
  }
  function expandSetupDir(path) {
    var d = Store.normalizeText(path)
    if (d === "") return ""
    if (d[0] === "~") return (home || "") + d.slice(1)
    return d
  }
  function saveSetupDevice() {
    var v = Store.normalizeText(setupDevice)
    if (v === "") { setupMessage = "Give this machine a name first (e.g. laptop)."; return }
    setupSaving = true
    setupMessage = "Saving name…"
    barSetDevice.command = [omarchyBin, "bar", "set", "rene.transnote", "deviceId", v]
    barSetDevice.running = true
  }
  function saveSetupDir() {
    var v = Store.normalizeText(setupDir)
    if (v === "") { setupMessage = "Enter a folder first (e.g. ~/transnote-lan)."; return }
    setupSaving = true
    setupMessage = "Saving folder…"
    barSetDir.command = [omarchyBin, "bar", "set", "rene.transnote", "syncDir", v]
    barSetDir.running = true
  }
  function saveSetupPeers() {
    setupSaving = true
    setupMessage = "Saving sharing list…"
    barSetPeers.command = [omarchyBin, "bar", "set", "rene.transnote", "allowList", Store.normalizeText(setupPeers)]
    barSetPeers.running = true
  }
  function createSetupFolder() {
    var dir = expandSetupDir(setupDir)
    if (dir === "") { setupMessage = "Enter a folder first (e.g. ~/transnote-lan)."; return }
    setupMessage = "Creating folder…"
    folderCreate.command = ["mkdir", "-p", dir]
    folderCreate.running = true
  }
  function checkSetupFolder() {
    var dir = expandSetupDir(setupDir)
    if (dir === "") return
    folderCheck.command = ["bash", "-c", "test -d " + shellQuote(dir) + " && test -w " + shellQuote(dir)]
    folderCheck.running = true
  }
  function onBarSetDone(key, exitCode) {
    setupSaving = false
    if (exitCode === 0) {
      if (key === "folder") checkSetupFolder()
      setupMessage = "Saved — the bar picks it up by itself."
    } else {
      setupMessage = "Couldn't save — try again."
    }
  }
  readonly property var nostrAllowList: {
    var base = (allowList || []).slice()
    ;(friends || []).forEach(function (f) { if (f && f.hex) base.push(f.hex) })
    return base
  }

  // -------------------------------------------------------------- state
  property var localNotes: []   // notes authored here (persisted locally)
  property var peerNotes: []    // merged shared notes from folder peers
  property var nostrPeerNotes: [] // shared notes from internet (Nostr fetch)
  property var displayNotes: [] // sorted union shown in the panel
  // My comments on peers' notes, published in my snapshot so their authors
  // merge them in: [{ noteId, comment }]. Persisted in the local file.
  property var outbox: []
  // Peers' comments on notes I display, merged from their snapshots:
  // { noteId: [comment] }.
  property var foreignComments: ({})
  property string syncStatus: ""
  property string selectedNoteId: ""
  // Notes expanded to full body text (map noteId -> true). Collapsed notes
  // show a short preview so one long note never takes over the list.
  property var expandedNotes: ({})

  function isExpanded(noteId) {
    return !!(expandedNotes && expandedNotes[noteId] === true)
  }

  function toggleExpanded(noteId) {
    var next = {}
    for (var k in expandedNotes) next[k] = expandedNotes[k]
    next[noteId] = !isExpanded(noteId)
    expandedNotes = next
  }
  property string newTitle: ""
  property string newBody: ""
  property var commentDrafts: ({})
  property var peerFiles: []

  function refreshDisplay() {
    var union = (localNotes || []).concat(peerNotes || []).concat(nostrPeerNotes || [])
    displayNotes = Store.sortNotes(union.filter(function (n) { return !!n }))
  }

  function allPeerNotes() {
    return (peerNotes || []).concat(nostrPeerNotes || [])
  }

  function mergePeers() {
    // peerNotes already holds only qualified, shared notes (filtered when
    // each snapshot loads). Rebuild the union defensively anyway.
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var fresh = (peerNotes || []).filter(function (n) { return n && !mine[n.id] })
    peerNotes = fresh
    var freshNostr = (nostrPeerNotes || []).filter(function (n) { return n && !mine[n.id] })
    nostrPeerNotes = freshNostr
    refreshDisplay()
  }

  function commentsFor(noteId) {
    var own = []
    var all = (localNotes || []).concat(peerNotes || []).concat(nostrPeerNotes || [])
    for (var i = 0; i < all.length; i++) {
      if (all[i] && all[i].id === noteId && Array.isArray(all[i].comments)) { own = all[i].comments; break }
    }
    var foreign = (foreignComments && foreignComments[noteId]) || []
    return own.concat(foreign)
  }

  // ------------------------------------------------- privacy lockdown
  // Notes are private: only this user may read them. The data dir and all
  // plugin files (notes, friends, key, sync queue, decrypted downloads, and
  // the folder-sync snapshot) are locked to owner-only on every save, so a
  // colleague with an account on the same machine cannot read them.
  // (The sync folder itself must also stay non-shared — see README.)
  function secureFiles() {
    if (!secureProcess.running) {
      var files = [notesPath, friendsPath, keyFile, nostrPublishPath, nostrFetchPath]
      if (syncSnapshotPath !== "") files.push(syncSnapshotPath)
      secureProcess.command = ["bash", "-c",
        "chmod 700 " + shellQuote(dataDir) + " 2>/dev/null; chmod 600 "
        + files.map(shellQuote).join(" ") + " 2>/dev/null; true"]
      secureProcess.running = true
    }
  }

  // ------------------------------------------------------------ persist
  function persist() {
    var payload = JSON.stringify({ version: 1, deviceId: myId, notes: localNotes, outbox: outbox }, null, 2) + "\n"
    localFile.setText(payload)
    if (syncConfigured) {
      var shared = localNotes.filter(function (n) { return n && n.shared === true })
      var snapshot = JSON.stringify({ version: 1, deviceId: myId, updatedAt: Store.nowIso(), notes: shared, noteComments: outbox }, null, 2) + "\n"
      syncSnapshotFile.setText(snapshot)
    }
    // Internet publish queue for the built-in sync: shared notes + outbox
    // comments. sync.mjs encrypts one copy per --recipients pubkey on publish.
    var job = Store.buildNostrPublish(localNotes, outbox)
    nostrPublishFile.setText(JSON.stringify(job, null, 2) + "\n")
    refreshDisplay()
    secureFiles()
  }

  function loadLocal(raw) {
    var notes = []
    var box = []
    try {
      var parsed = JSON.parse(String(raw || ""))
      var arr = parsed && Array.isArray(parsed.notes) ? parsed.notes : (Array.isArray(parsed) ? parsed : [])
      arr.forEach(function (n) {
        var clean = Store.sanitizeNote(n)
        if (clean) notes.push(clean)
      })
      box = Store.sanitizeOutbox(parsed && parsed.outbox)
    } catch (e) { console.warn("transnote", "Ignoring bad notes file", e) }
    localNotes = notes
    outbox = box
    mergePeers()
  }

  // Returns { notes: [...], pairs: [{ noteId, comment }] }.
  function loadPeerSnapshot(raw) {
    var out = []
    var pairs = []
    try {
      var parsed = JSON.parse(String(raw || ""))
      var arr = parsed && Array.isArray(parsed.notes) ? parsed.notes : []
      arr.forEach(function (n) {
        var clean = Store.sanitizeNote(n)
        // Accept only shared notes from qualified peers — plus snapshots
        // authored by myId itself (a second device of the same user).
        if (clean && clean.shared === true
            && (clean.author === root.myId || Store.isQualified(clean.author, allowList))) out.push(clean)
      })
      pairs = Store.sanitizeOutbox(parsed && parsed.noteComments)
    } catch (e) { /* ignore bad peer files */ }
    return { notes: out, pairs: pairs }
  }

  function rebuildPeerNotes() {
    var all = []
    var pairs = []
    for (var i = 0; i < peerInstantiator.count; i++) {
      var obj = peerInstantiator.objectAt(i)
      if (obj && obj.snapshot) {
        all = all.concat(obj.snapshot.notes)
        pairs = pairs.concat(obj.snapshot.pairs)
      }
    }
    // De-duplicate by note id, newest first; drop notes I authored (mine win).
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var byId = {}
    all.forEach(function (n) {
      if (!n || mine[n.id]) return
      if (!byId[n.id] || n.updatedAt > byId[n.id].updatedAt) byId[n.id] = n
    })
    peerNotes = Object.keys(byId).map(function (k) { return byId[k] })
    foreignComments = Store.mergeForeignComments(foreignComments, pairs, allowList, myId)
    var pruned = Store.pruneOutbox(outbox, localNotes, allPeerNotes())
    if (JSON.stringify(pruned) !== JSON.stringify(outbox)) {
      outbox = pruned
      persist()
      return
    }
    refreshDisplay()
  }

  // Internet fetch output (written by the built-in sync, read back here).
  // Already decrypted + author-filtered by sync.mjs; re-filter here too so
  // removing someone hides them immediately.
  function loadNostrFetch(raw) {
    root.nostrFetchRaw = String(raw || "")
    var parsed = Store.sanitizeNostrFetch(root.nostrFetchRaw, nostrAllowList, root.myHex)
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var folderIds = {}
    ;(peerNotes || []).forEach(function (n) { if (n) folderIds[n.id] = true })
    var fresh = parsed.notes.filter(function (n) { return n && !mine[n.id] && !folderIds[n.id] })
    nostrPeerNotes = fresh
    // Accept comments from hex-self too (second device of same user).
    var allowWithSelf = (allowList || []).concat(root.myHex ? [root.myHex] : [])
    foreignComments = Store.mergeForeignComments(foreignComments, parsed.pairs, allowWithSelf, myId)
    var pruned = Store.pruneOutbox(outbox, localNotes, allPeerNotes())
    if (JSON.stringify(pruned) !== JSON.stringify(outbox)) {
      outbox = pruned
      persist()
      return
    }
    refreshDisplay()
  }

  function refilterNostr() {
    if (root.nostrFetchRaw !== "") loadNostrFetch(root.nostrFetchRaw)
  }

  // ------------------------------------------------- internet self-setup
  // Everything here runs through background processes — the user never
  // touches a terminal. Stages: findnode → depcheck → depinstall → key.
  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'"
  }

  function nodeCandidates() {
    return ["node", home + "/.local/share/mise/shims/node", "/usr/bin/node", "/usr/local/bin/node", home + "/.local/bin/node"]
  }

  function updateNetStatus() {
    if (setupStage === "findnode" || setupStage === "depcheck" || setupStage === "depinstall" || setupStage === "key") {
      netStatus = "Internet: setting up…"
    } else if (setupStage === "node-missing") {
      netStatus = "Internet: off — needs Node.js installed"
      setupRetry.restart()
    } else if (setupStage === "depfailed") {
      netStatus = "Internet: setup failed (no connection?) — retrying"
      setupRetry.restart()
    } else if (syncRunning) {
      netStatus = "Internet: syncing…"
    } else {
      var n = Store.effectiveNostrAllow(allowList, friends).length
      if (n === 0) netStatus = "Internet: on — add a friend below to share"
      else netStatus = "Internet: on (" + n + (n === 1 ? " friend)" : " friends)")
    }
  }

  function setupStep() {
    updateNetStatus()
    if (setupStage === "findnode") {
      var cands = nodeCandidates()
      if (nodeCandidate >= cands.length) {
        setupStage = "node-missing"
        updateNetStatus()
        return
      }
      nodeProbe.command = [cands[nodeCandidate], "--version"]
      nodeProbe.running = true
    } else if (setupStage === "depcheck") {
      depCheck.command = ["bash", "-c", "test -f " + shellQuote(pluginDir + "/node_modules/nostr-tools/package.json")]
      depCheck.running = true
    } else if (setupStage === "depinstall") {
      netStatus = "Internet: downloading sync helper (once)…"
      depInstall.command = [npmBin, "install", "--prefix", pluginDir, "--no-audit", "--no-fund"]
      depInstall.running = true
    } else if (setupStage === "key") {
      keyProcess.command = [nodeBin, syncScript, "ensure-key", "--key-file", keyFile]
      keyProcess.running = true
    } else if (setupStage === "ready") {
      updateNetStatus()
      refilterNostr()
      syncTimer.start()
    }
  }

  function onNodeProbe(exitCode) {
    if (exitCode === 0) {
      nodeBin = nodeCandidates()[nodeCandidate]
      npmBin = nodeBin.indexOf("/") >= 0 ? nodeBin.replace(/\/node$/, "/npm") : "npm"
      setupStage = "depcheck"
    } else {
      nodeCandidate++
    }
    setupStep()
  }

  function onKeyOutput(text) {
    try {
      var info = JSON.parse(String(text || ""))
      if (info && Store.isHexPubkey(info.hex)) {
        myHex = String(info.hex).toLowerCase()
        myNpub = Store.normalizeText(info.npub)
        setupStage = "ready"
      } else {
        setupStage = "depfailed"
      }
    } catch (e) {
      setupStage = "depfailed"
    }
    setupStep()
  }

  // ------------------------------------------------------- friends (UI)
  function loadFriends(raw) {
    friends = Store.sanitizeFriends(raw)
    updateNetStatus()
    refilterNostr()
  }

  function saveFriends(list) {
    var clean = Store.sanitizeFriends(list)
    friends = clean
    friendsFile.setText(JSON.stringify({ version: 1, friends: clean }, null, 2) + "\n")
    updateNetStatus()
    refilterNostr()
  }

  function addFriendFromInput() {
    friendError = ""
    var input = Store.normalizeText(friendInput)
    if (input === "") return
    if (Store.isHexPubkey(input)) {
      finishAddFriend(input.toLowerCase())
      return
    }
    if (input.indexOf("npub1") === 0) {
      npubConvert.command = [nodeBin, syncScript, "npub-to-hex", "--npub", input]
      npubConvert.running = true
      return
    }
    friendError = "That code doesn't look right — paste your friend's code starting with npub1."
  }

  function finishAddFriend(hex) {
    var clean = Store.normalizePubkey(hex)
    if (clean === "") {
      friendError = "That code doesn't look right — ask your friend to resend it."
      return
    }
    var known = false
    ;(friends || []).forEach(function (f) { if (f && f.hex === clean) known = true })
    if (known) {
      friendError = "Already in your friends."
      return
    }
    var name = Store.normalizeText(friendName).slice(0, 40) || clean.slice(0, 8)
    var next = (friends || []).concat([{ hex: clean, name: name }])
    friendInput = ""
    friendName = ""
    if (friendInputField) friendInputField.text = ""
    if (friendNameField) friendNameField.text = ""
    saveFriends(next)
  }

  function removeFriend(hex) {
    saveFriends((friends || []).filter(function (f) { return f && f.hex !== hex }))
  }

  // ------------------------------------------------------- auto-sync
  // Runs by itself every minute once set up. Uploads notes you Shared
  // (encrypted for friends only), downloads friends' notes for the list.
  function runSyncCycle() {
    if (setupStage !== "ready" || syncRunning) return
    var allow = Store.effectiveNostrAllow(allowList, friends)
    if (allow.length === 0) {
      updateNetStatus()
      return
    }
    syncRunning = true
    updateNetStatus()
    persist() // refresh the publish queue file first
    syncDelay.restart()
  }

  function startPublish() {
    var allow = Store.effectiveNostrAllow(allowList, friends)
    pubProcess.command = [nodeBin, syncScript, "publish",
      "--key-file", keyFile, "--relays", relays,
      "--in", nostrPublishPath, "--recipients", allow.join(",")]
    pubProcess.running = true
  }

  function startFetch() {
    var allow = Store.effectiveNostrAllow(allowList, friends)
    fetchProcess.command = [nodeBin, syncScript, "fetch",
      "--key-file", keyFile, "--relays", relays,
      "--allow-list", allow.join(","), "--out", nostrFetchPath]
    fetchProcess.running = true
  }

  function onFetchDone(exitCode) {
    syncRunning = false
    if (exitCode === 0) {
      var n = Store.effectiveNostrAllow(allowList, friends).length
      netStatus = "Internet: on (" + n + (n === 1 ? " friend)" : " friends)")
    } else {
      netStatus = "Internet: couldn't reach friends — will retry"
    }
    // The fetch file watcher picks up new notes by itself.
  }

  // --------------------------------------------------------------- CRUD
  function addNote() {
    if (Store.normalizeText(newTitle) === "" && Store.normalizeText(newBody) === "") return
    var note = Store.createNote(newTitle, newBody, myId)
    localNotes = [note].concat(localNotes)
    newTitle = ""
    newBody = ""
    if (noteTitleField) noteTitleField.text = ""
    if (noteBodyField) noteBodyField.text = ""
    selectedNoteId = note.id
    persist()
  }

  function deleteNote(id) {
    localNotes = localNotes.filter(function (n) { return n && n.id !== id })
    if (selectedNoteId === id) selectedNoteId = ""
    persist()
  }

  function toggleShare(id) {
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === id) {
        Store.setShared(localNotes[i], !(localNotes[i].shared === true), myId)
        touchLocalNotes()
        break
      }
    }
    persist()
  }

  function touchLocalNotes() {
    // Reassign so QML bindings update for in-place mutations.
    localNotes = localNotes.slice()
  }

  function addComment(noteId) {
    var draft = Store.normalizeText(commentDrafts[noteId])
    if (draft === "") return
    var ownNote = null
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === noteId) { ownNote = localNotes[i]; break }
    }
    if (ownNote) {
      // Comment on my own note: stored inline and shared with the note.
      Store.addComment(ownNote, myId, draft)
    } else {
      // Comment on a peer's note: queued in the outbox and published in my
      // snapshot so the note author merges it in on next sync.
      var c = Store.createComment(myId, draft)
      if (!c) return
      outbox = outbox.concat([{ noteId: noteId, comment: c }])
    }
    var drafts = {}
    for (var k in commentDrafts) drafts[k] = commentDrafts[k]
    drafts[noteId] = ""
    commentDrafts = drafts
    touchLocalNotes()
    persist()
  }

  function isQualifiedPeer(peerId) {
    return Store.isQualified(peerId, allowList)
  }

  // Hex pubkeys are 64 chars — show first 8. 🌐 marks internet (Nostr)
  // notes so users can tell them apart from local/folder notes.
  function shortAuthor(id) {
    var s = Store.normalizeText(id)
    if (Store.isHexPubkey(s)) return s.slice(0, 8)
    return s
  }

  function authorLabel(note) {
    if (!note) return ""
    if (note.author === root.myId || (root.myHex !== "" && note.author === root.myHex)) return shortAuthor(note.author) + " (you)"
    var via = Store.isHexPubkey(note.author) ? "🌐 " : ""
    return via + shortAuthor(note.author)
  }

  // ------------------------------------------------------------ storage
  Process {
    id: mkdirProcess
    running: false
    onExited: function (exitCode) {
      if (exitCode !== 0) root.syncStatus = "Could not create data dir"
      else root.secureFiles()
    }
  }

  // Fire-and-forget permission lockdown (see secureFiles()).
  Process {
    id: secureProcess
    running: false
  }

  FileView {
    id: localFile
    path: root.notesPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadLocal(text())
    onLoadFailed: { root.localNotes = []; root.refreshDisplay() }
    onFileChanged: reload()
  }

  FileView {
    id: syncSnapshotFile
    path: root.syncSnapshotPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
  }

  FileView {
    id: nostrPublishFile
    path: root.nostrPublishPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
  }

  // Own hex pubkey comes from the built-in key setup (in memory) —
  // no files to manage by hand.

  // Decrypted internet notes (written by the built-in sync). Watches for
  // changes so Austria -> USA appears without reopening the panel.
  FileView {
    path: root.nostrFetchPath
    watchChanges: true
    printErrors: false
    onLoaded: root.loadNostrFetch(text())
    onLoadFailed: { root.nostrPeerNotes = []; root.nostrFetchRaw = ""; root.refreshDisplay() }
    onFileChanged: reload()
  }

  // Friends added in the UI (name + code). Never edited by hand.
  FileView {
    id: friendsFile
    path: root.friendsPath
    watchChanges: true
    atomicWrites: true
    printErrors: false
    onLoaded: root.loadFriends(text())
    onLoadFailed: { root.friends = [] }
    onFileChanged: reload()
  }

  // ---- background workers for internet setup + sync (no terminal) ----
  Process {
    id: nodeProbe
    running: false
    onExited: function (exitCode) { root.onNodeProbe(exitCode) }
  }

  Process {
    id: depCheck
    running: false
    onExited: function (exitCode) {
      root.setupStage = exitCode === 0 ? "key" : "depinstall"
      root.setupStep()
    }
  }

  Process {
    id: depInstall
    running: false
    onExited: function (exitCode) {
      root.setupStage = exitCode === 0 ? "key" : "depfailed"
      root.setupStep()
    }
  }

  Process {
    id: keyProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.onKeyOutput(text)
    }
  }

  Process {
    id: wlProbe
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.wlCopyOk = Store.normalizeText(text) !== ""
    }
  }

  Process {
    id: copyProcess
    running: false
    onExited: function (exitCode) {
      root.copyNote = exitCode === 0 ? "Copied!" : "Copy it manually (long-press to select)"
    }
  }

  // Folder-sync setup writer: official `omarchy bar set` per key (separate
  // processes so rapid Save clicks can't overwrite each other's command).
  // The shell persists shell.json + pushes the new settings to us.
  Process {
    id: barSetDevice
    running: false
    onExited: function (exitCode) { root.onBarSetDone("device", exitCode) }
  }

  Process {
    id: barSetDir
    running: false
    onExited: function (exitCode) { root.onBarSetDone("folder", exitCode) }
  }

  Process {
    id: barSetPeers
    running: false
    onExited: function (exitCode) { root.onBarSetDone("peers", exitCode) }
  }

  Process {
    id: folderCreate
    running: false
    onExited: function (exitCode) {
      if (exitCode === 0) { root.setupMessage = "Folder ready — press Save folder."; root.checkSetupFolder() }
      else root.setupMessage = "Couldn't create that folder — check the path."
    }
  }

  Process {
    id: folderCheck
    running: false
    onExited: function (exitCode) {
      if (root.panelView !== "setup" || root.setupSaving) return
      if (root.setupMessage === "Saving name…" || root.setupMessage === "Saving folder…" || root.setupMessage === "Saving sharing list…" || root.setupMessage === "Creating folder…") return
      var dir = root.expandSetupDir(root.setupDir)
      if (dir === "") return
      root.setupMessage = exitCode === 0 ? "Folder looks good." : "Folder not found — press Create folder, then Save folder."
    }
  }

  Process {
    id: npubConvert
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var info = JSON.parse(String(text || ""))
          if (info && Store.isHexPubkey(info.hex)) root.finishAddFriend(info.hex)
          else root.friendError = "That code doesn't look right — ask your friend to resend it."
        } catch (e) {
          root.friendError = "Couldn't read that code — check it and try again."
        }
      }
    }
  }

  Process {
    id: pubProcess
    running: false
    onExited: function (exitCode) { root.startFetch() }
  }

  Process {
    id: fetchProcess
    running: false
    onExited: function (exitCode) { root.onFetchDone(exitCode) }
  }

  // Short pause so the publish file is on disk before uploading it.
  Timer {
    id: syncDelay
    interval: 800
    repeat: false
    onTriggered: root.startPublish()
  }

  // Automatic sync, every minute, once set up.
  Timer {
    id: syncTimer
    interval: 60000
    repeat: true
    running: false
    onTriggered: root.runSyncCycle()
  }

  // Retry setup a while later (e.g. first launch was offline).
  Timer {
    id: setupRetry
    interval: 120000
    repeat: false
    onTriggered: {
      if (root.setupStage !== "depfailed" && root.setupStage !== "node-missing") return
      if (root.nodeBin === "") { root.nodeCandidate = 0; root.setupStage = "findnode" }
      else root.setupStage = "depcheck"
      root.setupStep()
    }
  }

  FileView {
    path: "/etc/hostname"
    watchChanges: false
    printErrors: false
    onLoaded: root.detectedHostname = String(text() || "").trim()
  }

  // Plugin version for the subtle footer readout.
  FileView {
    path: root.pluginDir + "/manifest.json"
    watchChanges: false
    printErrors: false
    onLoaded: {
      try {
        var m = JSON.parse(String(text() || ""))
        if (m && Store.normalizeText(m.version) !== "") root.pluginVersion = Store.normalizeText(m.version)
      } catch (e) { /* keep empty */ }
    }
  }

  Process {
    id: peerListProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyPeerListing(text)
    }
  }

  function applyPeerListing(output) {
    var files = []
    var own = myId + ".json"
    String(output || "").split("\n").forEach(function (line) {
      var name = line.trim()
      if (name.slice(-5) === ".json" && name !== own) files.push(syncDir + "/" + name)
    })
    files.sort()
    if (JSON.stringify(files) !== JSON.stringify(peerFiles)) peerFiles = files
  }

  function rescanPeers() {
    if (!syncConfigured) { peerFiles = []; return }
    if (!peerListProcess.running) {
      peerListProcess.command = ["bash", "-c", "ls -1 " + syncDir + " 2>/dev/null | grep '\\.json$' || true"]
      peerListProcess.running = true
    }
  }

  Instantiator {
    id: peerInstantiator
    model: root.peerFiles
    delegate: Item {
      required property var modelData
      property var snapshot: ({ notes: [], pairs: [] })
      FileView {
        path: modelData
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
          parent.snapshot = root.loadPeerSnapshot(text())
          root.rebuildPeerNotes()
        }
        onLoadFailed: { parent.snapshot = ({ notes: [], pairs: [] }); root.rebuildPeerNotes() }
      }
    }
    onObjectAdded: root.rebuildPeerNotes()
    onObjectRemoved: root.rebuildPeerNotes()
  }

  Timer {
    id: peerPoll
    interval: 15000
    repeat: true
    running: root.syncConfigured
    onTriggered: root.rescanPeers()
  }

  Component.onCompleted: {
    mkdirProcess.command = ["mkdir", "-p", dataDir]
    mkdirProcess.running = true
    if (syncConfigured) {
      syncStatus = "Sync on: " + syncDir
      rescanPeers()
    } else {
      syncStatus = "Local only — set syncDir to share"
    }
    // Internet sets itself up in the background (node → helper → key).
    wlProbe.command = ["bash", "-c", "command -v wl-copy || true"]
    wlProbe.running = true
    setupStage = "findnode"
    nodeCandidate = 0
    setupStep()
  }

  onAllowListChanged: { root.refilterNostr(); root.updateNetStatus() }
  onMyHexChanged: { root.refilterNostr(); root.updateNetStatus() }
  onFriendsChanged: { root.refilterNostr(); root.updateNetStatus() }

  onSyncConfiguredChanged: {
    if (syncConfigured) { syncStatus = "Sync on: " + syncDir; rescanPeers() }
    else { syncStatus = "Local only — set syncDir to share"; peerFiles = [] }
  }

  // ---------------------------------------------------------------- IPC
  IpcHandler {
    target: "rene.transnote"
    function open() { root.open() }
    function close() { root.close() }
    function show() { root.open() }
    function hide() { root.close() }
    function toggle() { root.toggle() }
  }

  // -------------------------------------------------------------- bar UI
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰎚"
    onPressed: function (b) {
      if (root.opened) root.close()
      else root.open()
    }
  }

  // -------------------------------------------------------------- panel
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(480))
    contentHeight: panel.fittedContentHeight(Math.min(Style.space(600), column.implicitHeight))

    Column {
      id: column
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      spacing: Style.space(10)

      // ---- section tabs: only one view fits the card, pick one ----
      RowLayout {
        width: parent.width
        spacing: Style.space(6)
        Button {
          Layout.fillWidth: true
          text: "Notes"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          selected: root.panelView === "notes"
          onClicked: root.panelView = "notes"
        }
        Button {
          Layout.fillWidth: true
          text: "Share 🌐"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          selected: root.panelView === "share"
          onClicked: root.panelView = "share"
        }
        Button {
          Layout.fillWidth: true
          text: "Setup"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          selected: root.panelView === "setup"
          onClicked: root.openSetup()
        }
      }

      Column {
        id: notesSection
        width: parent.width
        spacing: Style.space(10)
        visible: root.panelView === "notes"
        height: visible ? implicitHeight : 0

      PanelSectionHeader {
        text: "TRANSNOTE — " + displayNotes.length + " NOTE" + (displayNotes.length === 1 ? "" : "S")
        foreground: root.foreground
        fontFamily: root.fontFamily
        width: parent.width
      }

      Button {
        visible: !root.syncConfigured
        width: parent.width
        text: "Not sharing yet — open Setup…"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.openSetup()
      }

      // ---- new note ----
      TextField {
        id: noteTitleField
        width: parent.width
        placeholderText: "Note title…"
        foreground: root.foreground
        onTextChanged: root.newTitle = text
        onAccepted: root.addNote()
      }
      ScrollView {
        id: composeScroll
        width: parent.width
        height: Style.space(96)
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

      TextArea {
        id: noteBodyField
        // Bounded compose box: long drafts scroll inside instead of pushing
        // the whole panel out of rails.
        width: composeScroll.width - 8
        placeholderText: "Write a note… (Ctrl+Enter to add)"
        wrapMode: Text.WrapAnywhere
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        color: root.foreground
        background: Rectangle { color: "transparent"; border.color: Qt.darker(root.foreground, 1.8); radius: 6 }
        onTextChanged: root.newBody = text
        Keys.onPressed: function (event) {
          if ((event.modifiers & Qt.ControlModifier) && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter)) {
            root.addNote()
            event.accepted = true
          }
        }
      } // TextArea
      } // composeScroll
      Button {
        text: "Add note"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.addNote()
      }

      PanelSeparator { foreground: root.foreground; width: parent.width }

      // ---- notes: bounded scroll area so long notes scroll instead of
      // pushing the panel out of rails ----
      Text {
        width: parent.width
        visible: root.displayNotes.length === 0
        text: "No notes yet — write the first one above."
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      Item {
        width: parent.width
        visible: root.displayNotes.length > 0
        // Hug the notes: one short note → small window, many notes → grow
        // up to the cap, then scroll inside. (Width is fixed, so sizing the
        // height from contentHeight cannot loop.)
        height: visible ? Math.min(Style.space(300), Math.max(notesView.contentHeight, Style.space(60))) : 0
        clip: true

        ListView {
          id: notesView
          anchors.fill: parent
          model: root.displayNotes
          clip: true
          spacing: Style.space(6)
          boundsBehavior: Flickable.StopAtBounds

            delegate: Column {
            required property var modelData
            property var note: modelData
            // Collapsed preview computed in JS (plain short text), so a long
            // note can never overflow its delegate and paint over the footer.
            property var bodyPreview: Store.previewBody(note.body)
            width: ListView.view.width
            spacing: Style.space(4)

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            Text {
              Layout.fillWidth: true
              Layout.minimumWidth: 0
              text: (note.shared === true ? "◉ " : "○ ") + note.title
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              maximumLineCount: 1
              elide: Text.ElideRight
            }
            Text {
              Layout.maximumWidth: Style.space(130)
              text: root.authorLabel(note)
              color: Qt.darker(root.foreground, 1.4)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              maximumLineCount: 1
              elide: Text.ElideRight
            }
          }
          Text {
            id: bodyText
            width: parent.width
            text: root.isExpanded(note.id) ? note.body : bodyPreview.text
            visible: note.body !== ""
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WrapAnywhere
          }
          Button {
            visible: bodyPreview.truncated || root.isExpanded(note.id)
            text: root.isExpanded(note.id) ? "Show less" : "Show more…"
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.toggleExpanded(note.id)
          }
          // comments: inline ones plus peers' comments merged from snapshots
          Repeater {
            model: root.commentsFor(note.id)
            delegate: Text {
              required property var modelData
              width: parent.width
              text: "↳ " + root.shortAuthor(modelData.author) + ": " + modelData.text
              color: Qt.darker(root.foreground, 1.25)
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: Text.WrapAnywhere
            }
          }
          Text {
            width: parent.width
            visible: (note.attachments || []).length > 0
            text: "📎 " + (note.attachments || []).length + " attachment(s) — preview coming soon"
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
          RowLayout {
            width: parent.width
            spacing: Style.space(6)
            // Comment box on every note: own notes store inline, peer notes
            // go through the sync outbox.
            TextField {
              Layout.fillWidth: true
              placeholderText: "Comment…"
              foreground: root.foreground
              text: root.commentDrafts[note.id] || ""
              onTextChanged: {
                var drafts = {}
                for (var k in root.commentDrafts) drafts[k] = root.commentDrafts[k]
                drafts[note.id] = text
                root.commentDrafts = drafts
              }
              onAccepted: root.addComment(note.id)
            }
            Button {
              visible: note.author === root.myId
              text: note.shared === true ? "Shared" : "Share"
              foreground: root.foreground
              fontFamily: root.fontFamily
              selected: note.shared === true
              onClicked: root.toggleShare(note.id)
            }
            Button {
              visible: note.author === root.myId
              text: "Delete"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.deleteNote(note.id)
            }
          }
            PanelSeparator { foreground: root.foreground; width: parent.width }
          } // delegate Column
        } // notesView ListView
      } // notes list container
      } // notesSection column

      Column {
        id: shareSection
        width: parent.width
        spacing: Style.space(10)
        visible: root.panelView === "share"
        height: visible ? implicitHeight : 0

      // ---- share over internet: no terminal, everything happens here ----
      PanelSectionHeader {
        text: "SHARE OVER INTERNET"
        foreground: root.foreground
        fontFamily: root.fontFamily
        width: parent.width
      }
      Text {
        width: parent.width
        text: root.netStatus === "" ? "Internet: starting…" : root.netStatus
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        visible: root.myNpub !== ""
        text: "Your code — send it to friends (message, email, …):"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      RowLayout {
        width: parent.width
        visible: root.myNpub !== ""
        spacing: Style.space(6)
        TextField {
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          readOnly: true
          text: root.myNpub
          foreground: root.foreground
        }
        Button {
          visible: root.wlCopyOk
          text: "Copy"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: {
            root.copyNote = ""
            copyProcess.command = ["bash", "-c", "printf '%s' " + root.myNpub + " | wl-copy"]
            copyProcess.running = true
          }
        }
      }
      Text {
        width: parent.width
        visible: root.myNpub !== "" && (root.copyNote !== "" || !root.wlCopyOk)
        text: root.copyNote !== "" ? root.copyNote : "Tip: tap the code and copy it with Ctrl+C"
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        visible: root.setupStage === "ready"
        text: "Add a friend — paste the code they sent you:"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      TextField {
        id: friendInputField
        width: parent.width
        visible: root.setupStage === "ready"
        placeholderText: "Friend's code (starts with npub1…)…"
        foreground: root.foreground
        onTextChanged: root.friendInput = text
        onAccepted: root.addFriendFromInput()
      }
      TextField {
        id: friendNameField
        width: parent.width
        visible: root.setupStage === "ready"
        placeholderText: "Name (optional, e.g. Anna)…"
        foreground: root.foreground
        onTextChanged: root.friendName = text
        onAccepted: root.addFriendFromInput()
      }
      Button {
        visible: root.setupStage === "ready"
        text: "Add friend"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.addFriendFromInput()
      }
      Text {
        width: parent.width
        visible: root.friendError !== ""
        text: root.friendError
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      Repeater {
        model: root.friends
        delegate: RowLayout {
          required property var modelData
          width: parent.width
          spacing: Style.space(6)
          Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: "🌐 " + modelData.name
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            maximumLineCount: 1
            elide: Text.ElideRight
          }
          Button {
            text: "Remove"
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.removeFriend(modelData.hex)
          }
        }
      }
      Button {
        visible: root.setupStage === "ready"
        text: "Sync now"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.runSyncCycle()
      }
      } // shareSection column

      Column {
        id: setupSection
        width: parent.width
        spacing: Style.space(10)
        visible: root.panelView === "setup"
        height: visible ? implicitHeight : 0

      PanelSectionHeader {
        text: "SETUP — SHARE ON YOUR NETWORK"
        foreground: root.foreground
        fontFamily: root.fontFamily
        width: parent.width
      }
      Text {
        width: parent.width
        visible: !root.syncConfigured
        text: "Not sharing yet — three quick steps below, no terminal needed."
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        text: "1 — Name this machine (becomes <name>.json in the folder):"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      RowLayout {
        width: parent.width
        spacing: Style.space(6)
        TextField {
          id: setupDeviceField
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          placeholderText: "e.g. laptop…"
          foreground: root.foreground
          text: root.setupDevice
          onTextChanged: root.setupDevice = text
          onAccepted: root.saveSetupDevice()
        }
        Button {
          text: "Save"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.saveSetupDevice()
        }
      }
      Text {
        width: parent.width
        text: "2 — Shared folder (same folder, synced between machines with Syncthing/Dropbox):"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      TextField {
        id: setupDirField
        width: parent.width
        placeholderText: "~/transnote-lan…"
        foreground: root.foreground
        text: root.setupDir
        onTextChanged: { root.setupDir = text; root.checkSetupFolder() }
        onAccepted: root.saveSetupDir()
      }
      RowLayout {
        width: parent.width
        spacing: Style.space(6)
        Button {
          Layout.fillWidth: true
          text: "Create folder"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.createSetupFolder()
        }
        Button {
          Layout.fillWidth: true
          text: "Save folder"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.saveSetupDir()
        }
      }
      Text {
        width: parent.width
        text: "3 — Who can read your shared notes (comma-separated machine names):"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      RowLayout {
        width: parent.width
        spacing: Style.space(6)
        TextField {
          id: setupPeersField
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          placeholderText: "e.g. laptop,desktop…"
          foreground: root.foreground
          text: root.setupPeers
          onTextChanged: root.setupPeers = text
          onAccepted: root.saveSetupPeers()
        }
        Button {
          text: "Save"
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.saveSetupPeers()
        }
      }
      Text {
        width: parent.width
        visible: root.setupMessage !== ""
        text: root.setupMessage
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        text: "Then: sync this folder to your other machine, repeat these 3 steps there (other name, same folder, same list), and press Share on a note."
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      } // setupSection column

      PanelSeparator { foreground: root.foreground; width: parent.width }

      // ---- footer: identity / sync / qualification ----
      Text {
        width: parent.width
        text: "You are: " + root.myId + (root.myHex !== "" ? " · 🌐 " + root.shortAuthor(root.myHex) : "") + " · " + root.syncStatus
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        text: "Sharing with: " + (root.nostrAllowList.length > 0 ? root.nostrAllowList.map(function (h) { return root.shortAuthor(h) }).join(", ") : "(nobody yet)") + " · Attachments coming soon" + (root.pluginVersion !== "" ? " · v" + root.pluginVersion : "")
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
    }
  }
}
