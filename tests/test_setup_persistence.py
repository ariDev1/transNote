"""Regression tests for persistent TransNote Setup state.

Omarchy removes the complete bar-widget entry from shell.json when a widget
is disabled. TransNote must keep a private local copy of its Setup values so
disable/re-enable does not lose deviceId, syncDir, or allowList.
"""

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "Store.js"
PANEL = ROOT / "Panel.qml"


def node_eval(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class SetupBackupStoreTests(unittest.TestCase):
    def test_setup_backup_sanitizer_normalizes_supported_fields(self):
        out = node_eval(
            "const S = require('./Store.js');"
            "const f = typeof S.sanitizeSetupBackup === 'function'"
            "  ? S.sanitizeSetupBackup : null;"
            "const out = f ? f({"
            "  version: 99,"
            "  deviceId: ' omaThink ',"
            "  syncDir: ' ~/transnote-lan ',"
            "  allowList: ' ubuntu, omaMac, labor '"
            "}) : null;"
            "console.log(JSON.stringify(out));"
        )

        self.assertEqual(
            out,
            {
                "version": 1,
                "deviceId": "omaThink",
                "syncDir": "~/transnote-lan",
                "allowList": "ubuntu, omaMac, labor",
            },
        )

    def test_setup_backup_sanitizer_fails_closed_on_bad_json(self):
        out = node_eval(
            "const S = require('./Store.js');"
            "const f = typeof S.sanitizeSetupBackup === 'function'"
            "  ? S.sanitizeSetupBackup : null;"
            "const out = f ? f('{broken') : null;"
            "console.log(JSON.stringify(out));"
        )

        self.assertEqual(
            out,
            {
                "version": 1,
                "deviceId": "",
                "syncDir": "",
                "allowList": "",
            },
        )


class SetupBackupPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text(encoding="utf-8")

    def function_block(self, name):
        start = self.panel.index(f"  function {name}(")
        end = self.panel.find("\n  function ", start + 1)
        if end < 0:
            end = len(self.panel)
        return self.panel[start:end]

    def test_setup_backup_is_private_local_state(self):
        self.assertIn(
            'readonly property string setupBackupPath: dataDir + "/setup.json"',
            self.panel,
        )
        self.assertIn(
            "property bool setupBackupLoaded: false",
            self.panel,
        )

    def test_runtime_settings_have_local_recovery_values(self):
        for token in (
            "effectiveDeviceIdSetting",
            "effectiveSyncDirSetting",
            "effectiveAllowListSetting",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

        self.assertIn(
            "Store.parseAllowList(effectiveAllowListSetting)",
            self.panel,
        )

    def test_shell_setting_changes_are_mirrored_to_local_backup(self):
        for token in (
            'onDeviceIdSettingChanged: root.updateSetupBackup("deviceId", deviceIdSetting)',
            'onSyncDirSettingChanged: root.updateSetupBackup("syncDir", syncDirSetting)',
            'onAllowListSettingChanged: root.updateSetupBackup("allowList", allowListSetting)',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

    def test_setup_backup_uses_atomic_private_storage(self):
        self.assertIn("id: setupBackupFile", self.panel)
        self.assertIn("path: root.setupBackupPath", self.panel)

        start = self.panel.index("    id: setupBackupFile")
        block = self.panel[start : start + 500]

        self.assertIn("atomicWrites: true", block)

        secure = self.function_block("secureFiles")
        self.assertIn("setupBackupPath", secure)

    def test_identity_migration_waits_for_recovery_state(self):
        self.assertIn(
            "readonly property bool setupIdentityReady:",
            self.panel,
        )

        load_local = self.function_block("loadLocal")
        self.assertIn(
            'setupIdentityReady && nowId !== ""',
            load_local,
        )

        migrate = self.function_block("migrateAuthors")
        self.assertIn(
            "!setupIdentityReady",
            migrate,
        )


    def test_explicit_empty_inline_setting_wins_over_backup(self):
        self.assertIn(
            "function hasInlineSetting(name)",
            self.panel,
        )

        has_inline = self.function_block("hasInlineSetting")
        self.assertIn(
            "settings[name] !== undefined",
            has_inline,
        )
        self.assertIn(
            "settings[name] !== null",
            has_inline,
        )

        for token in (
            'if (hasInlineSetting("deviceId"))',
            'if (hasInlineSetting("syncDir"))',
            'if (hasInlineSetting("allowList"))',
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.panel)

    def test_backup_missing_is_distinct_from_backup_read_failure(self):
        self.assertIn(
            "property bool setupBackupLoadFailed: false",
            self.panel,
        )
        self.assertIn(
            "function onSetupBackupLoadFailed(error)",
            self.panel,
        )

        body = self.function_block("onSetupBackupLoadFailed")

        self.assertIn(
            "FileViewError.FileNotFound",
            body,
        )
        self.assertIn(
            "setupBackupLoadFailed = true",
            body,
        )

    def test_sync_waits_for_setup_identity_recovery(self):
        self.assertIn(
            'readonly property bool syncConfigured: setupIdentityReady && syncDir !== ""',
            self.panel,
        )

    def test_setup_form_uses_effective_recovered_values(self):
        body = self.function_block("openSetup")

        self.assertIn(
            "effectiveSyncDirSetting",
            body,
        )
        self.assertIn(
            "effectiveAllowListSetting",
            body,
        )


if __name__ == "__main__":
    unittest.main()
