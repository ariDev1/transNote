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
2. To share over the internet:
   - Copy **your code** in the panel (SHARE OVER INTERNET section) and send
     it to a friend — message, email, anything.
   - Paste the code your friend sends back under **Add a friend**, give them
     a name, press **Add friend**.
3. That's it. Shared notes sync by themselves about once a minute
   (or press **Sync now**). Your friend's notes appear marked with 🌐,
   and you can comment on them.

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

## Files (for the curious)

- `Panel.qml` — widget UI, self-setup, friends, automatic sync
- `Store.js` — note logic (pure JS, panel + Node compatible)
- `nostr/sync.mjs` — relay bridge used by the panel (`ensure-key`,
  `npub-to-hex`, `publish`, `fetch`)
