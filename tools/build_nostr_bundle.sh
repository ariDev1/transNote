#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESBUILD="$ROOT/node_modules/.bin/esbuild"
SOURCE="$ROOT/nostr/sync.mjs"
OUTPUT="$ROOT/nostr/sync.bundle.mjs"
TMP="$(mktemp "$ROOT/nostr/.sync.bundle.mjs.XXXXXX")"

cleanup() {
  rm -f "$TMP"
}
trap cleanup EXIT

if [[ ! -x "$ESBUILD" ]]; then
  echo "Missing development dependency: run npm ci" >&2
  exit 1
fi

"$ESBUILD" "$SOURCE" \
  --bundle \
  --platform=node \
  --format=esm \
  --target=node20 \
  --charset=utf8 \
  --legal-comments=eof \
  --log-level=warning \
  --outfile="$TMP"

mv "$TMP" "$OUTPUT"
trap - EXIT

sha256sum "$OUTPUT"
