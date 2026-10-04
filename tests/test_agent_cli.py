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
import stat

argv = sys.argv[1:]
record = {"argv": argv}
if len(argv) == 3 and argv[1] == "request":
    path = argv[2]
    record["request"] = json.loads(open(path, encoding="utf-8").read())
    record["mode"] = stat.S_IMODE(os.stat(path).st_mode)
    record["links"] = os.stat(path).st_nlink

with open(os.environ["TRANSNOTE_AGENT_TEST_LOG"], "w", encoding="utf-8") as f:
    json.dump(record, f)

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

    def invoke(self, *args, response=None, shell_exit=0, raw=False):
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
            [str(CLI), *args] if raw else [str(CLI), "--json-stdin"],
            input=None if raw else json.dumps(list(args)),
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
        record = json.loads(self.log.read_text(encoding="utf-8"))
        if "request" in record:
            request = record["request"]
            return [IPC_TARGET, request["method"], *request["arguments"]]
        return record["argv"]

    def test_private_payload_uses_unlinked_owner_only_descriptor(self):
        secrets = ["private title ä", "private body\n<img src='secret'>"]
        result = self.invoke("create", "--title", secrets[0], "--body", secrets[1])
        self.assertEqual(result.returncode, 0, result.stdout)
        record = json.loads(self.log.read_text())
        self.assertEqual(record["argv"][:2], [IPC_TARGET, "request"])
        self.assertRegex(record["argv"][2], r"^/proc/[0-9]+/fd/[0-9]+$")
        for secret in secrets:
            self.assertNotIn(secret, json.dumps(record["argv"]))
        self.assertEqual(record["request"], {"method": "create", "arguments": secrets})
        self.assertEqual(record["mode"], 0o600)
        self.assertEqual(record["links"], 0)
        self.assertFalse(Path(record["argv"][2]).exists())

    def test_sensitive_legacy_argv_is_rejected(self):
        for args in (("create", "--title", "private"), ("comment", "id", "--text", "private"), ("search", "private")):
            result = self.invoke(*args, raw=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(self.log.exists())

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

    def test_share_forwards_exact_note_id(self):
        result = self.invoke("share", "note-123")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "share", "note-123"],
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


    def test_get_forwards_exact_note_id(self):
        result = self.invoke("get", "note-123")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.forwarded_argv(),
            [IPC_TARGET, "get", "note-123"],
        )

    def test_get_requires_one_note_id_before_ipc(self):
        result = self.invoke("get")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "MISSING_ARGUMENT")

    def test_get_rejects_extra_arguments_before_ipc(self):
        result = self.invoke("get", "note-123", "extra")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "INVALID_ARGUMENT")

    def test_get_rejects_empty_note_id_before_ipc(self):
        result = self.invoke("get", "   ")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "INVALID_ARGUMENT")

    def test_get_note_not_found_uses_domain_exit_code(self):
        result = self.invoke(
            "get",
            "note-missing",
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


    def test_share_requires_one_note_id_before_ipc(self):
        result = self.invoke("share")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "MISSING_ARGUMENT")

    def test_share_rejects_extra_arguments_before_ipc(self):
        result = self.invoke("share", "note-123", "extra")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "INVALID_ARGUMENT")

    def test_share_rejects_empty_note_id_before_ipc(self):
        result = self.invoke("share", "   ")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "INVALID_ARGUMENT")

    def test_share_not_allowed_uses_domain_exit_code(self):
        result = self.invoke(
            "share",
            "note-human",
            response={
                "ok": False,
                "protocolVersion": PROTOCOL_VERSION,
                "error": {
                    "code": "SHARE_NOT_ALLOWED",
                    "message": "note is not eligible for agent sharing",
                },
            },
        )

        self.assertEqual(result.returncode, 4)

        out = self.output_json(result)
        self.assertEqual(out["error"]["code"], "SHARE_NOT_ALLOWED")

    def test_local_errors_include_protocol_version(self):
        result = self.invoke("get")

        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

        out = self.output_json(result)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "MISSING_ARGUMENT")
        self.assertEqual(out["protocolVersion"], PROTOCOL_VERSION)

if __name__ == "__main__":
    unittest.main()
