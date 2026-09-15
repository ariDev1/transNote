import base64
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRING = ROOT / "lan" / "pairing.mjs"

LOCAL_ID = "VT4RDYA-YF7D47B-EA6KH4M-X2TNLGF-7VET7T7-QOUBZXD-76WCE7M-N2ABYQF"
REMOTE_ID = "XAKQHZH-LBCD2KA-WFGNFGQ-XUV7HQU-UV23PME-BFYYBCR-S5MJXXR-RDTQTQK"


def run_node(source, *args):
    return subprocess.run(
        ["node", "--input-type=module", "-e", source, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def ubuntu_style_code(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return "TN1:" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class PairingCodecTests(unittest.TestCase):
    def test_round_trip_uses_tn1_and_expected_payload(self):
        source = f'''\nimport {{encodePairingCode, decodePairingCode}} from {json.dumps(PAIRING.as_uri())};\nconst code = encodePairingCode({{version:1, transnoteDeviceId:'reichskanzlei', syncthingDeviceId:{json.dumps(REMOTE_ID)}, folderId:'tn-0123456789abcdef'}});\nconsole.log(code);\nconsole.log(JSON.stringify(decodePairingCode(code)));\n'''
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("TN1:"))
        payload = json.loads(lines[1])
        self.assertEqual(payload, {
            "version": 1,
            "transnoteDeviceId": "reichskanzlei",
            "syncthingDeviceId": REMOTE_ID,
            "folderId": "tn-0123456789abcdef",
        })

    def test_accepts_code_created_by_ubuntu_format(self):
        code = ubuntu_style_code({
            "version": 1,
            "transnoteDeviceId": "reichskanzlei",
            "syncthingDeviceId": REMOTE_ID,
            "folderId": "tn-0123456789abcdef",
        })
        source = f'''\nimport {{decodePairingCode}} from {json.dumps(PAIRING.as_uri())};\nconsole.log(JSON.stringify(decodePairingCode(process.argv[1])));\n'''
        result = run_node(source, code)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(json.loads(result.stdout)["transnoteDeviceId"], "reichskanzlei")

    def test_invalid_prefix_and_version_fail_closed(self):
        bad_codes = [
            "XX1:abcd",
            ubuntu_style_code({
                "version": 2,
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": "tn-0123456789abcdef",
            }),
        ]
        source = f'''\nimport {{decodePairingCode}} from {json.dumps(PAIRING.as_uri())};\ntry {{ decodePairingCode(process.argv[1]); process.exit(9); }} catch (e) {{ console.log(e.code); }}\n'''
        for code in bad_codes:
            result = run_node(source, code)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(result.stdout.strip(), "BAD_PAIRING_CODE")

    def test_invalid_device_and_folder_ids_fail_closed(self):
        cases = [
            {
                "version": 1,
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": "BAD-ID",
                "folderId": "tn-0123456789abcdef",
            },
            {
                "version": 1,
                "transnoteDeviceId": "reichskanzlei",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": "bad folder/id",
            },
            {
                "version": 1,
                "transnoteDeviceId": "../evil",
                "syncthingDeviceId": REMOTE_ID,
                "folderId": "tn-0123456789abcdef",
            },
        ]
        source = f'''\nimport {{decodePairingCode}} from {json.dumps(PAIRING.as_uri())};\ntry {{ decodePairingCode(process.argv[1]); process.exit(9); }} catch (e) {{ console.log(e.code); }}\n'''
        for payload in cases:
            result = run_node(source, ubuntu_style_code(payload))
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(result.stdout.strip(), "BAD_PAIRING_CODE")

    def test_self_pairing_fails_closed(self):
        source = f'''\nimport {{validatePairingPeer}} from {json.dumps(PAIRING.as_uri())};\ntry {{\n validatePairingPeer({{remote:{{version:1,transnoteDeviceId:'labor',syncthingDeviceId:{json.dumps(REMOTE_ID)},folderId:'tn-a'}},localTransnoteDeviceId:'labor',localSyncthingDeviceId:{json.dumps(LOCAL_ID)}}});\n process.exit(9);\n}} catch(e) {{ console.log(e.code); }}\n'''
        result = run_node(source)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "PAIR_SELF")

    def test_peer_store_is_idempotent_and_conflicts_fail(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            source = f'''\nimport {{saveLanPeer, loadLanPeers}} from {json.dumps(PAIRING.as_uri())};\nconst data = process.argv[1];\nconst peer = {{version:1,transnoteDeviceId:'reichskanzlei',syncthingDeviceId:{json.dumps(REMOTE_ID)},folderId:'tn-a'}};\nawait saveLanPeer(data, peer, '2026-09-15T10:00:00.000Z');\nawait saveLanPeer(data, peer, '2026-09-15T11:00:00.000Z');\nconsole.log(JSON.stringify(await loadLanPeers(data)));\ntry {{ await saveLanPeer(data, {{...peer, folderId:'tn-b'}}); process.exit(9); }} catch(e) {{ console.log(e.code); }}\n'''
            result = run_node(source, str(data))
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            lines = result.stdout.strip().splitlines()
            store = json.loads(lines[0])
            self.assertEqual(len(store["peers"]), 1)
            self.assertEqual(lines[1], "PAIR_CONFLICT")
            self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((data / "lan_peers.json").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
