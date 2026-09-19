# Third-party notices

TransNote itself is released under the ISC License. See `LICENSE`.

## Runtime Nostr dependency

The direct JavaScript runtime dependency is:

- `nostr-tools` `2.25.2`
- license: Unlicense

The exact package version, integrity hash, dependency tree, and recorded license are locked in `package-lock.json`.

The maintained source is `nostr/sync.mjs`. The plugin executes the committed `nostr/sync.bundle.mjs` bundle at runtime.

The committed bundle preserves bundled license information. Its footer records MIT license notices for bundled Noble and Scure components. Keep those notices in the generated bundle when the bundle is rebuilt.

This file summarizes repository evidence. `package-lock.json` and the license notices retained in `nostr/sync.bundle.mjs` remain the detailed dependency evidence.
