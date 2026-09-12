# TransNote Runtime Dependency Security Design

Date: 2026-09-12

## Purpose

Remove automatic runtime package installation from TransNote.

This change addresses the Omarchy Plugin Marketplace security review for commit:

`96af0e561e437a6f2eb4af680fcd309d6de4c077`

Existing local, LAN, attachment, comment, and Nostr protocols must remain unchanged.

## Current problem

The current Internet-sync startup:

- searches several Node.js locations
- can resolve bare `node` and `npm` through `PATH`
- checks for `node_modules/nostr-tools`
- automatically runs `npm install`
- modifies the installed plugin checkout
- executes downloaded package code
- inherits environment variables such as `NODE_OPTIONS`

This makes the reviewed plugin checkout mutable at runtime.

## Required architecture

Runtime Node.js executable:

`/usr/bin/node`

TransNote must not search `PATH` for Node.js.

If `/usr/bin/node` is missing:

- Internet sync stays disabled
- the UI reports that system Node.js is required
- Local and LAN operation continue

The operator installs Node.js explicitly:

`omarchy pkg add nodejs`

TransNote must not install Node.js or npm packages.

## Nostr runtime artifact

Maintainable source:

`nostr/sync.mjs`

Reviewed runtime artifact:

`nostr/sync.bundle.mjs`

The bundle contains `nostr-tools` and its required JavaScript dependencies.

The bundle is committed to Git.

Runtime must not require:

- npm
- `node_modules`
- network package installation

`package.json` and `package-lock.json` remain dependency provenance.

## Runtime environment

Node.js must run with a sanitized environment.

Inherited `NODE_OPTIONS` must not reach Node.js.

The runtime must not depend on inherited `PATH`.

Only required environment values may be supplied explicitly.

## Preserved behavior

Do not change:

- Nostr key format
- NIP-44 encryption
- relay configuration
- publish/fetch semantics
- friend allow-list semantics
- local note format
- LAN snapshot protocol
- attachment protocol
- attachment SHA-256 verification
- comment format

## Expected changes

Expected files:

- `Panel.qml`
- `README.md`
- `nostr/sync.bundle.mjs`
- development build configuration

`nostr/sync.mjs` remains the source unless a build compatibility change is required.

Do not make unrelated changes.

## Verification

Before publication:

1. Build the bundle twice from the same clean source.
2. Confirm both bundle SHA-256 values are identical.
3. Confirm runtime does not create `node_modules`.
4. Confirm runtime does not modify the Git checkout.
5. Confirm no runtime npm command remains.
6. Confirm only `/usr/bin/node` is used.
7. Test with hostile `NODE_OPTIONS`.
8. Confirm the sanitized execution path is unaffected.
9. Test with `/usr/bin/node` unavailable.
10. Confirm Internet sync fails closed.
11. Confirm Local and LAN functions still work.
12. Field-test Internet key creation, friend conversion, publish, and fetch.

## Publication

Work remains on:

`publication-security-fix`

Do not modify `master` until verification and field testing pass.

After verification:

1. Review the complete diff.
2. Create a pull request.
3. Merge after field confirmation.
4. Verify the new master commit.
5. Perform a clean GitHub installation test.
6. Update Marketplace issue #6564 with the new master commit.
7. Wait for fresh Marketplace validation and security review.
