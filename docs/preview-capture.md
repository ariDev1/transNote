# Preview capture

Use this procedure when `preview.png` is refreshed for a release.

## Reference environment

The current reference capture environment is:

- Wayland
- Hyprland
- single display at `1920x1080`
- display scale `1.25`
- refresh rate `60 Hz`

## Procedure

1. Start the exact TransNote release candidate that is being documented.
2. Confirm the repository working tree and candidate SHA before capture.
3. Use the reference display settings above.
4. Open the TransNote panel in its normal bar position.
5. Show a representative normal-use state. Do not expose private notes, keys, peer identifiers, or other sensitive user data.
6. Capture the TransNote interface with the normal Omarchy screenshot workflow.
7. Save the final PNG as `preview.png` at the repository root.
8. Do not stretch or rescale the captured interface to simulate a different display configuration.
9. Check the final image manually before release and confirm that it represents the current candidate UI.

If the reference environment changes, update this document together with the preview so the capture conditions remain reproducible.
