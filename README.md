# TransNote

Fast shared notes for the Omarchy bar.

![TransNote running on Omarchy](preview.png)

TransNote lets you write notes, share them between your machines or with trusted peers, add comments, and exchange attachments.

It supports three modes:

- **Local** — notes stay on this machine.
- **LAN / folder sync** — shared notes move through a folder synchronized by Syncthing, Dropbox, rsync, or another file-sync tool.
- **Internet sync** — shared notes and comments are sent through Nostr relays using end-to-end encryption.

Normal use and setup are available from the TransNote panel.

## Features

- Local text notes
- Share and unshare notes
- Peer comments
- LAN folder synchronization
- Encrypted Internet synchronization
- File attachments over folder sync
- SHA-256 verification of received attachments
- Image thumbnails and text previews
- Copy note content to the clipboard
- Fenced code blocks with per-block copy
- Keyboard navigation
- Per-note color tint
- New-note indicators
- Local backup of the previous note state

Notes are private by default. TransNote does not publish a note until you explicitly share it.

## Requirements

- Omarchy with Quickshell plugin support
- Bash and standard Linux command-line utilities
- `wl-copy` for clipboard operations
- `xdg-open` for opening received attachments

For **Internet sync**, TransNote also requires:

- Node.js
- npm

Install Node.js and npm on Omarchy if they are not already available:

```bash
omarchy pkg add nodejs npm
```

TransNote uses the npm package `nostr-tools`.

When Internet sync is initialized for the first time, TransNote checks for this dependency and installs it into the plugin directory with npm if necessary.

LAN folder synchronization does not require Node.js or Nostr.

Syncthing is recommended for LAN synchronization, but it is not required. Any tool that reliably synchronizes the selected folder can be used.

## Installation

Install and enable TransNote directly from GitHub:

```bash
omarchy plugin add https://github.com/ariDev1/transNote.git --enable
```

Then open TransNote from the Omarchy bar.

The plugin ID is:

```text
ariDev1.transnote
```

## Quick setup

Open the **Setup** tab in TransNote.

### 1. Name this machine

Choose a stable device name such as:

```text
laptop
```

or:

```text
desktop
```

Keep this name stable after you start sharing notes.

### 2. Configure a shared folder

For LAN synchronization, select a folder such as:

```text
~/transnote-lan
```

TransNote can create the local folder for you.

The same folder must then be synchronized between your machines.

### 3. Configure trusted peers

Add the device names that are allowed to participate in your folder-sync setup.

Example:

```text
laptop,desktop
```

TransNote writes one snapshot per device into the shared folder.

Only notes marked as shared are included.

## LAN synchronization

LAN synchronization uses normal files. It does not require an Internet service.

A typical configuration is:

```text
Machine A
~/transnote-lan
      ⇅
   Syncthing
      ⇅
~/transnote-lan
Machine B
```

Each device writes its own snapshot:

```text
<deviceId>.json
```

For example:

```text
laptop.json
desktop.json
```

Peer snapshots are checked automatically.

You can also use **Check for peers now** in the Setup panel.

The Setup panel shows synchronization diagnostics when troubleshooting is necessary.

### Important privacy note

Folder-sync snapshots contain the notes that you explicitly share through that folder.

Anyone who has access to the synchronized folder can potentially read those shared files.

Use appropriate folder permissions and only synchronize the folder with machines and users you trust.

For sensitive remote sharing, use TransNote's encrypted Internet synchronization instead.

## Internet synchronization

Internet synchronization uses Nostr relays.

TransNote creates a private Nostr key on your machine and shows a public sharing code.

To connect with another TransNote user:

1. Copy your public code from the TransNote panel.
2. Send it to your friend through a trusted communication channel.
3. Ask them for their code.
4. Add their code under **Add a friend**.

Your private key stays on your machine.

The private key is stored at:

```text
~/.local/share/transnote/nostr_key
```

Never share this file.

Internet synchronization uses encrypted messages. Relay servers receive ciphertext rather than your note text.

TransNote will not publish Internet notes when no recipients are configured.

## Attachments

Attachments are supported through **folder synchronization**.

Attach a file to one of your own notes from the attachment row.

Maximum attachment size:

```text
25 MB
```

Attachment bytes are stored below:

```text
<syncDir>/.attachments/
```

