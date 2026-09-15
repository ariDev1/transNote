import base64
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "lan" / "syncthing.mjs"

LOCAL_ID = "VT4RDYA-YF7D47B-EA6KH4M-X2TNLGF-7VET7T7-QOUBZXD-76WCE7M-N2ABYQF"
REMOTE_ID = "XAKQHZH-LBCD2KA-WFGNFGQ-XUV7HQU-UV23PME-BFYYBCR-S5MJXXR-RDTQTQK"
EXISTING_ID = "P56IOI7-MZJNU2Y-IQGDREY-DM2MGTI-MGL3BXN-PQ6W5BM-TBBZ4TJ-XZWICQ2"
REMOTE_FOLDER = "tn-abcdef0123456789"


def pairing_code(name="reichskanzlei", folder=REMOTE_FOLDER, device=REMOTE_ID):
    payload = {
        "version": 1,
        "transnoteDeviceId": name,
        "syncthingDeviceId": device,
        "folderId": folder,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return "TN1:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def write_fake(path):
    path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys
        from pathlib import Path
        args = sys.argv[1:]
        log = Path(os.environ['FAKE_SYNCTHING_LOG'])
        with log.open('a', encoding='utf-8') as h:
            h.write(json.dumps(args) + '\\n')
        if args == ['cli','show','system']:
            if os.environ.get('FAKE_FAIL_SYSTEM') == '1':
                print('not running', file=sys.stderr); raise SystemExit(1)
            print(json.dumps({'myID': os.environ['FAKE_LOCAL_ID']}))
        elif args == ['cli','config','dump-json']:
            print(os.environ.get('FAKE_CONFIG_JSON','{"folders":[],"devices":[]}'))
        elif args == ['cli','show','pending','folders']:
            print(os.environ.get('FAKE_PENDING_JSON','{}'))
        elif args == ['cli','show','pending','devices']:
            print(os.environ.get('FAKE_PENDING_DEVICES_JSON','{}'))
        elif args == ['cli','show','connections']:
            print(os.environ.get('FAKE_CONNECTIONS_JSON','{"connections":{}}'))
        else:
            print('')
    """))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def read_commands(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


class SyncthingPairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sync = self.root / "transnote-lan"
        self.sync.mkdir()
        self.data = self.root / "data"
        self.fake = self.root / "syncthing"
        self.log = self.root / "commands.log"
        write_fake(self.fake)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, action, *, config=None, pending=None, pending_devices=None, connections=None, extra=None, binary=None, fail_system=False):
        env = os.environ.copy()
        env["TRANSNOTE_SYNCTHING_BIN"] = str(binary or self.fake)
        env["FAKE_SYNCTHING_LOG"] = str(self.log)
        env["FAKE_LOCAL_ID"] = LOCAL_ID
        env["FAKE_CONFIG_JSON"] = json.dumps(config or {"folders": [], "devices": []})
        env["FAKE_PENDING_JSON"] = json.dumps(pending or {})
        env["FAKE_PENDING_DEVICES_JSON"] = json.dumps(pending_devices or {})
        env["FAKE_CONNECTIONS_JSON"] = json.dumps(connections or {"connections": {}})
        if fail_system:
            env["FAKE_FAIL_SYSTEM"] = "1"
        args = ["node", str(CLI), action]
        args += ["--device-id", "omarchy", "--sync-dir", str(self.sync), "--data-dir", str(self.data)]
        if extra:
            args += extra
        return subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, check=False)

    def test_status_expands_home_in_existing_syncthing_folder_path(self):
        config = {
            "folders": [{
                "id": "reye3-kwu5q",
                "label": "transnote-lan",
                "path": "~/transnote-lan",
                "type": "sendreceive",
                "paused": False,
                "devices": [{"deviceID": LOCAL_ID}],
            }],
            "devices": [{"deviceID": LOCAL_ID}],
        }

        with mock.patch.dict(os.environ, {"HOME": str(self.root)}):
            result = self.run_cli("status", config=config)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["folder"]["configured"])
        self.assertEqual(value["folder"]["id"], "reye3-kwu5q")

    def test_prepare_creates_transnote_folder_and_tn1_code(self):
        result = self.run_cli("prepare")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["pairingCode"].startswith("TN1:"))
        encoded = value["pairingCode"][4:]
        encoded += "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["transnoteDeviceId"], "omarchy")
        self.assertEqual(payload["syncthingDeviceId"], LOCAL_ID)
        self.assertEqual(payload["folderId"], value["folderId"])
        self.assertEqual(value["folderPath"], str(self.sync.resolve()))
        commands = read_commands(self.log)
        folder_adds = [c for c in commands if c[:4] == ["cli","config","folders","add"]]
        self.assertEqual(len(folder_adds), 1)
        self.assertIn("--label", folder_adds[0])
        self.assertIn("transnote-lan", folder_adds[0])

    def test_repair_keeps_established_local_folder_authoritative(self):
        established = "reye3-kwu5q"

        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "lan_peers.json").write_text(json.dumps({
            "version": 1,
            "peers": [{
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": established,
                "pairedAt": "2026-09-15T10:00:00.000Z",
            }],
        }))

        config = {
            "folders": [{
                "id": established,
                "label": "transnote-lan",
                "path": str(self.sync.resolve()),
                "type": "sendreceive",
                "paused": False,
                "devices": [
                    {"deviceID": LOCAL_ID},
                    {"deviceID": REMOTE_ID},
                ],
            }],
            "devices": [
                {"deviceID": LOCAL_ID},
                {"deviceID": REMOTE_ID},
            ],
        }

        result = self.run_cli(
            "pair",
            config=config,
            extra=["--code", pairing_code(folder=REMOTE_FOLDER)],
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(json.loads(result.stdout)["peer"]["folderId"], established)

    def test_pair_folder_conflict_fails_before_syncthing_mutation(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "lan_peers.json").write_text(json.dumps({
            "version": 1,
            "peers": [{
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": REMOTE_FOLDER,
                "pairedAt": "2026-09-15T10:00:00.000Z",
            }],
        }))

        result = self.run_cli(
            "pair",
            extra=[
                "--code",
                pairing_code(folder="tn-1111111111111111"),
            ],
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "PAIR_CONFLICT")
        commands = read_commands(self.log)
        mutating = [
            command for command in commands
            if command[:3] == ["cli", "config", "devices"]
            or command[:3] == ["cli", "config", "folders"]
        ]
        self.assertEqual(mutating, [])

    def test_pair_identity_conflict_fails_before_syncthing_mutation(self):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "lan_peers.json").write_text(json.dumps({
            "version": 1,
            "peers": [{
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": REMOTE_FOLDER,
                "pairedAt": "2026-09-15T10:00:00.000Z",
            }],
        }))

        result = self.run_cli(
            "pair",
            extra=["--code", pairing_code(device=EXISTING_ID)],
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "PAIR_CONFLICT")
        commands = read_commands(self.log)
        mutating = [
            command for command in commands
            if command[:3] == ["cli", "config", "devices"]
            or command[:3] == ["cli", "config", "folders"]
        ]
        self.assertEqual(mutating, [])

    def test_pair_uses_remote_folder_when_local_path_is_empty(self):
        result = self.run_cli("pair", extra=["--code", pairing_code()])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["peer"]["folderId"], REMOTE_FOLDER)
        commands = read_commands(self.log)
        self.assertIn(["cli","config","devices","add","--device-id",REMOTE_ID], commands)
        self.assertIn(["cli","config","folders",REMOTE_FOLDER,"devices","add","--device-id",REMOTE_ID], commands)

    def test_pair_keeps_established_local_transnote_folder_authoritative(self):
        established = "tn-1111111111111111"
        config = {
            "folders": [{
                "id": established,
                "label": "transnote-lan",
                "path": str(self.sync.resolve()),
                "type": "sendreceive",
                "paused": False,
                "devices": [{"deviceID": LOCAL_ID}, {"deviceID": EXISTING_ID}],
            }],
            "devices": [{"deviceID": LOCAL_ID}, {"deviceID": EXISTING_ID}],
        }
        result = self.run_cli("pair", config=config, extra=["--code", pairing_code(folder=REMOTE_FOLDER)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["peer"]["folderId"], established)
        commands = read_commands(self.log)
        self.assertNotIn(["cli","config","folders",established,"delete"], commands)
        self.assertIn(["cli","config","folders",established,"devices","add","--device-id",REMOTE_ID], commands)

    def test_pair_replaces_unused_generated_provisional_folder(self):
        provisional = "tn-0123456789abcdef"
        config = {
            "folders": [{
                "id": provisional,
                "label": "transnote-lan",
                "path": str(self.sync.resolve()),
                "type": "sendreceive",
                "paused": False,
                "devices": [{"deviceID": LOCAL_ID}],
            }],
            "devices": [{"deviceID": LOCAL_ID}],
        }
        result = self.run_cli("pair", config=config, extra=["--code", pairing_code(folder=REMOTE_FOLDER)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        commands = read_commands(self.log)
        delete = ["cli","config","folders",provisional,"delete"]
        add = ["cli","config","folders","add","--id",REMOTE_FOLDER,"--label","transnote-lan","--path",str(self.sync.resolve())]
        self.assertIn(delete, commands)
        self.assertIn(add, commands)
        self.assertLess(commands.index(delete), commands.index(add))

    def test_unrelated_folder_at_path_fails_closed(self):
        config = {
            "folders": [{
                "id": "documents",
                "label": "Documents",
                "path": str(self.sync.resolve()),
                "type": "sendreceive",
                "paused": False,
                "devices": [{"deviceID": LOCAL_ID}],
            }],
            "devices": [{"deviceID": LOCAL_ID}],
        }
        result = self.run_cli("pair", config=config, extra=["--code", pairing_code()])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "FOLDER_ID_CONFLICT")

    def test_paused_and_non_sendreceive_folders_fail_closed(self):
        cases = [
            ({"type": "sendreceive", "paused": True}, "FOLDER_PAUSED"),
            ({"type": "sendonly", "paused": False}, "FOLDER_NOT_SENDRECEIVE"),
        ]
        for state, expected in cases:
            with self.subTest(expected=expected):
                config = {
                    "folders": [{
                        "id": "tn-1111111111111111",
                        "label": "transnote-lan",
                        "path": str(self.sync.resolve()),
                        "devices": [{"deviceID": LOCAL_ID}],
                        **state,
                    }],
                    "devices": [{"deviceID": LOCAL_ID}],
                }
                self.log.write_text("") if self.log.exists() else None
                result = self.run_cli("pair", config=config, extra=["--code", pairing_code()])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stderr)["code"], expected)

    def test_existing_remote_device_and_folder_membership_are_not_added_again(self):
        folder = REMOTE_FOLDER
        config = {
            "folders": [{
                "id": folder,
                "label": "transnote-lan",
                "path": str(self.sync.resolve()),
                "type": "sendreceive",
                "paused": False,
                "devices": [{"deviceID": LOCAL_ID}, {"deviceID": REMOTE_ID}],
            }],
            "devices": [{"deviceID": LOCAL_ID}, {"deviceID": REMOTE_ID}],
        }
        result = self.run_cli("pair", config=config, extra=["--code", pairing_code(folder=folder)])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        commands = read_commands(self.log)
        self.assertNotIn(["cli","config","devices","add","--device-id",REMOTE_ID], commands)
        self.assertNotIn(["cli","config","folders",folder,"devices","add","--device-id",REMOTE_ID], commands)

    def test_pending_folder_accept_rejects_non_transnote_label(self):
        config = {
            "folders": [],
            "devices": [{"deviceID": LOCAL_ID}, {"deviceID": REMOTE_ID, "name": "reichskanzlei"}],
        }
        pending = {REMOTE_FOLDER: {"offeredBy": {REMOTE_ID: {"label": "other-folder"}}}}
        result = self.run_cli(
            "accept-folder",
            config=config,
            pending=pending,
            extra=["--folder-id", REMOTE_FOLDER, "--syncthing-device-id", REMOTE_ID],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "PENDING_OFFER_NOT_TRANSNOTE")

    def test_mismatched_pending_offer_fails_closed(self):
        pending = {
            REMOTE_FOLDER: {
                "offeredBy": {
                    EXISTING_ID: {"label": "transnote-lan"}
                }
            }
        }
        result = self.run_cli("pair", pending=pending, extra=["--code", pairing_code()])
        self.assertNotEqual(result.returncode, 0)
        error = json.loads(result.stderr)
        self.assertEqual(error["code"], "PENDING_OFFER_MISMATCH")

    def test_pending_device_and_folder_are_reported_and_can_be_accepted(self):
        config = {
            "folders": [],
            "devices": [{"deviceID": LOCAL_ID}, {"deviceID": REMOTE_ID, "name": "reichskanzlei"}],
        }
        pending_devices = {REMOTE_ID: {"name": "reichskanzlei", "address": "192.0.2.2:22000"}}
        pending = {REMOTE_FOLDER: {"offeredBy": {REMOTE_ID: {"label": "transnote-lan"}}}}
        status = self.run_cli("status", config=config, pending=pending, pending_devices=pending_devices)
        self.assertEqual(status.returncode, 0, msg=status.stderr)
        value = json.loads(status.stdout)
        self.assertEqual(value["pendingDevices"][0]["deviceName"], "reichskanzlei")
        self.assertEqual(value["pendingOffers"][0]["folderId"], REMOTE_FOLDER)

        self.log.write_text("")
        accept = self.run_cli("accept-folder", config=config, pending=pending, extra=["--folder-id", REMOTE_FOLDER, "--syncthing-device-id", REMOTE_ID])
        self.assertEqual(accept.returncode, 0, msg=accept.stderr)
        commands = read_commands(self.log)
        self.assertIn(["cli","config","folders","add","--id",REMOTE_FOLDER,"--label","transnote-lan","--path",str(self.sync.resolve())], commands)

    def test_status_reports_missing_syncthing_without_breaking_manual_sync(self):
        missing = self.root / "does-not-exist"
        result = self.run_cli("status", binary=missing)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value["installed"])
        self.assertFalse(value["running"])

    def test_status_reports_not_running(self):
        result = self.run_cli("status", fail_system=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["installed"])
        self.assertFalse(value["running"])


if __name__ == "__main__":
    unittest.main()
