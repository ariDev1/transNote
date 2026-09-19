import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "transnote-agent"
IPC_TARGET = "aridev1.transnote.agent"
PROTOCOL_VERSION = 1


class AgentCliContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        tmp = Path(self.tmp.name)
        self.log = tmp / "argv.json"
        self.fake_bin = tmp / "bin"
        self.fake_bin.mkdir()

        shell = self.fake_bin / "omarchy-shell"
        shell.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["TRANSNOTE_AGENT_TEST_LOG"], "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f)

exit_code = int(os.environ.get("TRANSNOTE_AGENT_TEST_SHELL_EXIT", "0"))
response = os.environ.get(
    "TRANSNOTE_AGENT_TEST_RESPONSE",
    '{"ok":true,"protocolVersion":1}'
)

if exit_code == 0:
    print(response)
else:
    print("shell unavailable", file=sys.stderr)

raise SystemExit(exit_code)
""",
            encoding="utf-8",
        )
        shell.chmod(0o755)

    def invoke(self, *args, response=None, shell_exit=0):
        self.assertTrue(
            CLI.is_file(),
            "bin/transnote-agent does not exist yet",
        )

        env = os.environ.copy()
        env["PATH"] = str(self.fake_bin) + os.pathsep + env.get("PATH", "")
        env["TRANSNOTE_AGENT_TEST_LOG"] = str(self.log)
        env["TRANSNOTE_AGENT_TEST_SHELL_EXIT"] = str(shell_exit)

        if response is not None:
            env["TRANSNOTE_AGENT_TEST_RESPONSE"] = json.dumps(response)

        return subprocess.run(
            [str(CLI), *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )

    def output_json(self, result):
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(result.stderr, "")
        return json.loads(lines[0])

    def forwarded_argv(self):
        return json.loads(self.log.read_text(encoding="utf-8"))

    def test_cli_file_exists(self):
        self.assertTrue(CLI.is_file())

    def test_status_uses_fixed_ipc_target(self):
        result = self.invoke("status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "status"],
        )

    def test_list_uses_fixed_ipc_target(self):
        result = self.invoke("list")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "list"],
        )

    def test_search_forwards_one_query(self):
        result = self.invoke("search", "measurement")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "search", "measurement"],
        )

    def test_create_maps_options_to_fixed_arguments(self):
        result = self.invoke(
            "create",
            "--title",
            "Result",
            "--body",
            "Tests PASS",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [
                IPC_TARGET,
                "create",
                "Result",
                "Tests PASS",
            ],
        )

    def test_comment_maps_note_and_text(self):
        result = self.invoke(
            "comment",
            "note-123",
            "--text",
            "Confirmed",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [
                IPC_TARGET,
                "comment",
                "note-123",
                "Confirmed",
            ],
        )

    def test_unknown_command_is_structured_error(self):
        result = self.invoke("destroy")
        self.assertEqual(result.returncode, 2)

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "UNKNOWN_COMMAND")
        self.assertFalse(self.log.exists())

    def test_forbidden_commands_are_not_forwarded(self):
        for command in (
            "delete",
            "share",
            "unshare",
            "hide",
            "pair",
            "syncthing",
            "attach",
        ):
            with self.subTest(command=command):
                if self.log.exists():
                    self.log.unlink()

                result = self.invoke(command)

                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.log.exists())

    def test_identity_override_is_rejected(self):
        result = self.invoke(
            "create",
            "--title",
            "Test",
            "--author",
            "agent:opencode@labor",
        )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "UNKNOWN_OPTION")

    def test_empty_create_is_rejected_before_ipc(self):
        result = self.invoke(
            "create",
            "--title",
            "   ",
            "--body",
            "",
        )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertEqual(out["error"]["code"], "EMPTY_NOTE")

    def test_empty_search_is_rejected_before_ipc(self):
        result = self.invoke("search", "   ")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_empty_comment_is_rejected_before_ipc(self):
        result = self.invoke(
            "comment",
            "note-123",
            "--text",
            "   ",
        )

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_protocol_version_is_checked(self):
        result = self.invoke(
            "status",
            response={
                "ok": True,
                "protocolVersion": PROTOCOL_VERSION + 1,
            },
        )

        self.assertEqual(result.returncode, 5)

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "PROTOCOL_ERROR")

    def test_unavailable_shell_is_structured_error(self):
        result = self.invoke("status", shell_exit=1)

        self.assertEqual(result.returncode, 3)

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(
            out["error"]["code"],
            "TRANSNOTE_UNAVAILABLE",
        )


    def test_note_not_found_uses_domain_exit_code(self):
        result = self.invoke(
            "comment",
            "note-missing",
            "--text",
            "test",
            response={
                "ok": False,
                "protocolVersion": PROTOCOL_VERSION,
                "error": {
                    "code": "NOTE_NOT_FOUND",
                    "message": "note was not found",
                },
            },
        )

        self.assertEqual(result.returncode, 4)

        out = self.output_json(result)
        self.assertEqual(out["error"]["code"], "NOTE_NOT_FOUND")

    def test_not_ready_uses_runtime_exit_code(self):
        result = self.invoke(
            "list",
            response={
                "ok": False,
                "protocolVersion": PROTOCOL_VERSION,
                "error": {
                    "code": "TRANSNOTE_NOT_READY",
                    "message": "TransNote state is not ready",
                },
            },
        )

        self.assertEqual(result.returncode, 3)

    def test_remote_validation_error_uses_usage_exit_code(self):
        result = self.invoke(
            "create",
            "--title",
            "x",
            response={
                "ok": False,
                "protocolVersion": PROTOCOL_VERSION,
                "error": {
                    "code": "EMPTY_NOTE",
                    "message": "title and body cannot both be empty",
                },
            },
        )

        self.assertEqual(result.returncode, 2)

    def test_malformed_error_response_is_protocol_error(self):
        result = self.invoke(
            "list",
            response={
                "ok": False,
                "protocolVersion": PROTOCOL_VERSION,
            },
        )

        self.assertEqual(result.returncode, 5)

        out = self.output_json(result)
        self.assertEqual(out["error"]["code"], "PROTOCOL_ERROR")


    def test_capabilities_uses_fixed_ipc_target(self):
        result = self.invoke("capabilities")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "capabilities"],
        )

    def test_capabilities_rejects_arguments_before_ipc(self):
        result = self.invoke("capabilities", "extra")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "INVALID_ARGUMENT")

if __name__ == "__main__":
    unittest.main()