The note itself contains attachment metadata including:

- file name
- file size
- SHA-256 hash

Received files are hashed locally before TransNote marks them as verified.

TransNote can:

- show image thumbnails
- preview text files
- save received files to `~/Downloads`
- open safe files with the system handler
- report missing or invalid attachment data

Saved files never overwrite an existing file. TransNote creates a new numbered file name instead.

Files that look executable, or files with the executable bit set, are not opened automatically. They remain save-only.

Attachment bytes are currently transported through folder sync. Internet-shared notes can carry attachment metadata, but not the attachment bytes.

## Comments

Shared notes can contain comments.

Comments follow the same synchronization path as the note:

- folder-synchronized notes exchange comments through peer snapshots
- Internet-shared notes exchange comments through encrypted Internet synchronization

Local comments are stored with the local note state.

## Keyboard controls

TransNote supports keyboard-first operation.

| Key | Action |
|---|---|
| `j` / `k` | Move between notes |
| `↑` / `↓` | Move between notes |
| `Enter` | Expand selected note |
| `c` | Copy note content |
| `s` | Share or unshare |
| `x` | Delete your own note |
| `a` | Open attachment controls |
| `t` | Change note tint |
| `/` | Focus note composer |
| `Ctrl+Enter` | Add note |
| `Esc` | Close or leave the current action |

When a text field has focus, normal typing is passed to that field.

## Data and privacy

TransNote stores its local data below:

```text
~/.local/share/transnote/
```

This includes:

```text
notes.json
notes.json.bak
friends.json
nostr_key
attachments/
```

TransNote restricts its private data directory and files to the local user.

The previous `notes.json` state is preserved as:

```text
notes.json.bak
```

This provides a simple recovery point for local notes.

### What leaves the machine

A local note does not leave the machine unless you explicitly share it.

When folder synchronization is active, shared note data is written to the configured sync folder.

When Internet synchronization is active, shared data is encrypted for configured recipients before it is sent to the configured Nostr relays.

## Updating

For a Git-managed installation:

```bash
omarchy plugin update ariDev1.transnote
```

The current TransNote version is shown in the panel footer.

## Removal

Remove TransNote with:

```bash
omarchy plugin remove ariDev1.transnote
```

Omarchy removes the installed plugin checkout.

TransNote user data under:

```text
~/.local/share/transnote/
```

and an external synchronization folder such as:

```text
~/transnote-lan
```

are separate from the plugin installation.

This prevents plugin removal from silently destroying user notes, keys, or synchronized files.

Delete those directories manually only when you intentionally want to remove their data.

## Troubleshooting

### Peer notes do not appear

First verify that the synchronization folder itself works independently of TransNote.

Create a temporary file on one machine:

```bash
touch ~/transnote-lan/transnote-sync-test
```

Confirm that the file arrives on the other machine.

If it does not, fix the folder synchronization system first.

Then check:

1. Both machines use different stable device names.
2. Each machine allows the other device name.
3. The note is marked as shared.
4. The peer snapshot exists in the synchronization folder.
5. Both machines run a compatible TransNote version.

The Setup panel also provides peer and synchronization diagnostics.

### Recover the previous local note state

TransNote keeps the previous state at:

```text
~/.local/share/transnote/notes.json.bak
```

To restore it:

```bash
cp ~/.local/share/transnote/notes.json.bak \
   ~/.local/share/transnote/notes.json
```

### Internet sync reports that Node.js is missing

Install the required runtime:

```bash
omarchy pkg add nodejs npm
```

Then restart or reopen TransNote.

## Project structure

```text
Panel.qml
Store.js
nostr/sync.mjs
manifest.json
package.json
package-lock.json
```

`Panel.qml`
: Omarchy / Quickshell user interface and runtime integration.

`Store.js`
: Note, comment, peer, attachment, and validation logic.

`nostr/sync.mjs`
: Internet synchronization and encryption bridge.

`manifest.json`
: Omarchy plugin manifest.

`package.json`
: JavaScript dependency declaration.

`package-lock.json`
: Locked npm dependency versions and integrity hashes.

## License

TransNote is open-source software released under the **ISC License**.

See [`LICENSE`](LICENSE).

## Source

GitHub:

```text
https://github.com/ariDev1/transNote
```