import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"
PACKAGE = ROOT / "package.json"
BUNDLE = ROOT / "nostr" / "sync.bundle.mjs"


class RuntimeSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text()

    def test_runtime_has_no_package_install_path(self):
        forbidden = (
            "function nodeCandidates()",
            "npmBin",
            "depCheck",
            "depInstall",
            "depinstall",
            "/node_modules/nostr-tools/package.json",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.panel)

    def test_runtime_uses_fixed_node_and_committed_bundle(self):
        self.assertIn(
            'readonly property string envBin: "/usr/bin/env"',
            self.panel,
        )
        self.assertIn(
            'readonly property string nodeBin: "/usr/bin/node"',
            self.panel,
        )
        self.assertIn(
            'readonly property string syncBundle: pluginDir + "/nostr/sync.bundle.mjs"',
            self.panel,
        )

    def test_runtime_builds_sanitized_node_commands(self):
        self.assertIn("function sanitizedNodeCommand(args)", self.panel)
        self.assertIn(
            'return [envBin, "-i", "HOME=" + home, "PATH=/usr/bin:/bin", nodeBin].concat(args || [])',
            self.panel,
        )
        self.assertIn("function nostrCommand(args)", self.panel)
        self.assertIn(
            "return sanitizedNodeCommand([syncBundle].concat(args || []))",
            self.panel,
        )

    def test_every_nostr_operation_uses_nostr_command(self):
        required = (
            'keyProcess.command = nostrCommand(["ensure-key"',
            'npubConvert.command = nostrCommand(["npub-to-hex"',
            'pubProcess.command = nostrCommand(["publish"',
            'fetchProcess.command = nostrCommand(["fetch"',
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

    def test_package_versions_are_exact(self):
        package = json.loads(PACKAGE.read_text())
        self.assertEqual(package["dependencies"]["nostr-tools"], "2.25.2")
        self.assertEqual(package["devDependencies"]["esbuild"], "0.28.2")

    def test_bundle_is_committed_and_self_contained(self):
        self.assertTrue(BUNDLE.is_file(), "nostr/sync.bundle.mjs is missing")
        text = BUNDLE.read_text(errors="replace")
        self.assertNotIn('from "nostr-tools"', text)
        self.assertNotIn("from 'nostr-tools'", text)

    def test_bundle_key_and_npub_round_trip(self):
        node = shutil.which("node")
        self.assertIsNotNone(
            node,
            "development Node.js is required for this test",
        )

        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "nostr_key"

            first = subprocess.run(
                [
                    node,
                    str(BUNDLE),
                    "ensure-key",
                    "--key-file",
                    str(key),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            info = json.loads(first.stdout)
            self.assertRegex(info["hex"], r"^[0-9a-f]{64}$")
            self.assertTrue(info["npub"].startswith("npub1"))

            second = subprocess.run(
                [
                    node,
                    str(BUNDLE),
                    "npub-to-hex",
                    "--npub",
                    info["npub"],
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            converted = json.loads(second.stdout)
            self.assertEqual(converted["hex"], info["hex"])


if __name__ == "__main__":
    unittest.main()
