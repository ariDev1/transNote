# TransNote — shared text notes for the Omarchy bar

Write notes, share them with qualified friends, read and comment.
Works locally, over a shared folder (Syncthing/Dropbox/rsync), and over the
internet (encrypted). Attachments are planned, not yet built.

No terminal needed — everything happens in the panel.

## How sharing works

| Path | Transport | Who can read |
|------|-----------|--------------|
| Local | This machine only | You |
| Folder sync | Shared folder, one `<deviceId>.json` per machine | Device ids on your `allowList` |
| Internet sync | Relays, end-to-end encrypted | Friends you added in the panel |

Relays only ever see ciphertext — never your text. Removing someone stops
future notes (old ciphertext stays on relays but is unreadable to them).
Internet notes show a 🌐 badge.

## Use it

1. Open TransNote in the bar and write a note. Press **Share** on it.
2. To share on your local network (folder sync, works offline) — no terminal needed:
   - Open TransNote in the bar → **Setup** tab.
   - **1 — Name this machine** (e.g. `laptop`), press **Save**.
   - **2 — Shared folder**: enter `~/transnote-lan`, press **Create folder**,
     then **Save folder**. Sync that folder between the machines with
     Syncthing (recommended), Dropbox, or for a quick test with SSH:
     `sshfs <user>@<other-ip>:/home/<user>/transnote-lan ~/transnote-lan`
   - **3 — Who can read**: enter every machine name, comma-separated
     (e.g. `laptop,desktop`), press **Save**.
    - Repeat on the other machine (other name, same folder, same list).
      Keep names stable afterwards: notes are signed with the name active
      when created — renaming hides their Share/Delete buttons and forces
      everyone to allow-list the old name too (the Setup tab warns you).
    - Check the footer: `Local only — set syncDir to share` means step 2 is
      still open. `Sync on: ~/transnote-lan` means folder sync is active.
      After pressing **Share** on a note, your `<deviceId>.json` appears in
      the folder and shows up on the peer within ~15 seconds.
    - Setup also reports **Peer files seen here (N)** plus a **Diagnostics**
      line (`files=… fetched=… snapNotes=… peerNotes=… shown=…`) and a
      **Check for peers now** button — the fastest way to see whether the
      other side's file even arrives.
   - Expert fallback: the same three values live in
     `~/.config/omarchy/shell.json` in the `"id": "rene.transnote"` entry
     (`deviceId`, `syncDir`, `allowList`) — or via
     `omarchy bar set rene.transnote <key> <value>`. The Setup tab writes
     through that same official command.
3. To share over the internet:
   - Copy **your code** in the panel (SHARE OVER INTERNET section) and send
     it to a friend — message, email, anything.
   - Paste the code your friend sends back under **Add a friend**, give them
     a name, press **Add friend**.
4. That's it. Shared notes sync by themselves about once a minute
   (or press **Sync now**). Your friend's notes appear marked with 🌐,
   and you can comment on them. Every note has a **Copy** button that puts
   its title + body on the clipboard (no fiddly text selection needed).
   Fresh arrivals show a **• new** pill and a dot on the bar icon until
   you open the panel. The panel grows with your notes and scrolls as one
   card when content exceeds the screen.

The first time, the panel sets everything up by itself (about a minute:
it prepares the sync helper and creates your private key, which stays on
your machine). The status line always tells you what is happening
(`setting up…`, `on (2 friends)`, `couldn't reach friends — will retry`).

## Safety notes

- Your private key file (`~/.local/share/transnote/nostr_key`) is **secret**,
  like a password. Never share it — only your code.
- Notes default to **private**. Nothing leaves the machine until you press
  **Share** *and* added a friend.
- The sync refuses to publish without recipients (no accidental public posts).
- Colleagues on the same machine cannot read your notes: the panel locks
  its data folder to owner-only (`700`) and every file it writes
  (notes, friends, key, sync queue, downloads) to owner-only (`600`) on
  every save. Folder sync is the exception — its snapshot is also locked
  down, but anyone you admit to the shared folder can read what you Share
  there, so keep the folder itself non-shared. For sensitive notes prefer
  internet sharing (end-to-end encrypted).

## Install on another machine (friends & family)

The `rene.` in the name is just the publisher name (like a brand) — the
plugin works under any username on any machine. Nothing is hardcoded.

The repo is private, so first give your friend access (GitHub → repo
Settings → Collaborators → add them). Then on their machine:

```bash
omarchy plugin add https://github.com/ariDev1/transNote.git --enable
omarchy restart shell
```

Open TransNote in the bar — the first launch sets everything up by itself.
Then exchange codes (panel → SHARE OVER INTERNET) and add each other.

If the panel says it needs Node.js:

```bash
omarchy pkg add nodejs npm
omarchy restart shell
```

## Updates

When a new version is out, on each machine:

```bash
omarchy plugin update rene.transnote
omarchy restart shell
```

Check you're current: the panel footer ends with `· vX.Y.Z`.

## If shared notes don't appear

Work down this list — it covers every failure seen in real LAN testing:

1. **Are the folders actually linked?** Setup only creates a *local* folder.
   Prove the link past TransNote: `touch ~/transnote-lan/link-test.txt`
   on machine A — it must appear on machine B within a minute, and vice
   versa. If not, fix Syncthing/sshfs first (folder shared + accepted on
   both sides, status Up to Date). Nothing else matters until this works.
2. **Did the peer write its snapshot?** Its `<deviceId>.json` must exist in
   the folder with your note inside (`shared: true`). Saving Setup writes
   it immediately on current versions — on old versions, toggle **Share**
   off/on (or add a comment) to force the write. Both machines must run
   the same version (compare footers).
3. **Is the note Shared?** Only ◉ notes publish; ○ notes never leave the
   machine. Press **Share** on it.
4. **Does each allow-list name the other's author?** Matching is against
   note *authors* (the machine name active when the note was created),
   not file names. `Sharing with: …` in the footer shows your effective
   list.
5. **Wait ~15 seconds** (folder poll cadence), then check Setup's
   **Diagnostics** line: `files=` (scan) → `fetched=`/`snapNotes=`
   (read) → `peerNotes=` (merge) → `shown=` (display) pinpoints the stage.

## Files (for the curious)

- `Panel.qml` — widget UI, self-setup, friends, automatic sync
- `Store.js` — note logic (pure JS, panel + Node compatible)
- `nostr/sync.mjs` — relay bridge used by the panel (`ensure-key`,
  `npub-to-hex`, `publish`, `fetch`)
