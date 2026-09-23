# Release notes

## TransNote 0.5.7

This version refreshes the TransNote panel UI while retaining the existing local, LAN, Internet, and Agent behavior.

Changes include:

- clearer **People** and **Devices** sections for Internet friends versus LAN/folder sync;
- device setup-code labels that distinguish computer pairing from Internet friend codes;
- manual folder-sync controls moved under a collapsed Advanced section;
- switchable List and square-grid note views;
- single-note grid selection, with full details shown immediately above the selected row and an explicit route to List controls.

The repository test suite passes on this version. The full runtime compatibility statement remains scoped to the recorded `0.5.6` acceptance baseline below.

## TransNote 0.5.6

This release candidate combines the current Omarchy TransNote user interface, trust-boundary hardening, and the optional local Agent interface.

Changes include:

- a collapsible note composer that leaves more panel space for existing notes;
- LAN and local filesystem trust-boundary hardening;
- the optional Agent CLI protocol v1;
- local-only AI provenance markers for Agent-created notes and comments;
- restricted Agent Share for visible local notes that were created through the Agent API;
- an optional OpenCode adapter with fixed TransNote tools and fail-closed version checks;
- a portable `tests/run` entry point for the repository test suite;
- local private Setup recovery so Omarchy disable/re-enable does not lose the device name, sync folder, or allow-list;

Agent-created notes remain private by default. Sharing is a separate explicit operation. The Agent API does not expose delete, unshare, pairing administration, attachment mutation, arbitrary filesystem access, or arbitrary command forwarding.

### OpenCode acceptance boundary

The OpenCode adapter implementation and automated tests are present in this release candidate. OpenCode `1.18.31` was not recorded as a trusted adapter version because the required live permission-boundary acceptance run was blocked by the provider path during development.

The adapter therefore keeps the exact-version acceptance gate. A version must pass `tools/opencode/security-test.txt` before `tools/opencode/mark-tested.sh --accept-security-test` records it as tested.

### Tested runtime baseline

The runtime acceptance baseline for this candidate is:

```text
184036235f064281533a631aa70c794e62ea96f4
```

See the tested compatibility section in `README.md` for the exact Omarchy, Quickshell, session, display, and hardware scope.
