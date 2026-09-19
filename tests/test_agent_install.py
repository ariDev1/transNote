import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "transnote-agent"
INSTALL = ROOT / "tools" / "install-agent-cli.sh"
UNINSTALL = ROOT / "tools" / "uninstall-agent-cli.sh"


class AgentInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.home = Path(self.tmp.name)
        self.bin_dir = self.home / ".local" / "bin"
        self.command = self.bin_dir / "transnote-agent"

        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)

    def run_script(self, script):
        return subprocess.run(
            [str(script)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_install_and_uninstall_scripts_exist(self):
        self.assertTrue(INSTALL.is_file())
        self.assertTrue(UNINSTALL.is_file())

    def test_install_creates_user_level_symlink(self):
        result = self.run_script(INSTALL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.command.is_symlink())
        self.assertEqual(
            self.command.resolve(),
            CLI.resolve(),
        )

    def test_install_is_idempotent(self):
        first = self.run_script(INSTALL)
        second = self.run_script(INSTALL)

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertTrue(self.command.is_symlink())
        self.assertEqual(
            self.command.resolve(),
            CLI.resolve(),
        )

    def test_install_does_not_replace_existing_file(self):
        self.bin_dir.mkdir(parents=True)
        self.command.write_text(
            "foreign command\n",
            encoding="utf-8",
        )

        result = self.run_script(INSTALL)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.command.is_symlink())
        self.assertEqual(
            self.command.read_text(encoding="utf-8"),
            "foreign command\n",
        )

    def test_install_does_not_replace_foreign_symlink(self):
        self.bin_dir.mkdir(parents=True)
        foreign = self.home / "foreign-command"
        foreign.write_text("foreign\n", encoding="utf-8")
        self.command.symlink_to(foreign)

        result = self.run_script(INSTALL)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.command.is_symlink())
        self.assertEqual(
            self.command.resolve(),
            foreign.resolve(),
        )

    def test_uninstall_removes_own_symlink(self):
        self.assertEqual(
            self.run_script(INSTALL).returncode,
            0,
        )

        result = self.run_script(UNINSTALL)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.command.exists())
        self.assertFalse(self.command.is_symlink())

    def test_uninstall_is_idempotent(self):
        first = self.run_script(UNINSTALL)
        second = self.run_script(UNINSTALL)

        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)

    def test_uninstall_does_not_remove_foreign_file(self):
        self.bin_dir.mkdir(parents=True)
        self.command.write_text(
            "foreign command\n",
            encoding="utf-8",
        )

        result = self.run_script(UNINSTALL)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.command.is_file())
        self.assertEqual(
            self.command.read_text(encoding="utf-8"),
            "foreign command\n",
        )

    def test_uninstall_does_not_remove_foreign_symlink(self):
        self.bin_dir.mkdir(parents=True)
        foreign = self.home / "foreign-command"
        foreign.write_text("foreign\n", encoding="utf-8")
        self.command.symlink_to(foreign)

        result = self.run_script(UNINSTALL)

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.command.is_symlink())
        self.assertEqual(
            self.command.resolve(),
            foreign.resolve(),
        )

    def test_scripts_do_not_use_privilege_or_shell_config(self):
        combined = (
            INSTALL.read_text(encoding="utf-8")
            + "\n"
            + UNINSTALL.read_text(encoding="utf-8")
        )

        forbidden = (
            "sudo",
            ".bashrc",
            ".zshrc",
            ".profile",
            "fish/config",
            "/etc/",
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, combined)

    def test_scripts_do_not_access_transnote_storage_or_sync(self):
        combined = (
            INSTALL.read_text(encoding="utf-8")
            + "\n"
            + UNINSTALL.read_text(encoding="utf-8")
        )

        forbidden = (
            "notes.json",
            "notes.json.bak",
            "transnote-lan",
            "verified-attachments",
            "syncthing",
            "pairing",
            "nostr_key",
        )

        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, combined)


if __name__ == "__main__":
    unittest.main()
