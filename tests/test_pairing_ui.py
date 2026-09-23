import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"


class PairingUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PANEL.read_text(encoding="utf-8")

    def test_tn1_pairing_surfaces_are_present(self):
        for marker in [
            'text: "Connect computers for LAN/folder sync here. A device setup code is different from an Internet friend code; pairing adds the computer to your device list automatically."',
            'text: "Device sync"',
            '"Create device setup code"',
            'text: "Share this device setup code with the other computer:"',
            'text: "Join an existing device sync"',
            'text: "Join device sync"',
            'text: "Pending computer connections"',
            'text: "Pending TransNote folders"',
            'text: "Connected computers"',
            '"Advanced: configure folder sync manually"',
            'text: "No folder sync configured yet — create a device setup code or join an existing device sync."',
        ]:
            self.assertIn(marker, self.text)

    def test_pairing_helper_is_invoked_as_argv_not_interpolated_shell(self):
        self.assertIn('readonly property string pairingHelper: pluginDir + "/lan/syncthing.mjs"', self.text)
        self.assertIn('return [nodeBin, pairingHelper, action,', self.text)
        self.assertIn('"--code", code', self.text)

    def test_manual_folder_sync_controls_remain_present(self):
        self.assertIn('text: "1 — Name this machine (becomes <name>.json in the folder):"', self.text)
        self.assertIn('text: "2 — Shared folder (same folder, synced between machines with Syncthing/Dropbox):"', self.text)
        self.assertIn('text: "3 — Allowed LAN devices (comma-separated machine names):"', self.text)
        self.assertIn('text: "Machine names control folder-sync visibility. Removing one hides its LAN shares. People added under People are separate; older Internet public keys in this shared list also authorize Internet sharing."', self.text)
        self.assertIn('id: setupPeersField', self.text)
        self.assertIn('visible: root.manualSetupOpen', self.text)

    def test_people_view_explains_internet_scope(self):
        self.assertIn('text: "People here are Internet friends only. Adding or removing someone affects Internet sharing, not LAN device sync."', self.text)

    def test_pair_import_updates_qualified_peers(self):
        self.assertIn('qualifyPairingPeer(peer)', self.text)
        self.assertIn('saveSetupPeers()', self.text)
        self.assertIn('if (peers.indexOf(peer) === -1) peers.push(peer)', self.text)

    def test_pairing_persists_base_omarchy_settings(self):
        self.assertIn('function persistPairingBaseSettings()', self.text)
        self.assertIn('"deviceId", device', self.text)
        self.assertIn('"syncDir", folder', self.text)
        self.assertGreaterEqual(self.text.count('persistPairingBaseSettings()'), 4)


if __name__ == "__main__":
    unittest.main()
