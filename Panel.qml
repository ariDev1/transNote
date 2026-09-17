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
// - Attachments: folder-synced sidecar files with metadata and SHA-256 verification.
Panel {
  id: root
  moduleName: "aridev1.transnote"
  ipcTarget: "aridev1.transnote"
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
  function isSafeDeviceId(value) {
    var id = Store.normalizeText(value)
    return id !== ""
      && id !== "."
      && id !== ".."
      && id[0] !== "."
      && id.indexOf("/") === -1
      && id.indexOf("\\") === -1
      && id.indexOf("\0") === -1
  }

  readonly property string myId: {
    var s = Store.normalizeText(deviceIdSetting)
    if (isSafeDeviceId(s)) return s

    var detected = Store.normalizeText(detectedHostname)
    if (isSafeDeviceId(detected)) return detected

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
  // LAN peer snapshots are untrusted synchronized input. Bound both file
  // count and bytes before snapshot content reaches the QML collector.
  readonly property int maxPeerFiles: 32
  readonly property int maxPeerFileBytes: 2097152
  readonly property int maxPeerAggregateBytes: 8388608
  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string dataDir: (Quickshell.env("XDG_DATA_HOME") || home + "/.local/share") + "/transnote"
  readonly property string notesPath: dataDir + "/notes.json"
  // Previous saved state of notes.json, rotated on every save. Recovery:
  // copy it over notes.json (see README troubleshooting). Guards the
  // private/local-only notes that exist nowhere else.
  readonly property string notesBakPath: dataDir + "/notes.json.bak"
  property string lastLocalRaw: ""
  readonly property string syncSnapshotPath: syncConfigured ? syncDir + "/" + myId + ".json" : ""
  // Internet (Nostr) sync files in the private data dir. The panel runs
  // nostr/sync.mjs itself (no terminal needed): it writes
  // nostr_publish.json for upload and reads nostr_fetch.json for downloads.
  readonly property string nostrFetchPath: dataDir + "/nostr_fetch.json"
  readonly property string nostrPublishPath: dataDir + "/nostr_publish.json"
  readonly property string friendsPath: dataDir + "/friends.json"
  readonly property string keyFile: dataDir + "/nostr_key"
  // Folder this Panel.qml lives in — the plugin dir, wherever it is
  // installed. Used to find the committed Nostr helper bundle.
  readonly property string pluginDir: {
    var u = String(Qt.resolvedUrl("./"))
    if (u.indexOf("file://") === 0) u = u.slice(7)
    if (u.length > 1 && u[u.length - 1] === "/") u = u.slice(0, -1)
    return u
  }
  readonly property string syncBundle: pluginDir + "/nostr/sync.bundle.mjs"
  readonly property string envBin: "/usr/bin/env"
  readonly property string nodeBin: "/usr/bin/node"
  readonly property string pairingHelper: pluginDir + "/lan/syncthing.mjs"
  readonly property string secureRemoveHelper: pluginDir + "/lan/secure_remove.py"
  readonly property string relays: "wss://relay.damus.io,wss://nos.lol,wss://relay.nostr.band"
  property string myHex: ""
  property string myNpub: ""
  property string nostrFetchRaw: ""
  // Shown subtly in the footer so you can check you're on the latest
  // version. Read from manifest.json (single source of truth).
  property string pluginVersion: ""
  // Internet sync state machine: init → nodecheck → key → ready.
  // "node-missing" and "setup-failed" fail closed without affecting LAN.
  property string setupStage: "init"
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
  // Per-note clipboard copy: Copy button stages title+body to a file, then
  // wl-copy reads it (argv-safe for any text — no shell interpolation of
  // the note itself). Button shows Copied!/Failed per note.
  property string pendingCopyNoteId: ""
  property string copiedNoteId: ""
  property string copyFailedId: ""
  readonly property string clipboardStagingPath: dataDir + "/clipboard.txt"
  // Attachments (MVP): sidecar bytes + inline metadata records.
  // - Own notes: attach here, bytes under dataDir/attachments/<noteId>/.
  // - Shared notes: bytes mirrored under <syncDir>/.attachments/<noteId>/
  //   (dot-dir, invisible to the *.json peer scan) and carried by whatever
  //   syncs the folder. Peers verify hash before trusting.
  readonly property string localAttachDir: dataDir + "/attachments"
  readonly property string verifiedAttachDir: dataDir + "/verified-attachments"
  property var attachBusy: ({})    // noteId -> true while copying+hashing
  property var attachMsg: ({})     // noteId -> status/error text
  property var verifiedAtts: ({})  // "<noteId>/<attId>" -> waiting|ok|bad
  property var attachPaths: ({})   // noteId -> draft source path text
  // Notes with a run in flight (cleared per run on completion). Used only
  // to notice crashed runs; run context itself travels in stdout markers
  // so concurrent attaches can never cross (single shared slot did).
  property var attachActive: ({})
  property var verifyJobs: ({})    // "<noteId>/<attId>" -> expected sha256
  function syncAttachDir() {
    return syncConfigured ? syncDir + "/.attachments" : ""
  }
  function ownAttachSubdir(noteId) {
    return localAttachDir + "/" + noteId
  }
  function syncAttachSubdir(noteId) {
    var d = syncAttachDir()
    return d === "" ? "" : d + "/" + noteId
  }
  // Byte location for one attachment: notes in the local file live
  // locally, everything else in the synced dot-dir. Membership (not the
  // author string) decides, so renamed-device notes keep working.
  function attachmentSignature(att) {
    if (!att) return ""

    var name = String(att.name || "")
    var size = Number(att.size)
    var sha = String(att.sha256 || "").toLowerCase()

    if (name === "" || !isFinite(size) || size < 0 || sha === "") return ""

    return JSON.stringify([name, size, sha])
  }

  function currentPeerAttachmentSignature(key) {
    var notes = allPeerNotes()

    for (var i = 0; i < notes.length; i++) {
      var note = notes[i]
      if (!note) continue

      var atts = note.attachments || []

      for (var j = 0; j < atts.length; j++) {
        var clean = Store.sanitizeAttachment(atts[j])
        if (!clean) continue

        if (note.id + "/" + clean.id === key) {
          return attachmentSignature(clean)
        }
      }
    }

    return ""
  }

  function attPathFor(note, att) {
    if (!note || !att || !Store.isSafeId(note.id)) return ""

    var fileName = att.id + "-" + att.name

    if (isLocalNote(note.id)) {
      return ownAttachSubdir(note.id) + "/" + fileName
    }

    var key = note.id + "/" + att.id
    var signature = attachmentSignature(att)

    if (
      signature === ""
      || verifiedAtts[key] !== "ok"
      || verifyJobs[key] !== signature
    ) {
      return ""
    }

    return verifiedAttachDir + "/" + note.id + "/" + fileName
  }
  function attUrl(path) {
    var p = String(path || "")
    if (p === "") return ""
    return "file://" + p.split("/").map(encodeURIComponent).join("/")
  }
  function formatSize(b) {
    var n = Number(b) || 0
    if (n < 1024) return n + " B"
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB"
    return (n / 1048576).toFixed(1) + " MB"
  }
  // Sanitized attachments of one note (never renders hostile records).
  function cleanAttachments(note) {
    var out = []
    ;((note && note.attachments) || []).forEach(function (a) {
      var c = Store.sanitizeAttachment(a)
      if (c) out.push(c)
    })
    return out
  }
  // Text-peek cache for text attachments: key "<noteId>/<attId>".
  property var attPeeks: ({})
  function setAttPeek(key, text) {
    var m = {}
    for (var k in attPeeks) m[k] = attPeeks[k]
    m[key] = String(text || "")
    attPeeks = m
  }
  function peekLines(key) {
    var lines = String(attPeeks[key] || "").replace(/\r\n/g, "\n").split("\n")
    if (lines.length <= 30) return lines.join("\n")
    return lines.slice(0, 30).join("\n") + "\n…"
  }
  property string savePendingNote: ""
  property string openPendingNote: ""
  property string openPendingName: ""
  // Save a received file to ~/Downloads (never overwrites: .1, .2…).
  function saveAttachment(note, att) {
    var clean = Store.sanitizeAttachment(att)
    if (!note || !clean) return
    var src = attPathFor(note, clean)
    if (src === "") { setAttachMsg(note.id, "File not found."); return }
    var dl = (home || "") + "/Downloads"
    savePendingNote = note.id
    setAttachMsg(note.id, "Saving…")
    saveProcess.command = ["bash", "-c",
      "mkdir -p " + shellQuote(dl) + " && dst=" + shellQuote(dl + "/" + clean.name)
      + "; n=1; while test -e \"$dst\"; do n=$((n + 1)); dst=" + shellQuote(dl + "/" + clean.name) + ".$n; done; "
      + "cp -- " + shellQuote(src) + " \"$dst\" && echo SAVED:$dst"]
    saveProcess.running = true
  }
  function onSaveOutput(text, exitCode) {
    var noteId = savePendingNote
    savePendingNote = ""
    if (noteId === "") return
    if (exitCode === 0 && String(text || "").indexOf("SAVED:") !== -1) {
      var p = String(text).split("SAVED:")[1].trim().split("\n")[0]
      var short = p.replace((home || "") + "/", "~/")
      setAttachMsg(noteId, "Saved to " + short)
    } else {
      setAttachMsg(noteId, "Save failed — file may not have arrived yet.")
    }
  }
  // Open explicitly via the system handler. Executables are save-only:
  // risky extensions and anything with the exec bit are refused here.
  function openAttachment(note, att) {
    var clean = Store.sanitizeAttachment(att)
    if (!note || !clean) return
    if (Store.isRiskyExecutable(clean.name)) {
      setAttachMsg(note.id, clean.name + " looks executable — saved copies only, never opened.")
      return
    }
    var src = attPathFor(note, clean)
    if (src === "") { setAttachMsg(note.id, "File not found."); return }
    openPendingNote = note.id
    openPendingName = clean.name
    openProcess.command = ["bash", "-c",
      "test -f " + shellQuote(src) + " || { echo MISSING; exit 0; }; "
      + "test -x " + shellQuote(src) + " && { echo EXECBIT; exit 0; }; "
      + "xdg-open " + shellQuote(src) + " >/dev/null 2>&1 & echo OPENED"]
    openProcess.running = true
  }
  function onOpenOutput(text) {
    var noteId = openPendingNote
    var name = openPendingName
    openPendingNote = ""
    openPendingName = ""
    if (noteId === "") return
    var out = String(text || "")
    if (out.indexOf("EXECBIT") !== -1) setAttachMsg(noteId, name + " has the executable bit — save instead.")
    else if (out.indexOf("MISSING") !== -1) setAttachMsg(noteId, "File not arrived yet — try again in a bit.")
    else setAttachMsg(noteId, "Opening " + name + "…")
  }
  function setAttachMsg(noteId, msg) {
    var m = {}
    for (var k in attachMsg) m[k] = attachMsg[k]
    if (msg === "") delete m[noteId]
    else m[noteId] = msg
    attachMsg = m
  }
  function setAttachBusy(noteId, busy) {
    var b = {}
    for (var k in attachBusy) b[k] = attachBusy[k]
    if (busy) b[noteId] = true
    else delete b[noteId]
    attachBusy = b
  }
  // Attach a file (own notes only): size gate → stage copy → sha256, one
  // shell chain. Record joins note.attachments on success; persist()
  // publishes the metadata, the folder sync carries the bytes.
  function attachFile(noteId, srcRaw) {
    var src = Store.normalizeText(srcRaw)
    if (attachBusy[noteId]) return
    if (src === "") { setAttachMsg(noteId, "Enter a file path first."); return }
    var note = null
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === noteId) { note = localNotes[i]; break }
    }
    if (!note) return
    if (src[0] === "~") src = (home || "") + src.slice(1)
    var cleanName = Store.sanitizeFileName(src.split("/").pop())
    if (cleanName === "") { setAttachMsg(noteId, "That file name is unusable."); return }
    var attId = Store.uid("att")
    var dir = ownAttachSubdir(noteId)
    var act = {}
    for (var k in attachActive) act[k] = attachActive[k]
    act[noteId] = true
    attachActive = act
    setAttachBusy(noteId, true)
    setAttachMsg(noteId, "Attaching…")
    attachProcess.command = ["bash", "-c",
      "echo '===ATTACHCTX==='; echo 'NOTE:" + noteId + "'; echo 'ATT:" + attId + "'; echo 'NAME:" + cleanName + "'; "
      + "S=$(stat -c%s " + shellQuote(src) + " 2>/dev/null) || { echo NOSRC; exit 0; }; "
      + "echo SIZE:$S; "
      + "if [ \"$S\" -gt " + Store.MAX_ATTACHMENT_BYTES + " ]; then echo TOOBIG; exit 0; fi; "
      + "mkdir -p " + shellQuote(dir) + " && cp -- " + shellQuote(src) + " " + shellQuote(dir + "/" + attId + "-" + cleanName)
      + " && sha256sum " + shellQuote(dir + "/" + attId + "-" + cleanName)]
    attachProcess.running = true
  }
  function clearAttachActive(noteId) {
    if (!attachActive[noteId]) return
    var act = {}
    for (var k in attachActive) act[k] = attachActive[k]
    delete act[noteId]
    attachActive = act
  }
  function onAttachOutput(text, exitCode) {
    var out = String(text || "")
    var noteId = ""
    var attId = ""
    var cleanName = ""
    out.split("\n").forEach(function (line) {
      var m = line.match(/^(NOTE|ATT|NAME):(.*)$/)
      if (m && m[1] === "NOTE") noteId = m[2].trim()
      else if (m && m[1] === "ATT") attId = m[2].trim()
      else if (m && m[1] === "NAME") cleanName = m[2].trim()
    })
    // No context (stray output): nothing attributable, ignore.
    if (noteId === "" || attId === "") return
    clearAttachActive(noteId)
    var dst = ownAttachSubdir(noteId) + "/" + attId + "-" + cleanName
    if (out.indexOf("NOSRC") !== -1) {
      setAttachBusy(noteId, false)
      setAttachMsg(noteId, "File not found — check the path.")
      return
    }
    if (out.indexOf("TOOBIG") !== -1) {
      setAttachBusy(noteId, false)
      setAttachMsg(noteId, "Too big — max " + Math.round(Store.MAX_ATTACHMENT_BYTES / 1048576) + " MB per file.")
      return
    }
    var size = -1
    var sha = ""
    out.split("\n").forEach(function (line) {
      var m = line.match(/^SIZE:(\d+)$/)
      if (m) size = parseInt(m[1], 10)
      var h = line.match(/^([0-9a-f]{64})\s/)
      if (h) sha = h[1]
    })
    var rec = (size >= 0 && sha !== "" && cleanName !== "") ? Store.createAttachment(cleanName, size, sha, attId) : null
    // Stale sidecar of THIS run only (never another run's files).
    if (!rec || rec.id !== attId) {
      queueGc(["bash", "-c", "rm -f " + shellQuote(dst) + " 2>/dev/null; true"])
      setAttachBusy(noteId, false)
      setAttachMsg(noteId, exitCode === 0 ? "Couldn't stage that file." : "Attach failed — try again.")
      return
    }
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === noteId) {
        if (!Array.isArray(localNotes[i].attachments)) localNotes[i].attachments = []
        localNotes[i].attachments.push(rec)
        touchLocalNotes()
        break
      }
    }
    setAttachBusy(noteId, false)
    setAttachMsg(noteId, "")
    persist()
  }
  // Remove sidecar dirs for a note. includeSync=false deletes own bytes
  // only, true deletes own + synced mirror (delete). Never use for
  // unshare — that must keep local bytes and drop only the mirror
  // (see toggleShare).
  function queueSafeRemove(rootDir, noteId) {
    if (rootDir === "" || !Store.isSafeId(noteId)) return
    // No shell and no inherited environment. The helper retains directory
    // descriptors and never reopens a checked descendant by pathname.
    queueGc([envBin, "-i", "/usr/bin/python3", secureRemoveHelper, rootDir, noteId])
  }

  function queueSafeUnlink(rootDir, noteId, fileName) {
    if (rootDir === "" || !Store.isSafeId(noteId) || fileName === "") return
    queueGc([
      envBin,
      "-i",
      "/usr/bin/python3",
      secureRemoveHelper,
      "unlink",
      rootDir,
      noteId,
      fileName
    ])
  }

  function queueSafeCopy(sourcePath, rootDir, noteId, fileName) {
    if (
      sourcePath === ""
      || rootDir === ""
      || !Store.isSafeId(noteId)
      || fileName === ""
    ) return

    queueGc([
      envBin,
      "-i",
      "/usr/bin/python3",
      secureRemoveHelper,
      "copy",
      sourcePath,
      rootDir,
      noteId,
      fileName
    ])
  }

  function removeAttachDirs(noteId, includeSync) {
    if (!Store.isSafeId(noteId)) return
    queueSafeRemove(localAttachDir, noteId)
    var syncRoot = syncAttachDir()
    if (includeSync && syncRoot !== "") queueSafeRemove(syncRoot, noteId)
  }
  // Fire-and-forget sidecar cleanup queue: gcProcess is a single shared
  // slot, so rapid consecutive deletes must queue instead of overwriting
  // each other's command (last-wins would orphan earlier sidecars).
  property var pendingGc: []
  function queueGc(cmd) {
    if (!cmd) return
    pendingGc = (pendingGc || []).concat([cmd])
    if (!gcProcess.running) flushGc()
  }
  function flushGc() {
    if (gcProcess.running) return
    var q = pendingGc || []
    if (q.length === 0) return
    // Preserve each command as argv. This lets the secure-delete helper run
    // directly through /usr/bin/env without a shell or inherited environment.
    gcProcess.command = q[0]
    pendingGc = q.slice(1)
    gcProcess.running = true
  }
  // Remove one attachment: drop the record, delete both sidecars.
  function removeAttachment(noteId, attId) {
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === noteId) {
        var kept = []
        var gone = []
        ;(localNotes[i].attachments || []).forEach(function (a) {
          var clean = Store.sanitizeAttachment(a)
          if (clean && clean.id === attId) gone.push(clean)
          else if (clean) kept.push(clean)
          else if (a) kept.push(a)
        })
        localNotes[i].attachments = kept
        gone.forEach(function (g) {
          var fileName = g.id + "-" + g.name
          queueSafeUnlink(localAttachDir, noteId, fileName)
          queueSafeUnlink(syncAttachDir(), noteId, fileName)
        })
        touchLocalNotes()
        break
      }
    }
    persist()
  }
  // Re-verify every peer attachment: present + hash match → ok, absent →
  // waiting (still syncing), mismatch → bad. Runs after each peer fetch.
  function refreshAttachmentStates() {
    if (verifyProcess.running) return

    var sourceRoot = syncAttachDir()
    var jobs = []
    var seen = {}

    allPeerNotes().forEach(function (n) {
      if (!n || !Store.isSafeId(n.id)) return

      ;(n.attachments || []).forEach(function (a) {
        var clean = Store.sanitizeAttachment(a)
        if (!clean) return

        var key = n.id + "/" + clean.id
        if (seen[key]) return
        seen[key] = true

        var signature = attachmentSignature(clean)
        if (signature === "") return

        jobs.push({
          key: key,
          noteId: n.id,
          fileName: clean.id + "-" + clean.name,
          size: clean.size,
          sha: clean.sha256,
          signature: signature
        })
      })
    })

    // Keep an existing OK state only when it belongs to the exact metadata
    // that is still current. This prevents an older successful job from
    // authorizing new metadata with the same note/attachment IDs.
    var retained = {}
    jobs.forEach(function (j) {
      if (
        verifiedAtts[j.key] === "ok"
        && verifyJobs[j.key] === j.signature
      ) {
        retained[j.key] = "ok"
      }
    })

    if (JSON.stringify(retained) !== JSON.stringify(verifiedAtts)) {
      verifiedAtts = retained
    }

    var exp = {}
    jobs.forEach(function (j) {
      exp[j.key] = j.signature
    })
    verifyJobs = exp

    // Prune runs in the same process sequence as verification. It cannot
    // race a verification temporary file.
    var pruneArgs = [
      envBin,
      "-i",
      "/usr/bin/python3",
      secureRemoveHelper,
      "prune-verified",
      verifiedAttachDir
    ]

    jobs.forEach(function (j) {
      pruneArgs.push(j.noteId)
      pruneArgs.push(j.fileName)
      pruneArgs.push(String(j.size))
      pruneArgs.push(j.sha)
    })

    var cmds = [
      pruneArgs.map(function (arg) {
        return shellQuote(arg)
      }).join(" ")
    ]

    if (sourceRoot !== "") {
      jobs.forEach(function (j) {
        cmds.push(
          "echo '===ATT:" + j.key + "==='; "
          + shellQuote(envBin)
          + " -i /usr/bin/python3 "
          + shellQuote(secureRemoveHelper)
          + " " + shellQuote("verify-copy")
          + " " + shellQuote(sourceRoot)
          + " " + shellQuote(j.noteId)
          + " " + shellQuote(j.fileName)
          + " " + shellQuote(String(j.size))
          + " " + shellQuote(String(Store.MAX_ATTACHMENT_BYTES))
          + " " + shellQuote(j.sha)
          + " " + shellQuote(verifiedAttachDir)
          + " || echo READFAIL"
        )
      })
    }

    verifyProcess.command = ["bash", "-c", cmds.join("\n")]
    verifyProcess.running = true
  }
  function applyVerifyOutput(output) {
    var next = {}
    var idx = ""
    var exp = verifyJobs

    String(output || "").split("\n").forEach(function (line) {
      var m = line.match(/^===ATT:(.*)===$/)
      if (m) {
        idx = m[1]
        return
      }

      if (idx === "") return

      var current = currentPeerAttachmentSignature(idx)

      // Ignore output from a job that belongs to older peer metadata.
      if (!exp[idx] || current === "" || current !== exp[idx]) {
        idx = ""
        return
      }

      if (line === "VERIFIED") next[idx] = "ok"
      else if (line === "BAD_SIZE" || line === "BAD_HASH") next[idx] = "bad"
      else if (line === "MISSING" || line === "READFAIL") next[idx] = "waiting"

      idx = ""
    })

    if (JSON.stringify(next) !== JSON.stringify(verifiedAtts)) {
      verifiedAtts = next
    }
  }
  function copyNoteFull(note) {
    if (!note || !note.id) return
    copyRawText(Store.copyText(note), note.id)
  }
  function copyRawText(text, key) {
    if (!key) return
    pendingCopyNoteId = key
    copiedNoteId = ""
    copyFailedId = ""
    clipboardFile.setText(String(text || ""))
    copyDelay.restart()
  }
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
  // TN1 device-pairing state. Pairing is optional: the existing manual
  // folder-sync settings below remain authoritative and usable without it.
  property string pairingCode: ""
  property string incomingPairingCode: ""
  property string pairingMessage: "Device sync is ready to configure."
  property bool pairingBusy: false
  property var pairingPendingDevices: []
  property var pairingPendingOffers: []
  property var pairingPeers: []
  // Last folder-merge outcome, shown in Setup so a missing peer note can be
  // located without log access: files seen → notes parsed → notes kept →
  // notes displayed. Updated by rebuildPeerNotes() on every peer load.
  property string peerDebug: ""
  readonly property string omarchyBin: (Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy") + "/bin/omarchy"
  // Authors of existing local notes that differ from the drafted device
  // name. Renaming re-signs them to the new name automatically (see
  // loadLocal migration + migrateAuthors), so buttons keep working — but
  // peers must allow-list the NEW name afterwards, since qualification
  // matches note authors, not snapshot file names.
  readonly property var setupForeignAuthors: {
    var seen = {}
    var out = []
    var want = Store.normalizeText(root.setupDevice)
    ;(localNotes || []).forEach(function (n) {
      var a = Store.normalizeText(n && n.author)
      if (a !== "" && a !== want && !seen[a]) { seen[a] = true; out.push(a) }
    })
    return out
  }
  function pairingSyncDir() {
    var d = expandSetupDir(setupDir)
    if (d !== "") return d
    return syncDir
  }
  function pairingDeviceId() {
    var d = Store.normalizeText(setupDevice)
    return d !== "" ? d : myId
  }
  function pairingBaseCommand(action) {
    return [nodeBin, pairingHelper, action,
      "--device-id", pairingDeviceId(),
      "--sync-dir", pairingSyncDir(),
      "--data-dir", dataDir]
  }
  function pairingErrorMessage(info) {
    var code = Store.normalizeText(info && info.code)
    if (code === "SYNCTHING_NOT_FOUND") return "Syncthing is not installed. Manual folder sync still works."
    if (code === "SYNCTHING_NOT_RUNNING") return "Syncthing is not running. Manual folder sync still works."
    if (code === "BAD_PAIRING_CODE") return "That TransNote setup code is invalid."
    if (code === "PAIR_SELF") return "This setup code belongs to this computer."
    if (code === "PAIR_CONFLICT") return "This computer conflicts with an existing pairing record."
    if (code === "FOLDER_ID_CONFLICT" || code === "FOLDER_PATH_CONFLICT") return "The TransNote folder conflicts with an existing Syncthing folder."
    if (code === "PENDING_OFFER_MISMATCH") return "The pending folder offer does not match this setup code."
    var msg = Store.normalizeText(info && info.message)
    return msg !== "" ? msg : "Device sync failed. Manual folder sync remains available."
  }
  function parsePairingResult(text) {
    try { return JSON.parse(String(text || "")) }
    catch (e) { return null }
  }
  function preparePairing() {
    if (pairingBusy) return
    if (Store.normalizeText(pairingSyncDir()) === "") {
      pairingMessage = "Enter a shared folder first."
      return
    }
    pairingBusy = true
    pairingMessage = "Preparing device sync…"
    pairingProcess.action = "prepare"
    pairingProcess.output = ""
    pairingProcess.errorOutput = ""
    pairingProcess.command = pairingBaseCommand("prepare")
    pairingProcess.running = true
  }
  function connectPairing() {
    if (pairingBusy) return
    var code = Store.normalizeText(incomingPairingCode)
    if (code === "") {
      pairingMessage = "Paste a TransNote setup code first."
      return
    }
    pairingBusy = true
    pairingMessage = "Connecting computer…"
    pairingProcess.action = "pair"
    pairingProcess.output = ""
    pairingProcess.errorOutput = ""
    pairingProcess.command = pairingBaseCommand("pair").concat(["--code", code])
    pairingProcess.running = true
  }
  function acceptPairingDevice(deviceId) {
    if (pairingBusy) return
    var id = Store.normalizeText(deviceId)
    if (id === "") return
    pairingBusy = true
    pairingMessage = "Accepting computer connection…"
    pairingProcess.action = "accept-device"
    pairingProcess.output = ""
    pairingProcess.errorOutput = ""
    pairingProcess.command = pairingBaseCommand("accept-device").concat(["--syncthing-device-id", id])
    pairingProcess.running = true
  }
  function acceptPairingFolder(folderId, deviceId) {
    if (pairingBusy) return
    var folder = Store.normalizeText(folderId)
    var device = Store.normalizeText(deviceId)
    if (folder === "" || device === "") return
    pairingBusy = true
    pairingMessage = "Accepting TransNote folder…"
    pairingProcess.action = "accept-folder"
    pairingProcess.output = ""
    pairingProcess.errorOutput = ""
    pairingProcess.command = pairingBaseCommand("accept-folder").concat([
      "--folder-id", folder,
      "--syncthing-device-id", device])
    pairingProcess.running = true
  }
  function persistPairingBaseSettings() {
    var device = pairingDeviceId()
    var folder = Store.normalizeText(setupDir)
    if (device !== Store.normalizeText(deviceIdSetting)) {
      barSetDevice.command = [omarchyBin, "bar", "set", "aridev1.transnote", "deviceId", device]
      barSetDevice.running = true
    }
    if (folder !== "" && folder !== Store.normalizeText(syncDirSetting)) {
      barSetDir.command = [omarchyBin, "bar", "set", "aridev1.transnote", "syncDir", folder]
      barSetDir.running = true
    }
  }
  function qualifyPairingPeer(peerName) {
    var peer = Store.normalizeText(peerName)
    if (peer === "") return
    var peers = Store.parseAllowList(setupPeers)
    if (peers.indexOf(peer) === -1) peers.push(peer)
    setupPeers = peers.join(",")
    if (setupPeersField) setupPeersField.text = setupPeers
    saveSetupPeers()
  }
  function finishPairingAction(exitCode, action, output, errorOutput) {
    pairingBusy = false
    var info = parsePairingResult(exitCode === 0 ? output : errorOutput)
    if (exitCode !== 0 || !info || info.ok !== true) {
      pairingMessage = pairingErrorMessage(info || {})
      refreshPairingStatus()
      return
    }
    if (action === "prepare") {
      persistPairingBaseSettings()
      pairingCode = Store.normalizeText(info.pairingCode)
      pairingMessage = pairingCode !== "" ? "Setup code ready." : "Pairing helper returned no setup code."
    } else if (action === "pair") {
      persistPairingBaseSettings()
      var peer = Store.normalizeText(info.peer && info.peer.transnoteDeviceId)
      if (peer !== "") {
        qualifyPairingPeer(peer)
        pairingMessage = "Connected to " + peer + "."
      } else {
        pairingMessage = "Connected, but no TransNote machine name was returned."
      }
    } else if (action === "accept-device") {
      var deviceName = Store.normalizeText(info.deviceName)
      pairingMessage = "Computer accepted" + (deviceName !== "" ? ": " + deviceName : "") + ". Waiting for folder offer…"
    } else if (action === "accept-folder") {
      persistPairingBaseSettings()
      pairingMessage = "TransNote folder accepted."
    }
    refreshPairingStatus()
  }
  function applyPairingStatus(exitCode, output, errorOutput) {
    var info = parsePairingResult(exitCode === 0 ? output : errorOutput)
    if (exitCode !== 0 || !info || info.ok !== true) {
      pairingMessage = pairingErrorMessage(info || {})
      return
    }
    pairingPendingDevices = Array.isArray(info.pendingDevices) ? info.pendingDevices : []
    pairingPendingOffers = Array.isArray(info.pendingOffers) ? info.pendingOffers : []
    pairingPeers = Array.isArray(info.peers) ? info.peers : []
    if (info.installed === false) pairingMessage = "Syncthing is not installed. Manual folder sync still works."
    else if (info.running === false) pairingMessage = "Syncthing is not running. Manual folder sync still works."
  }
  function refreshPairingStatus() {
    if (pairingStatusProcess.running) return
    pairingStatusProcess.output = ""
    pairingStatusProcess.errorOutput = ""
    pairingStatusProcess.command = pairingBaseCommand("status")
    pairingStatusProcess.running = true
  }
  function copyPairingCode() {
    if (Store.normalizeText(pairingCode) === "") return
    pairingCopyProcess.command = ["bash", "-c", "printf '%s' \"$1\" | wl-copy", "transnote-pairing", pairingCode]
    pairingCopyProcess.running = true
  }
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
    refreshPairingStatus()
  }
  function expandSetupDir(path) {
    var d = Store.normalizeText(path)
    if (d === "") return ""
    if (d[0] === "~") return (home || "") + d.slice(1)
    return d
  }
  function saveSetupDevice() {
    var v = Store.normalizeText(setupDevice)
    if (v === "") {
      setupMessage = "Give this machine a name first (e.g. laptop)."
      return
    }
    if (!isSafeDeviceId(v)) {
      setupMessage = "Use a normal machine name without path characters."
      return
    }
    setupSaving = true
    setupMessage = "Saving name…"
    barSetDevice.command = [omarchyBin, "bar", "set", "aridev1.transnote", "deviceId", v]
    barSetDevice.running = true
  }
  function saveSetupDir() {
    var v = Store.normalizeText(setupDir)
    if (v === "") { setupMessage = "Enter a folder first (e.g. ~/transnote-lan)."; return }
    setupSaving = true
    setupMessage = "Saving folder…"
    barSetDir.command = [omarchyBin, "bar", "set", "aridev1.transnote", "syncDir", v]
    barSetDir.running = true
  }
  function saveSetupPeers() {
    setupSaving = true
    setupMessage = "Saving sharing list…"
    barSetPeers.command = [omarchyBin, "bar", "set", "aridev1.transnote", "allowList", Store.normalizeText(setupPeers)]
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
  // Path autocomplete for every path field (Setup folder, attach path).
  // Debounced `compgen` lookup; Tab completes the common prefix, click (or
  // Tab on a single match) accepts. target is "setup" or a note id.
  property var completeResults: []
  property string completeFor: ""
  property var completePending: null
  function expandCompletePartial(text) {
    var p = Store.normalizeText(text)
    if (p === "") return ""
    if (p[0] === "~") p = (home || "") + p.slice(1)
    if (p[0] !== "/") p = (home || "") + "/" + p
    return p
  }
  function shortCompletePath(path) {
    var h = home || ""
    if (h !== "" && String(path).indexOf(h + "/") === 0) return "~" + String(path).slice(h.length)
    return String(path)
  }
  function requestComplete(target, text, dirsOnly) {
    completePending = { target: target, partial: expandCompletePartial(text), dirsOnly: dirsOnly === true }
    if (completePending.partial === "") {
      completeResults = []
      completeFor = ""
      return
    }
    completeDebounce.restart()
  }
  function runComplete() {
    if (completeProcess.running) return
    var req = completePending
    completePending = null
    if (!req) return
    completeProcess.currentTarget = req.target
    completeProcess.currentPartial = req.partial
    completeProcess.command = ["bash", "-c", req.dirsOnly ? 'compgen -d -- "$0"' : 'compgen -f -- "$0"', req.partial]
    completeProcess.running = true
  }
  function applyComplete(output) {
    var target = completeProcess.currentTarget
    // Field cleared while we worked: drop stale results.
    var cur = target === "setup" ? expandCompletePartial(setupDir) : expandCompletePartial(attachPaths[target] || "")
    if (cur === "") {
      completeResults = []
      completeFor = ""
      return
    }
    var seen = {}
    var out = []
    String(output || "").split("\n").forEach(function (line) {
      var s = line.trim()
      if (s !== "" && !seen[s] && out.length < 12) { seen[s] = true; out.push(s) }
    })
    // User kept typing while we worked: re-run with the latest text.
    if (completePending) {
      completeResults = []
      completeFor = ""
      runComplete()
      return
    }
    // A single exact match is completion, not a suggestion.
    if (out.length === 1 && out[0] === expandCompletePartial(completeProcess.currentPartial || "")) {
      completeResults = []
      completeFor = ""
      return
    }
    completeResults = out
    completeFor = out.length > 0 ? target : ""
  }
  function acceptCompletion(target, value) {
    completeResults = []
    completeFor = ""
    completePending = null
    if (target === "setup") {
      setupDir = value
      if (setupDirField) setupDirField.text = value
    } else {
      var m = {}
      for (var k in attachPaths) m[k] = attachPaths[k]
      m[target] = value
      attachPaths = m
    }
  }
  function completeCommonPrefix(target) {
    var list = (completeFor === target) ? completeResults : []
    if (list.length === 0) return false
    var prefix = String(list[0])
    for (var i = 1; i < list.length; i++) {
      var s = String(list[i])
      var j = 0
      while (j < prefix.length && j < s.length && prefix[j] === s[j]) j++
      prefix = prefix.slice(0, j)
    }
    if (prefix === "") return false
    acceptCompletion(target, prefix)
    return true
  }
  function clearCompletion() {
    completeResults = []
    completeFor = ""
    completePending = null
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
  // Deletion tombstones { noteId: deletedAtIso } — persisted locally and
  // published in the LAN snapshot + as NIP-09 kind-5 on Nostr. Delete-wins:
  // every merge path filters against them so deleted notes never resurrect.
  property var deletedIds: ({})
  // Tombstones not yet uploaded to Nostr (noteIds). Flushed on publish.
  property var pendingDeletes: []
  // Local-only hides [noteId]: dismissing a peer's note hides it on this
  // machine only (never published, never affects others).
  property var hiddenIds: []
  // My comments on peers' notes, published in my snapshot so their authors
  // merge them in: [{ noteId, comment }]. Persisted in the local file.
  property var outbox: []
  // Peers' comments on notes I display, merged from their snapshots:
  // { noteId: [comment] }.
  property var foreignComments: ({})
  property string syncStatus: ""
  property string selectedNoteId: ""
  // Unread tracking for the subtle new-note effect. The list model is
  // rebuilt wholesale on every sync (so per-item entrance animations would
  // replay constantly) — instead: the bar icon tints while anything is
  // unread, and fresh notes carry a small "• new" pill until the panel is
  // opened. First build only primes the known set (no unread after restart).
  property var knownNoteIds: ({})
  property var unreadIds: ({})
  property bool notesPrimed: false
  readonly property bool hasUnread: Object.keys(unreadIds).length > 0
  function trackFreshness() {
    var seen = {}
    ;(displayNotes || []).forEach(function (n) { if (n && n.id) seen[n.id] = true })
    if (!notesPrimed) {
      knownNoteIds = seen
      notesPrimed = true
      return
    }
    var unread = {}
    for (var k in unreadIds) unread[k] = unreadIds[k]
    var changed = false
    // Own notes are never "new" — only arrivals from others.
    ;(displayNotes || []).forEach(function (n) {
      if (!n || !n.id) return
      if (n.author === myId || (myHex !== "" && n.author === myHex)) return
      if (!knownNoteIds[n.id] && !unread[n.id]) { unread[n.id] = true; changed = true }
    })
    Object.keys(unread).forEach(function (id) {
      if (!seen[id]) { delete unread[id]; changed = true }
    })
    knownNoteIds = seen
    if (changed) unreadIds = unread
  }
  function markAllRead() {
    if (Object.keys(unreadIds).length > 0) unreadIds = ({})
  }
  // Note tints: translucent theme-safe washes (never opaque theme colors),
  // one per note, synced like any other field. Cycled from the title row.
  readonly property var noteTintMap: ({
    red: "#2BE57373", orange: "#2BFFB74D", yellow: "#2BFFF176",
    green: "#2B81C784", blue: "#2B64B5F6", violet: "#2BBA68C8"
  })
  readonly property var colorCycle: ["red", "orange", "yellow", "green", "blue", "violet", ""]
  function noteTint(note) {
    var c = (note && note.color) || ""
    return noteTintMap[c] || "transparent"
  }
  function cycleColor(noteId) {
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === noteId) {
        if (Store.normalizeText(localNotes[i].author) !== Store.normalizeText(myId)) {
          localNotes[i].author = Store.normalizeText(myId)
        }
        var cur = Store.sanitizeColor(localNotes[i].color)
        var at = colorCycle.indexOf(cur)
        Store.setColor(localNotes[i], colorCycle[(at + 1) % colorCycle.length], "")
        touchLocalNotes()
        break
      }
    }
    persist()
  }
  // Keyboard navigation (Omarchy idiom: PanelKeyCatcher + note cursor).
  // j/k/arrows move, Enter/Space expands, c copies, s shares, x deletes
  // deletable notes (hides peers' notes), a opens the attach row, /
  // jumps to compose. Any text field focused sets editing (catcher passes
  // keys through instead).
  property bool editing: false
  property bool cursorActive: false
  property int noteCursor: -1
  property string focusAttachFor: ""
  function cursorNoteId() {
    if (noteCursor < 0 || noteCursor >= displayNotes.length) return ""
    var n = displayNotes[noteCursor]
    return (n && n.id) || ""
  }
  function cursorOn(noteId) {
    return cursorActive && cursorNoteId() === noteId
  }
  function ensureCursor() {
    if (displayNotes.length === 0) { noteCursor = -1; return }
    if (noteCursor < 0) noteCursor = 0
    if (noteCursor >= displayNotes.length) noteCursor = displayNotes.length - 1
  }
  function cursorNote() {
    var id = cursorNoteId()
    if (id === "") return null
    for (var i = 0; i < displayNotes.length; i++) {
      if (displayNotes[i] && displayNotes[i].id === id) return displayNotes[i]
    }
    return null
  }
  function moveCursor(dx, dy) {
    if (root.panelView !== "notes") return
    cursorActive = true
    if (dy !== 0) {
      ensureCursor()
      noteCursor = Math.max(0, Math.min(displayNotes.length - 1, noteCursor + dy))
      scrollCursorIntoView()
    } else if (dx < 0) {
      var n = cursorNote()
      if (n && isExpanded(n.id)) toggleExpanded(n.id)
    } else if (dx > 0) {
      var m = cursorNote()
      if (m && !isExpanded(m.id)) toggleExpanded(m.id)
    }
  }
  function activateCursor() {
    if (root.panelView !== "notes") return
    cursorActive = true
    ensureCursor()
    var n = cursorNote()
    if (n) toggleExpanded(n.id)
  }
  function deleteCursorNote() {
    var n = cursorNote()
    if (!n) return
    if (isDeletable(n)) deleteNote(n.id)
    else hideNote(n.id)
  }
  function cursorKey(t) {
    if (root.panelView !== "notes") return
    if (t === "c") {
      var n = cursorNote()
      if (n) copyNoteFull(n)
    } else if (t === "s") {
      var m = cursorNote()
      if (m && isLocalNote(m.id)) toggleShare(m.id)
    } else if (t === "a") {
      var k = cursorNote()
      if (k && isLocalNote(k.id)) {
        if (!attachOpen[k.id]) toggleAttachRow(k.id)
        focusAttachFor = k.id
      }
    } else if (t === "t") {
      var c2 = cursorNote()
      if (c2 && isLocalNote(c2.id)) cycleColor(c2.id)
    } else if (t === "/") {
      if (noteTitleField) noteTitleField.forceActiveFocus()
    }
  }
  function scrollCursorIntoView() {
    if (noteCursor < 0 || !panelFlick) return
    try {
      notesView.positionViewAtIndex(noteCursor, ListView.Contain)
      var item = notesView.itemAtIndex(noteCursor)
      if (!item) return
      var p = item.mapToItem(panelFlick.contentItem, 0, 0)
      if (p.y < panelFlick.contentY) panelFlick.contentY = p.y
      else if (p.y + item.height > panelFlick.contentY + panelFlick.height) {
        panelFlick.contentY = p.y + item.height - panelFlick.height
      }
    } catch (e) { /* best effort */ }
  }
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
  // True once the local notes file has been read (or confirmed missing).
  // Guards persist-on-config-change so a settings update arriving before
  // the first load can never clobber notes.json with an empty array.
  property bool localLoaded: false
  // Set when the local file failed to load (corrupt/locked): persist()
  // then skips the local-file write so a transient read failure can never
  // wipe notes.json — memory is kept until the next successful load.
  property bool localLoadFailed: false

  function refreshDisplay() {
    var union = (localNotes || []).concat(peerNotes || []).concat(nostrPeerNotes || [])
    union = Store.filterDeletedNotes(union, deletedIds)
    var hidden = {}
    ;(hiddenIds || []).forEach(function (id) { if (id) hidden[Store.normalizeText(id)] = true })
    displayNotes = Store.sortNotes(union.filter(function (n) { return !!n && !hidden[n.id] }))
    trackFreshness()
  }

  function allPeerNotes() {
    return (peerNotes || []).concat(nostrPeerNotes || [])
  }

  function mergePeers() {
    // peerNotes already holds only qualified, shared notes (filtered when
    // each snapshot loads). Rebuild the union defensively anyway.
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var fresh = (peerNotes || []).filter(function (n) { return n && !mine[n.id] && !Store.isDeleted(deletedIds, n.id) })
    peerNotes = fresh
    var freshNostr = (nostrPeerNotes || []).filter(function (n) { return n && !mine[n.id] && !Store.isDeleted(deletedIds, n.id) })
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
      var files = [notesPath, notesBakPath, friendsPath, keyFile, nostrPublishPath, nostrFetchPath, clipboardStagingPath]
      if (syncSnapshotPath !== "") files.push(syncSnapshotPath)
      secureProcess.command = ["bash", "-c",
        "chmod 700 " + shellQuote(dataDir) + " " + shellQuote(localAttachDir) + " 2>/dev/null; chmod 600 "
        + files.map(shellQuote).join(" ") + " 2>/dev/null; find " + shellQuote(localAttachDir)
        + " -type f -exec chmod 600 {} + 2>/dev/null; true"]
      secureProcess.running = true
    }
  }

  // ------------------------------------------------------------ persist
  // Snapshot-only write: publishes shared notes WITHOUT touching
  // notes.json. Used when sync turns on, so configuring Setup can never
  // rewind the local notes file (it only ever announces current memory).
  // Remembers the last announced name: after a device rename the stale
  // <old-name>.json is removed so it can never resurface as a "peer".
  property string lastSnapshotId: ""
  function writeSnapshot() {
    if (!syncConfigured || syncSnapshotPath === "") return
    if (lastSnapshotId !== "" && lastSnapshotId !== myId) {
      queueGc(["bash", "-c", "rm -f " + shellQuote(syncDir + "/" + lastSnapshotId + ".json") + " 2>/dev/null; true"])
    }
    lastSnapshotId = myId
    var shared = localNotes.filter(function (n) { return n && n.shared === true })
    var snapshot = JSON.stringify({ version: 2, deviceId: myId, updatedAt: Store.nowIso(), notes: shared, noteComments: outbox, deletedIds: deletedIds }, null, 2) + "\n"
    syncSnapshotFile.setText(snapshot)
    mirrorSharedAttachments()
  }
  // Mirror shared notes' sidecars into the synced dot-dir (one guarded
  // batch; cmp avoids rewrite churn that would re-trigger file sync).
  // Without this, peers get metadata with no bytes — hash "bad" forever.
  function mirrorSharedAttachments() {
    if (!syncConfigured) return

    localNotes.forEach(function (n) {
      if (!n || n.shared !== true || !Store.isSafeId(n.id)) return

      ;(n.attachments || []).forEach(function (a) {
        var clean = Store.sanitizeAttachment(a)
        if (!clean) return

        var fileName = clean.id + "-" + clean.name
        queueSafeCopy(
          ownAttachSubdir(n.id) + "/" + fileName,
          syncAttachDir(),
          n.id,
          fileName
        )
      })
    })
  }

  function persist() {
    // A failed load keeps memory intact (see onLoadFailed): never write the
    // local file in that state, or a transient read error would wipe it.
    // Snapshot + publish queue still go out so peers keep current state.
    var payload = JSON.stringify({ version: 2, deviceId: myId, notes: localNotes, outbox: outbox, deletedIds: deletedIds, hidden: Store.sanitizeHidden(hiddenIds) }, null, 2) + "\n"
    if (!localLoadFailed) {
      // Rotate the previous state aside first (skipped on the very first save
      // when nothing was loaded yet) — never overwrites the backup with empty.
      if (lastLocalRaw !== "") notesBakFile.setText(lastLocalRaw)
      localFile.setText(payload)
      lastLocalRaw = payload
    }
    writeSnapshot()
    // Internet publish queue for the built-in sync: shared notes + outbox
    // comments + deletion tombstones. sync.mjs encrypts one copy per
    // --recipients pubkey on publish.
    var job = Store.buildNostrPublish(localNotes, outbox, deletedIds, pendingDeletes)
    nostrPublishFile.setText(JSON.stringify(job, null, 2) + "\n")
    refreshDisplay()
    secureFiles()
  }

  function loadLocal(raw) {
    lastLocalRaw = String(raw || "")
    var notes = []
    var box = []
    var tomb = ({})
    var hid = []
    try {
      var parsed = JSON.parse(String(raw || ""))
      var arr = parsed && Array.isArray(parsed.notes) ? parsed.notes : (Array.isArray(parsed) ? parsed : [])
      arr.forEach(function (n) {
        var clean = Store.sanitizeNote(n)
        if (clean) notes.push(clean)
      })
      box = Store.sanitizeOutbox(parsed && parsed.outbox)
      tomb = Store.sanitizeDeleted(parsed && (parsed.deletedIds || parsed.deleted))
      hid = Store.sanitizeHidden(parsed && parsed.hidden)
      // Device rename migration: every note in this file was authored on
      // this machine, whatever author string it carries. Re-sign stragglers
      // to the current name so Share/Delete keep working and peers qualify
      // the new name. Without this, renaming orphans notes (buttons hide,
      // peers must allow-list the OLD name).
      var nowId = Store.normalizeText(myId)
      if (nowId !== "") {
        var stamp = ""
        notes.forEach(function (n) {
          if (Store.normalizeText(n.author) !== nowId) {
            n.author = nowId
            if (stamp === "") stamp = Store.nowIso()
            n.updatedAt = stamp
          }
        })
      }
    } catch (e) { console.warn("transnote", "Ignoring bad notes file", e) }
    localNotes = Store.filterDeletedNotes(notes, tomb)
    outbox = box.filter(function (entry) { return entry && !Store.isDeleted(tomb, entry.noteId) })
    deletedIds = tomb
    hiddenIds = hid
    // Pending Nostr deletes = all tombstones (reconciled after publish).
    pendingDeletes = Object.keys(tomb)
    localLoaded = true
    localLoadFailed = false
    mergePeers()
  }

  // Re-sign local notes when the device name changes while running: the
  // file migration in loadLocal only runs on load, but Setup saves the new
  // name live. All local notes are this machine's by construction.
  function migrateAuthors() {
    var nowId = Store.normalizeText(myId)
    if (nowId === "" || !localLoaded) return
    var changed = false
    var stamp = ""
    ;(localNotes || []).forEach(function (n) {
      if (n && Store.normalizeText(n.author) !== nowId) {
        n.author = nowId
        if (stamp === "") stamp = Store.nowIso()
        n.updatedAt = stamp
        changed = true
      }
    })
    if (changed) {
      touchLocalNotes()
      persist()
    }
  }

  // Returns { notes: [...], pairs: [{ noteId, comment }], deleted: {...} }.
  function loadPeerSnapshot(raw) {
    var out = []
    var pairs = []
    var tomb = {}
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
      tomb = Store.sanitizeDeleted(parsed && (parsed.deletedIds || parsed.deleted))
    } catch (e) { /* ignore bad peer files */ }
    return { notes: out, pairs: pairs, deleted: tomb }
  }

  function rebuildPeerNotes() {
    var all = []
    var pairs = []
    Object.keys(peerSnapshots).forEach(function (k) {
      var s = peerSnapshots[k]
      if (s) {
        all = all.concat(s.notes || [])
        pairs = pairs.concat(s.pairs || [])
      }
    })
    // LAN snapshots are untrusted peer state. Their tombstones must not
    // modify this machine's local or Nostr deletion state. Local tombstones
    // still suppress matching peer notes on this machine.
    all = Store.filterDeletedNotes(all, deletedIds)
    pairs = pairs.filter(function (entry) { return entry && !Store.isDeleted(deletedIds, entry.noteId) })
    // De-duplicate by note id, newest first; drop notes I authored (mine win).
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var byId = {}
    all.forEach(function (n) {
      if (!n || mine[n.id]) return
      if (!byId[n.id] || n.updatedAt > byId[n.id].updatedAt) byId[n.id] = n
    })
    peerNotes = Object.keys(byId).map(function (k) { return byId[k] })
    var fc = {}
    Object.keys(foreignComments || {}).forEach(function (k) {
      if (!Store.isDeleted(deletedIds, k)) fc[k] = foreignComments[k]
    })
    foreignComments = Store.mergeForeignComments(fc, pairs, allowList, myId)
    var pruned = Store.pruneOutbox(outbox, localNotes, allPeerNotes())
    if (JSON.stringify(pruned) !== JSON.stringify(outbox)) {
      outbox = pruned
      persist()
      peerDebug = "files=" + peerFiles.length + " fetched=" + Object.keys(peerSnapshots).length + " snapNotes=" + all.length + " peerNotes=" + peerNotes.length + " shown=" + displayNotes.length + " (pruned, reloading)"
      return
    }
    refreshDisplay()
    peerDebug = "files=" + peerFiles.length + " fetched=" + Object.keys(peerSnapshots).length + " snapNotes=" + all.length + " peerNotes=" + peerNotes.length + " shown=" + displayNotes.length
  }

  // Internet fetch output (written by the built-in sync, read back here).
  // Already decrypted + author-filtered by sync.mjs; re-filter here too so
  // removing someone hides them immediately. Relay tombstones (kind-5)
  // merge into local deletedIds — delete-wins, no resurrection.
  function loadNostrFetch(raw) {
    root.nostrFetchRaw = String(raw || "")
    var parsed = Store.sanitizeNostrFetch(root.nostrFetchRaw, nostrAllowList, root.myHex, deletedIds)
    if (parsed.tombstones && JSON.stringify(parsed.tombstones) !== JSON.stringify(deletedIds)) {
      deletedIds = Store.mergeDeleted(deletedIds, parsed.tombstones)
      pendingDeletes = Object.keys(deletedIds)
    }
    var mine = {}
    localNotes.forEach(function (n) { if (n) mine[n.id] = true })
    var folderIds = {}
    ;(peerNotes || []).forEach(function (n) { if (n) folderIds[n.id] = true })
    var fresh = parsed.notes.filter(function (n) { return n && !mine[n.id] && !folderIds[n.id] && !Store.isDeleted(deletedIds, n.id) })
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
  // Internet sync uses the fixed system Node.js executable and the
  // committed helper bundle. Runtime package installation is not allowed.
  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'"
  }

  function sanitizedNodeCommand(args) {
    return [envBin, "-i", "HOME=" + home, "PATH=/usr/bin:/bin", nodeBin].concat(args || [])
  }

  function nostrCommand(args) {
    return sanitizedNodeCommand([syncBundle].concat(args || []))
  }

  function updateNetStatus() {
    if (setupStage === "nodecheck" || setupStage === "key") {
      netStatus = "Internet: setting up…"
    } else if (setupStage === "node-missing") {
      netStatus = "Internet: off — install system Node.js"
      setupRetry.restart()
    } else if (setupStage === "setup-failed") {
      netStatus = "Internet: setup failed — retrying"
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
    if (setupStage === "nodecheck") {
      nodeProbe.command = sanitizedNodeCommand(["--version"])
      nodeProbe.running = true
    } else if (setupStage === "key") {
      keyProcess.command = nostrCommand(["ensure-key", "--key-file", keyFile])
      keyProcess.running = true
    } else if (setupStage === "ready") {
      updateNetStatus()
      refilterNostr()
      syncTimer.start()
    }
  }

  function onNodeProbe(exitCode) {
    setupStage = exitCode === 0 ? "key" : "node-missing"
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
        setupStage = "setup-failed"
      }
    } catch (e) {
      setupStage = "setup-failed"
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
      npubConvert.command = nostrCommand(["npub-to-hex", "--npub", input])
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
    pubProcess.command = nostrCommand(["publish",
      "--key-file", keyFile, "--relays", relays,
      "--in", nostrPublishPath, "--recipients", allow.join(",")])
    pubProcess.running = true
  }

  function startFetch() {
    var allow = Store.effectiveNostrAllow(allowList, friends)
    fetchProcess.command = nostrCommand(["fetch",
      "--key-file", keyFile, "--relays", relays,
      "--allow-list", allow.join(","), "--out", nostrFetchPath])
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
    var clean = Store.normalizeText(id)
    if (clean === "") return
    removeAttachDirs(clean, true)
    localNotes = localNotes.filter(function (n) { return n && n.id !== clean })
    peerNotes = (peerNotes || []).filter(function (n) { return n && n.id !== clean })
    nostrPeerNotes = (nostrPeerNotes || []).filter(function (n) { return n && n.id !== clean })
    // Tombstone first: delete-wins on every future merge (LAN + Nostr).
    deletedIds = Store.addTombstone(deletedIds, clean)
    if (pendingDeletes.indexOf(clean) === -1) pendingDeletes = pendingDeletes.concat([clean])
    // Drop comments/outbox/unread state for the deleted note.
    outbox = (outbox || []).filter(function (entry) { return entry && entry.noteId !== clean })
    if (foreignComments && foreignComments[clean]) {
      var fc = {}
      for (var k in foreignComments) { if (k !== clean) fc[k] = foreignComments[k] }
      foreignComments = fc
    }
    if (selectedNoteId === clean) selectedNoteId = ""
    if (unreadIds && unreadIds[clean]) {
      var unread = {}
      for (var u in unreadIds) { if (u !== clean) unread[u] = unreadIds[u] }
      unreadIds = unread
    }
    // A deleted note is never hidden: drop any local hide entry.
    hiddenIds = Store.sanitizeHidden(hiddenIds).filter(function (hid) { return hid !== clean })
    persist()
    // Upload the kind-5 deletion immediately; persist() already queued it.
    // Guard mirrors runSyncCycle: no Nostr recipients or setup incomplete
    // means LAN-only mode, where persist()+writeSnapshot() is sufficient.
    if (setupStage === "ready" && Store.effectiveNostrAllow(allowList, friends).length > 0) startPublish()
  }

  // Dismiss a peer's note on this machine only. Unlike deleteNote (owner
  // deletes for everyone), hiding never publishes anything — the note stays
  // visible to others and reappears here only via Unhide all.
  function hideNote(id) {
    var nid = Store.normalizeText(id)
    if (nid === "" || isLocalNote(nid)) return
    var hid = Store.sanitizeHidden(hiddenIds)
    if (hid.indexOf(nid) === -1) {
      hid.push(nid)
      hiddenIds = hid
      persist()
    } else {
      refreshDisplay()
    }
  }

  function unhideAll() {
    if ((hiddenIds || []).length === 0) return
    hiddenIds = []
    persist()
  }

  function toggleShare(id) {
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === id) {
        // Local notes stay manageable after a device rename: re-sign to the
        // current name when sharing — peers qualify authors, not file names.
        if (Store.normalizeText(localNotes[i].author) !== Store.normalizeText(myId)) {
          localNotes[i].author = Store.normalizeText(myId)
        }
        Store.setShared(localNotes[i], !(localNotes[i].shared === true), "")
        // Unsharing retracts the synced mirror (local bytes stay) AND
        // tombstones the note so peers drop their copy and Nostr relays
        // serve the kind-5 deletion instead of the old ciphertext.
        if (!(localNotes[i].shared === true)) {
          queueSafeRemove(syncAttachDir(), id)
          localNotes[i].updatedAt = Store.nowIso()
          deletedIds = Store.addTombstone(deletedIds, id)
          if (pendingDeletes.indexOf(id) === -1) pendingDeletes = pendingDeletes.concat([id])
        } else {
          // Re-sharing clears the tombstone so the live note wins again.
          localNotes[i].updatedAt = Store.nowIso()
          var kept = {}
          for (var k in (deletedIds || {})) { if (k !== id) kept[k] = deletedIds[k] }
          deletedIds = kept
          pendingDeletes = (pendingDeletes || []).filter(function (pid) { return pid !== id })
        }
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
  function isLocalNote(id) {
    for (var i = 0; i < localNotes.length; i++) {
      if (localNotes[i] && localNotes[i].id === id) return true
    }
    return false
  }
  // Deletable: own LAN notes plus own Nostr copies (authorHex == myHex).
  // Peer notes stay author-gated — only the author can tombstone them.
  function isDeletable(note) {
    if (!note || !note.id) return false
    if (isLocalNote(note.id)) return true
    if (note.author === myId) return true
    if (myHex !== "" && Store.normalizeText(note.author).toLowerCase() === Store.normalizeText(myHex).toLowerCase()) return true
    return false
  }
  // Per-note attach-row toggle (paperclip in the comment row). Closed by
  // default: the quiet UI shows one action row per note, details on demand.
  property var attachOpen: ({})
  function toggleAttachRow(noteId) {
    var m = {}
    for (var k in attachOpen) m[k] = attachOpen[k]
    if (m[noteId]) {
      delete m[noteId]
      if (focusAttachFor === noteId) focusAttachFor = ""
    }
    else m[noteId] = true
    attachOpen = m
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
    // A failed first read (missing file = fresh install) starts empty;
    // a failed LATER read keeps memory so a transient error can never
    // wipe notes.json — persist() also skips the local write while failed.
    onLoadFailed: {
      if (!root.localLoaded && (root.localNotes || []).length === 0) {
        root.localNotes = []
        root.outbox = []
        root.deletedIds = ({})
        root.hiddenIds = []
        root.lastLocalRaw = ""
      } else {
        root.localLoadFailed = true
      }
      root.localLoaded = true
      root.refreshDisplay()
    }
    onFileChanged: reload()
  }

  // Previous-state backup of notes.json (written by persist, never watched).
  FileView {
    id: notesBakFile
    path: root.notesBakPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
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

  // Folder-merge diagnostics for troubleshooting without log access.
  // Written whenever peerDebug changes; safe to cat from a terminal.
  FileView {
    id: peerDebugFile
    path: root.dataDir + "/folder_debug.json"
    watchChanges: false
    atomicWrites: true
    printErrors: false
  }

  // ---- background workers for internet setup + sync (no terminal) ----
  Process {
    id: nodeProbe
    running: false
    onExited: function (exitCode) { root.onNodeProbe(exitCode) }
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

  // Clipboard staging file for note copy (written, then wl-copy reads it).
  FileView {
    id: clipboardFile
    path: root.clipboardStagingPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
  }

  // Short pause so the staging file is on disk before wl-copy reads it.
  Timer {
    id: copyDelay
    interval: 600
    repeat: false
    onTriggered: {
      noteCopyProcess.command = ["bash", "-c", "wl-copy < " + shellQuote(clipboardStagingPath)]
      noteCopyProcess.running = true
    }
  }

  Process {
    id: noteCopyProcess
    running: false
    onExited: function (exitCode) {
      if (exitCode === 0) { root.copiedNoteId = root.pendingCopyNoteId; root.copyFailedId = "" }
      else { root.copyFailedId = root.pendingCopyNoteId; root.copiedNoteId = "" }
    }
  }

  // Attachment stage+hash (stdout parsed by onAttachOutput).
  Process {
    id: attachProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.onAttachOutput(text, 0)
    }
    onExited: function (exitCode) {
      // Crashed run with no stdout: context unknown, so only clear + flag
      // in-flight notes. A concurrent healthy run overwrites this with its
      // own outcome when its stdout lands.
      if (exitCode !== 0) {
        for (var k in root.attachActive) {
          root.setAttachBusy(k, false)
          root.setAttachMsg(k, "Attach interrupted — try again.")
        }
        root.attachActive = ({})
      }
    }
  }

  // Fire-and-forget sidecar cleanup (queued via queueGc/flushGc so
  // bursts of deletes never overwrite each other).
  Process {
    id: gcProcess
    running: false
    onExited: root.flushGc()
  }

  // Peer attachment hash verification (stdout parsed by applyVerifyOutput).
  Process {
    id: verifyProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyVerifyOutput(text)
    }
  }

  // Path completion engine (see requestComplete): debounced compgen lookup
  // shared by every path field. currentTarget/Partial carry the request the
  // running process answers (declared props — QML forbids expando).
  Timer {
    id: completeDebounce
    interval: 200
    repeat: false
    onTriggered: root.runComplete()
  }

  Process {
    id: completeProcess
    property string currentTarget: ""
    property string currentPartial: ""
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyComplete(text)
    }
  }

  // Save one attachment to ~/Downloads (stdout parsed by onSaveOutput).
  Process {
    id: saveProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.onSaveOutput(text, 0)
    }
    onExited: function (exitCode) {
      if (exitCode !== 0 && root.savePendingNote !== "") root.onSaveOutput("", exitCode)
    }
  }

  // Explicit system-handler open (stdout parsed by onOpenOutput).
  Process {
    id: openProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.onOpenOutput(text)
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
    id: pairingProcess
    property string action: ""
    property string output: ""
    property string errorOutput: ""
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: pairingProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: pairingProcess.errorOutput = text
    }
    onExited: function (exitCode) {
      var actionNow = action
      var outputNow = output
      var errorNow = errorOutput
      Qt.callLater(function () {
        root.finishPairingAction(exitCode, actionNow, outputNow, errorNow)
      })
    }
  }

  Process {
    id: pairingStatusProcess
    property string output: ""
    property string errorOutput: ""
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: pairingStatusProcess.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: pairingStatusProcess.errorOutput = text
    }
    onExited: function (exitCode) {
      var outputNow = output
      var errorNow = errorOutput
      Qt.callLater(function () {
        root.applyPairingStatus(exitCode, outputNow, errorNow)
      })
    }
  }

  Process {
    id: pairingCopyProcess
    running: false
    onExited: function (exitCode) {
      root.pairingMessage = exitCode === 0 ? "Setup code copied." : "Copy failed — select the setup code manually."
    }
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

  // Retry setup later if system Node.js was missing or setup failed.
  Timer {
    id: setupRetry
    interval: 120000
    repeat: false
    onTriggered: {
      if (root.setupStage !== "setup-failed" && root.setupStage !== "node-missing") return
      root.setupStage = "nodecheck"
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
    var listing = String(output || "")
    if (listing.indexOf("===TRANSNOTE_PEER_LIST_OVERFLOW===") !== -1) {
      peerFiles = []
      peerDebug = "peer scan rejected: too many JSON files"
      fetchPeerSnapshots()
      return
    }
    var files = []
    var own = myId + ".json"
    listing.split("\n").forEach(function (line) {
      var name = line.trim()
      if (name.slice(-5) !== ".json" || name === own) return
      if (Store.isSyncArtifact(name)) return
      files.push(syncDir + "/" + name)
    })
    files.sort()
    if (JSON.stringify(files) !== JSON.stringify(peerFiles)) peerFiles = files
    // Marker so the debug file shows scan state even if no delegate ever
    // reports back (rebuildPeerNotes overwrites this with full detail).
    if (peerDebug === "" && files.length > 0) peerDebug = "listed " + files.length + " file(s), waiting for load…"
    // Content follows the listing: a new file is fetched immediately,
    // changed content is re-fetched on every poll tick.
    fetchPeerSnapshots()
  }

  function rescanPeers() {
    if (!syncConfigured) { peerFiles = []; return }
    if (!peerListProcess.running) {
      var listScript = "count=0; overflow=0; "
        + "while IFS= read -r name; do "
        + "count=$((count + 1)); "
        + "if [ \"$count\" -gt " + maxPeerFiles + " ]; then overflow=1; break; fi; "
        + "printf '%s\\n' \"$name\"; "
        + "done < <(/usr/bin/find " + shellQuote(syncDir) + " -maxdepth 1 -type f -name '*.json' -printf '%f\\n' 2>/dev/null); "
        + "if [ \"$overflow\" -ne 0 ]; then printf '%s\\n' '===TRANSNOTE_PEER_LIST_OVERFLOW==='; fi"
      peerListProcess.command = ["bash", "-c", listScript]
      peerListProcess.running = true
    }
  }

  // Peer snapshots keyed by file path. Filled by fetchPeerSnapshots()
  // (Process + cat) rather than a FileView-per-peer delegate: FileView
  // loads inside Instantiator delegates proved unreliable (stuck pending),
  // while Process stdout delivery works everywhere in this panel.
  property var peerSnapshots: ({})

  function fetchPeerSnapshots() {
    if (peerFetchProcess.running) return
    if (!syncConfigured || peerFiles.length === 0) {
      if (Object.keys(peerSnapshots).length > 0) {
        peerSnapshots = ({})
        rebuildPeerNotes()
      }
      refreshAttachmentStates()
      return
    }
    if (peerFiles.length > maxPeerFiles) {
      peerFiles = []
      peerDebug = "peer fetch rejected: too many JSON files"
      return
    }

    var command = [
      envBin,
      "-i",
      "/usr/bin/python3",
      secureRemoveHelper,
      "peer-read",
      syncDir,
      String(maxPeerFileBytes),
      String(maxPeerAggregateBytes)
    ]

    peerFiles.forEach(function (p) {
      command.push(String(p).split("/").pop())
    })

    peerFetchProcess.command = command
    peerFetchProcess.running = true
  }

  function applyPeerFetch(output) {
    var chunks = {}
    var idx = -1
    var buf = []
    String(output || "").split("\n").forEach(function (line) {
      var m = line.match(/^===TRANSNOTEPEER:(\d+)===$/)
      if (m) {
        if (idx >= 0) chunks[idx] = buf.join("\n")
        idx = parseInt(m[1], 10)
        buf = []
      } else if (idx >= 0) {
        buf.push(line)
      }
    })
    if (idx >= 0) chunks[idx] = buf.join("\n")
    var next = {}
    peerFiles.forEach(function (p, i) {
      var c = chunks[i]
      if (c === undefined || c.trim() === "" || c.trim().indexOf("REJECTED:") === 0) return
      next[p] = root.loadPeerSnapshot(c)
    })
    var snapshotsChanged = JSON.stringify(next) !== JSON.stringify(peerSnapshots)
    if (snapshotsChanged) {
      peerSnapshots = next
      // A changed peer snapshot invalidates authorization for previous
      // trusted copies. Verification restores "ok" for current metadata.
      verifiedAtts = ({})
    }
    rebuildPeerNotes()
    refreshAttachmentStates()
  }

  Process {
    id: peerFetchProcess
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyPeerFetch(text)
    }
  }

  Timer {
    id: peerPoll
    interval: 15000
    repeat: true
    running: root.syncConfigured
    onTriggered: { root.rescanPeers(); root.fetchPeerSnapshots() }
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
    // Internet checks fixed system Node.js, then initializes the
    // committed helper bundle. Local and LAN operation do not depend on it.
    wlProbe.command = ["bash", "-c", "command -v wl-copy || true"]
    wlProbe.running = true
    setupStage = "nodecheck"
    setupStep()
  }

  onAllowListChanged: { root.refilterNostr(); root.updateNetStatus() }
  onMyIdChanged: root.migrateAuthors()
  onDisplayNotesChanged: {
    if (noteCursor >= displayNotes.length) noteCursor = displayNotes.length - 1
  }
  onOpenedChanged: { if (opened) root.markAllRead() }
  onMyHexChanged: { root.refilterNostr(); root.updateNetStatus() }
  onFriendsChanged: { root.refilterNostr(); root.updateNetStatus() }

  onSyncConfiguredChanged: {
    if (syncConfigured) {
      syncStatus = "Sync on: " + syncDir
      rescanPeers()      // Snapshot-only (never touches notes.json): configuring Setup
      // announces current notes immediately instead of leaving an empty
      // folder until the next note edit. Guarded by localLoaded so a
      // settings update before first load writes nothing at all.
      if (localLoaded) writeSnapshot()
    }
    else { syncStatus = "Local only — set syncDir to share"; peerFiles = [] }
  }

  onPeerDebugChanged: {
    if (peerDebug !== "") peerDebugFile.setText(peerDebug + "\n")
  }

  // ---------------------------------------------------------------- IPC
  IpcHandler {
    target: "aridev1.transnote"
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

  // Subtle unread signal: a small dot in the icon corner while fresh notes
  // wait (cleared on open). The icon glyph itself stays untouched.
  Rectangle {
    visible: root.hasUnread
    width: Style.space(8)
    height: Style.space(8)
    radius: Style.space(8) / 2
    color: bar ? bar.urgent : Color.urgent
    anchors.right: button.right
    anchors.top: button.top
    anchors.rightMargin: Style.space(2)
    anchors.topMargin: Style.space(2)
    z: 10
  }

  // -------------------------------------------------------------- panel
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(480))
    // Responsive card: hugs content, grows with it up to the cap, and the
    // shell clamps it to the actual screen (availableCardHeight) — so short
    // screens never overflow and tall screens show more notes.
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(760))

    // Whole-card scroll (stock pattern): the card hugs content up to the
    // cap / screen edge, and anything taller scrolls here — footer included.
    // The notes list below therefore never needs its own cap: it grows
    // naturally and this Flickable is the single scroll region.
    // Keyboard dispatcher (Omarchy idiom): arrows/hjkl move the note
    // cursor, Enter expands, x deletes own notes, c/s/a// act, Esc closes,
    // Tab switches panels. Blocked while typing in any field.
    PanelKeyCatcher {
      anchors.fill: parent
      blocked: root.editing
      onMoveRequested: function (dx, dy) { root.moveCursor(dx, dy) }
      onActivateRequested: root.activateCursor()
      onCloseRequested: root.close()
      onDeleteRequested: root.deleteCursorNote()
      onTabRequested: function (direction) { root.switchPanel(direction) }
      onTextKey: function (t) { root.cursorKey(t) }

    Flickable {
      id: panelFlick
      anchors.fill: parent
      contentWidth: width
      contentHeight: column.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      interactive: contentHeight > height
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    Column {
      id: column
      width: panelFlick.width
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
        visible: (root.hiddenIds || []).length > 0
        width: parent.width
        text: "Hidden notes (" + (root.hiddenIds || []).length + ") — Unhide all"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.unhideAll()
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
        onActiveFocusChanged: root.editing = activeFocus
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
        onActiveFocusChanged: root.editing = activeFocus
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
        // Natural height: the outer card Flickable is the single scroll
        // region, so the list never caps or clips mid-note here. (Width is
        // fixed, so sizing the height from contentHeight cannot loop.)
        height: visible ? Math.max(notesView.contentHeight, Style.space(120)) : 0
        clip: true

        ListView {
          id: notesView
          anchors.fill: parent
          model: root.displayNotes
          clip: true
          spacing: Style.space(6)
          boundsBehavior: Flickable.StopAtBounds
          // Never scrolls itself (height always equals content): all
          // dragging/wheel belongs to the outer card Flickable. Children
          // (buttons, comment fields) still receive clicks normally.
          interactive: false

            delegate: Item {
            required property var modelData
            property var note: modelData
            // Collapsed preview computed in JS (plain short text), so a long
            // note can never overflow its delegate and paint over the footer.
            property var bodyPreview: Store.previewBody(note.body)
            width: ListView.view.width
            height: noteCard.implicitHeight + (((note.color || "") !== "") ? Style.space(12) : 0)
            // Tinted card behind colored notes only; plain notes stay flat
            // on the panel background (the Omarchy-quiet default).
            Rectangle {
              anchors.fill: parent
              radius: 8
              visible: ((note.color || "") !== "")
              color: root.noteTint(note)
            }
            Column {
              id: noteCard
              anchors.fill: parent
              anchors.margins: (((note.color || "") !== "") ? Style.space(6) : 0)
              spacing: Style.space(4)

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            Text {
              id: noteTitleText
              Layout.fillWidth: true
              Layout.minimumWidth: 0
              text: (note.shared === true ? "◉ " : "○ ") + note.title
              // Keyboard cursor: title takes the accent color instead of a
              // bar widget (keeps the row free of layout intruders).
              color: root.cursorOn(note.id) ? Color.accent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              font.underline: titleHover.containsMouse
              maximumLineCount: 1
              elide: Text.ElideRight
              // The headline itself toggles expand/collapse (drag-scroll
              // still works: the outer Flickable may steal the gesture).
              MouseArea {
                id: titleHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                acceptedButtons: Qt.LeftButton
                onClicked: root.toggleExpanded(note.id)
              }
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
            Text {
              visible: !!root.unreadIds[note.id]
              text: "• new"
              color: Color.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              maximumLineCount: 1
            }
            // Quiet actions: icon-only, tooltips on hover. Share/Delete act
            // on all local notes (not just author === myId) so a device
            // rename can never trap notes; Delete additionally covers own
            // Nostr copies; Hide dismisses other peers' notes locally
            // without affecting anyone else. Explicit touch targets:
            // icon-only buttons must not rely on implicit sizing.
            Button {
              visible: root.isLocalNote(note.id)
              Layout.preferredWidth: Style.space(28)
              Layout.preferredHeight: Style.space(28)
              iconText: String.fromCodePoint(0xF0474)
              tooltipText: note.shared === true ? "Unshare" : "Share"
              foreground: root.foreground
              fontFamily: root.fontFamily
              selected: note.shared === true
              onClicked: root.toggleShare(note.id)
            }
            Button {
              Layout.preferredWidth: Style.space(28)
              Layout.preferredHeight: Style.space(28)
              iconText: root.copiedNoteId === note.id ? String.fromCodePoint(0xF012C) : String.fromCodePoint(0xF018F)
              tooltipText: root.copyFailedId === note.id ? "Copy failed" : (root.copiedNoteId === note.id ? "Copied!" : "Copy note")
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.copyNoteFull(note)
            }
            Button {
              visible: root.isDeletable(note)
              Layout.preferredWidth: Style.space(28)
              Layout.preferredHeight: Style.space(28)
              iconText: String.fromCodePoint(0xF0194)
              tooltipText: "Delete (everywhere)"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.deleteNote(note.id)
            }
            Button {
              visible: !root.isDeletable(note)
              Layout.preferredWidth: Style.space(28)
              Layout.preferredHeight: Style.space(28)
              iconText: String.fromCodePoint(0xF06D1)
              tooltipText: "Hide (this machine only)"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.hideNote(note.id)
            }
            Button {
              visible: root.isLocalNote(note.id)
              Layout.preferredWidth: Style.space(28)
              Layout.preferredHeight: Style.space(28)
              iconText: String.fromCodePoint(0xF03B2)
              tooltipText: (note.color || "") !== "" ? "Note color (" + note.color + ")" : "Note color"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.cycleColor(note.id)
            }
          }
          // Body renders as segments: prose as usual, ```fenced code blocks
          // monospace + no-wrap in a horizontal scroller with language label
          // and per-block copy. Collapsed notes show the plain preview.
          Column {
            width: parent.width
            visible: note.body !== ""
            spacing: Style.space(4)
            property var segments: {
              var raw = root.isExpanded(note.id) ? Store.parseSegments(note.body) : [{ type: "text", lang: "", content: bodyPreview.text }]
              var ci = 0
              return raw.map(function (s) {
                if (s && s.type === "code") s.key = note.id + "#b" + (ci++)
                return s
              })
            }
            Repeater {
              model: parent.segments
              delegate: Column {
                required property var modelData
                width: parent.width
                spacing: Style.space(4)
                Text {
                  visible: modelData.type !== "code"
                  width: parent.width
                  text: modelData.content
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  wrapMode: Text.WrapAnywhere
                }
                Column {
                  visible: modelData.type === "code"
                  width: parent.width
                  spacing: Style.space(4)
                  RowLayout {
                    width: parent.width
                    spacing: Style.space(6)
                    Text {
                      Layout.fillWidth: true
                      Layout.minimumWidth: 0
                      text: modelData.lang !== "" ? modelData.lang : "code"
                      color: Qt.darker(root.foreground, 1.4)
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      maximumLineCount: 1
                      elide: Text.ElideRight
                    }
                    Button {
                      property string blockKey: modelData.key || note.id
                      iconText: root.copiedNoteId === blockKey ? String.fromCodePoint(0xF012C) : String.fromCodePoint(0xF018F)
                      tooltipText: root.copyFailedId === blockKey ? "Copy failed" : (root.copiedNoteId === blockKey ? "Copied!" : "Copy code block")
                      foreground: root.foreground
                      fontFamily: root.fontFamily
                      onClicked: root.copyRawText(modelData.content, blockKey)
                    }
                  }
                  ScrollView {
                    width: parent.width
                    height: Math.min(codeText.implicitHeight, Style.space(220))
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded
                    Text {
                      id: codeText
                      text: modelData.content
                      font.family: "monospace"
                      font.pixelSize: Style.font.body
                      color: root.foreground
                      wrapMode: Text.NoWrap
                    }
                  }
                }
              }
            }
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
          // Attachments: kind rendering (image/text/file) with verified
          // badges for peers, Save/Open actions, and the attach row on
          // own notes. Bytes sync as sidecars; metadata rides the note.
          Column {
            width: parent.width
            visible: root.cleanAttachments(note).length > 0
            spacing: Style.space(4)
            Repeater {
              model: root.cleanAttachments(note)
              delegate: Column {
                required property var modelData
                property var att: modelData
                property string attKey: note.id + "/" + att.id
                property string attPath: root.attPathFor(note, att)
                property bool isOwn: root.isLocalNote(note.id)
                property string attState: isOwn ? "own" : (root.verifiedAtts[attKey] || "checking")
                property string stateLabel: attState === "own" ? "on this machine"
                  : attState === "ok" ? "verified ✓"
                  : attState === "bad" ? "hash mismatch!"
                  : attState === "waiting" ? "syncing…" : "checking…"
                width: parent.width
                spacing: Style.space(4)
                Image {
                  visible: att.kind === "image" && (isOwn || attState === "ok")
                  width: parent.width
                  height: Style.space(180)
                  fillMode: Image.PreserveAspectFit
                  asynchronous: true
                  cache: false
                  // Empty source unless this is a verified image: QML loads
                  // source even while invisible, so an audio/file attachment
                  // would otherwise spam "Unsupported image format" errors.
                  source: att.kind === "image" ? root.attUrl(attPath) : ""
                }
                Text {
                  visible: att.kind === "text" && root.attPeeks[attKey] !== undefined && root.attPeeks[attKey] !== ""
                  width: parent.width
                  text: root.peekLines(attKey)
                  font.family: "monospace"
                  font.pixelSize: Style.font.caption
                  color: root.foreground
                  wrapMode: Text.WrapAnywhere
                }
                // Peek loader for text attachments (single-file reads are
                // reliable; watch picks up late-synced bytes).
                FileView {
                  path: att.kind === "text" ? attPath : ""
                  watchChanges: true
                  printErrors: false
                  onLoaded: root.setAttPeek(attKey, text())
                  onLoadFailed: root.setAttPeek(attKey, "")
                  onFileChanged: reload()
                }
                RowLayout {
                  width: parent.width
                  spacing: Style.space(6)
                  Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: "📎 " + att.name + " (" + root.formatSize(att.size) + ") · " + stateLabel
                    color: attState === "bad" ? Color.urgent : Qt.darker(root.foreground, 1.4)
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    maximumLineCount: 1
                    elide: Text.ElideRight
                  }
                  Button {
                    iconText: String.fromCodePoint(0xF01DA)
                    tooltipText: "Save to Downloads"
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    onClicked: root.saveAttachment(note, att)
                  }
                  Button {
                    iconText: String.fromCodePoint(0xF02FA)
                    tooltipText: "Open"
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    onClicked: root.openAttachment(note, att)
                  }
                  Button {
                    visible: isOwn
                    text: "×"
                    tooltipText: "Remove attachment"
                    foreground: root.foreground
                    fontFamily: root.fontFamily
                    onClicked: root.removeAttachment(note.id, att.id)
                  }
                }
              }
            }
          }
          // Attach row on own notes, behind the 📎 toggle: paste a path,
          // staged + hashed locally.
          // Path completion included (Tab completes, click accepts).
          RowLayout {
            visible: root.isLocalNote(note.id) && !!root.attachOpen[note.id]
            width: parent.width
            spacing: Style.space(6)
            TextField {
              id: attachPathField
              Layout.fillWidth: true
              Layout.minimumWidth: 0
              placeholderText: "Attach file path… (Tab completes)"
              foreground: root.foreground
              text: root.attachPaths[note.id] || ""
              onTextChanged: {
                var m = {}
                for (var k in root.attachPaths) m[k] = root.attachPaths[k]
                m[note.id] = text
                root.attachPaths = m
                root.requestComplete(note.id, text, false)
              }
              onAccepted: { root.clearCompletion(); root.attachFile(note.id, text) }
              onActiveFocusChanged: root.editing = activeFocus
              Keys.onTabPressed: function (event) {
                if (root.completeCommonPrefix(note.id)) event.accepted = true
              }
              Keys.onEscapePressed: root.clearCompletion()
              Connections {
                target: root
                function onFocusAttachForChanged() {
                  if (root.focusAttachFor === note.id && root.attachOpen[note.id]) attachPathField.forceActiveFocus()
                }
              }
            }
            Button {
              text: root.attachBusy[note.id] ? "…" : "Attach"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: { root.clearCompletion(); root.attachFile(note.id, root.attachPaths[note.id] || "") }
            }
          }
          // Path suggestions for this note's attach field.
          Column {
            width: parent.width
            visible: root.isLocalNote(note.id) && root.completeFor === note.id && root.completeResults.length > 0 && attachPathField.activeFocus
            spacing: Style.space(2)
            Repeater {
              model: root.completeResults
              delegate: Button {
                required property var modelData
                width: parent.width
                text: "▸ " + root.shortCompletePath(modelData)
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: {
                  root.acceptCompletion(note.id, modelData)
                  attachPathField.forceActiveFocus()
                }
              }
            }
          }
          Text {
            width: parent.width
            visible: (root.attachMsg[note.id] || "") !== ""
            text: root.attachMsg[note.id] || ""
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WrapAnywhere
          }
          RowLayout {
            width: parent.width
            spacing: Style.space(6)
            // Comment box on every note: own notes store inline, peer notes
            // go through the sync outbox.
            TextField {
              id: commentField
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
              onActiveFocusChanged: root.editing = activeFocus
            }
            // Attach toggle (own notes keep it quiet until needed).
            Button {
              visible: root.isLocalNote(note.id)
              text: "📎"
              tooltipText: root.attachOpen[note.id] ? "Hide attach row" : "Attach a file"
              foreground: root.foreground
              fontFamily: root.fontFamily
              selected: !!root.attachOpen[note.id]
              onClicked: root.toggleAttachRow(note.id)
            }
          }
            PanelSeparator { foreground: root.foreground; width: parent.width }
            } // noteCard Column
          } // delegate Item
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
        onActiveFocusChanged: root.editing = activeFocus
      }
      TextField {
        id: friendNameField
        width: parent.width
        visible: root.setupStage === "ready"
        placeholderText: "Name (optional, e.g. Anna)…"
        foreground: root.foreground
        onTextChanged: root.friendName = text
        onAccepted: root.addFriendFromInput()
        onActiveFocusChanged: root.editing = activeFocus
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
        text: "Device sync"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }
      Text {
        width: parent.width
        text: "This computer: " + root.pairingDeviceId()
        color: root.foreground
        opacity: 0.75
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Button {
        width: parent.width
        text: root.pairingBusy ? "Working…" : "Start new sync"
        enabled: !root.pairingBusy
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.preparePairing()
      }
      Text {
        width: parent.width
        text: "Your setup code"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      RowLayout {
        width: parent.width
        spacing: Style.space(6)
        TextField {
          id: pairingCodeField
          Layout.fillWidth: true
          Layout.minimumWidth: 0
          readOnly: true
          placeholderText: "Select Start new sync first"
          foreground: root.foreground
          text: root.pairingCode
          onActiveFocusChanged: root.editing = activeFocus
        }
        Button {
          text: "Copy code"
          enabled: root.pairingCode !== ""
          foreground: root.foreground
          fontFamily: root.fontFamily
          bordered: true
          onClicked: root.copyPairingCode()
        }
      }
      Text {
        width: parent.width
        text: "Join existing sync"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      TextField {
        id: incomingPairingField
        width: parent.width
        placeholderText: "Paste TransNote setup code"
        foreground: root.foreground
        text: root.incomingPairingCode
        onTextChanged: root.incomingPairingCode = text
        onAccepted: root.connectPairing()
        onActiveFocusChanged: root.editing = activeFocus
      }
      Button {
        width: parent.width
        text: "Connect"
        enabled: !root.pairingBusy && Store.normalizeText(root.incomingPairingCode) !== ""
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.connectPairing()
      }
      Text {
        visible: root.pairingPendingDevices.length > 0
        width: parent.width
        text: "Pending computer connections"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      Repeater {
        model: root.pairingPendingDevices
        delegate: RowLayout {
          required property var modelData
          width: parent ? parent.width : 0
          Text {
            Layout.fillWidth: true
            text: Store.normalizeText(modelData.deviceName) !== ""
              ? modelData.deviceName
              : String(modelData.syncthingDeviceId || "").slice(0, 7) + "…"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
          Button {
            text: "Accept"
            enabled: !root.pairingBusy
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: root.acceptPairingDevice(modelData.syncthingDeviceId)
          }
        }
      }
      Text {
        visible: root.pairingPendingOffers.length > 0
        width: parent.width
        text: "Pending TransNote folders"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      Repeater {
        model: root.pairingPendingOffers
        delegate: RowLayout {
          required property var modelData
          width: parent ? parent.width : 0
          Text {
            Layout.fillWidth: true
            text: Store.normalizeText(modelData.deviceName) !== ""
              ? modelData.deviceName + " · " + modelData.folderId
              : modelData.folderId
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
          Button {
            text: "Accept"
            enabled: !root.pairingBusy
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: root.acceptPairingFolder(modelData.folderId, modelData.syncthingDeviceId)
          }
        }
      }
      Text {
        width: parent.width
        text: "Connected computers"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        text: root.pairingPeers.length === 0
          ? "No computers connected yet."
          : root.pairingPeers.map(function (p) {
              var state = p.connected === true ? "connected" : (p.configured === true ? "configured" : "not ready")
              return p.transnoteDeviceId + " (" + state + ")"
            }).join(", ")
        color: root.foreground
        opacity: 0.72
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        text: root.pairingMessage
        color: root.foreground
        opacity: 0.72
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Text {
        width: parent.width
        text: "Advanced / manual setup"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
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
          onActiveFocusChanged: root.editing = activeFocus
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
        visible: root.setupForeignAuthors.length > 0
        text: "Heads up: your existing notes are signed as '" + root.setupForeignAuthors.join(", ") + "'. Renaming re-signs them automatically, but friends must allow the new name. Prefer keeping the name."
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
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
        placeholderText: "~/transnote-lan… (Tab completes)"
        foreground: root.foreground
        text: root.setupDir
        onTextChanged: { root.setupDir = text; root.checkSetupFolder(); root.requestComplete("setup", text, true) }
        onAccepted: { root.clearCompletion(); root.saveSetupDir() }
        onActiveFocusChanged: root.editing = activeFocus
        Keys.onTabPressed: function (event) {
          if (root.completeCommonPrefix("setup")) event.accepted = true
        }
        Keys.onEscapePressed: root.clearCompletion()
      }
      // Path suggestions (folders only), click to accept.
      Column {
        width: parent.width
        visible: root.completeFor === "setup" && root.completeResults.length > 0 && setupDirField.activeFocus
        spacing: Style.space(2)
        Repeater {
          model: root.completeResults
          delegate: Button {
            required property var modelData
            width: parent.width
            text: "▸ " + root.shortCompletePath(modelData)
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: {
              root.acceptCompletion("setup", modelData)
              setupDirField.forceActiveFocus()
            }
          }
        }
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
          onActiveFocusChanged: root.editing = activeFocus
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
      Text {
        width: parent.width
        text: root.peerFiles.length > 0
          ? "Peer files seen here (" + root.peerFiles.length + "): " + root.peerFiles.map(function (p) { return String(p).split("/").pop() }).join(", ")
          : "No peer files here yet — if the other machine already pressed Save, the two folders are not linked (check Syncthing/sshfs below)."
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
      Button {
        text: "Check for peers now"
        foreground: root.foreground
        fontFamily: root.fontFamily
        bordered: true
        onClicked: root.rescanPeers()
      }
      Text {
        width: parent.width
        visible: root.peerDebug !== ""
        text: "Diagnostics: " + root.peerDebug
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
        text: "Sharing with: " + (root.nostrAllowList.length > 0 ? root.nostrAllowList.map(function (h) { return root.shortAuthor(h) }).join(", ") : "(nobody yet)") + (root.pluginVersion !== "" ? " · v" + root.pluginVersion : "")
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WrapAnywhere
      }
    } // column
    } // panelFlick
    } // keyCatcher
  }
}
