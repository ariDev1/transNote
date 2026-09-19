import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
SECURITY = ROOT / "SECURITY.md"
THIRD_PARTY = ROOT / "THIRD_PARTY_NOTICES.md"
RELEASE_NOTES = ROOT / "RELEASE_NOTES.md"
PREVIEW_CAPTURE = ROOT / "docs" / "preview-capture.md"


class ReleaseDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = README.read_text(encoding="utf-8")
        cls.readme_lower = cls.readme.lower()

    def test_readme_records_exact_tested_compatibility_scope(self):
        required = (
            "- Omarchy `4.0.4-1`",
            "- Quickshell `0.3.1`",
            "184036235f064281533a631aa70c794e62ea96f4",
            "x86_64",
            "7.2.5-3-omarchy",
            "Wayland",
            "Hyprland",
            "1920x1080",
            "1.25",
            "60 Hz",
            "AMD Lucienne",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.readme)

        for scope in (
            "X11",
            "multi-monitor",
            "other architectures",
            "other display scaling values",
        ):
            with self.subTest(scope=scope):
                self.assertIn(scope, self.readme)

    def test_readme_has_public_support_route(self):
        self.assertIn(
            "https://github.com/ariDev1/transNote/issues",
            self.readme,
        )

    def test_security_policy_exists_and_states_review_boundary(self):
        self.assertTrue(SECURITY.is_file())
        text = SECURITY.read_text(encoding="utf-8")
        lower = text.lower()

        self.assertIn("security", lower)
        self.assertIn("do not publish", lower)
        self.assertIn("vulnerability", lower)
        self.assertIn("not a security audit", lower)
        self.assertIn("https://github.com/ariDev1/transNote", text)

    def test_third_party_notice_records_verified_runtime_dependency(self):
        self.assertTrue(THIRD_PARTY.is_file())
        text = THIRD_PARTY.read_text(encoding="utf-8")

        required = (
            "nostr-tools",
            "2.25.2",
            "Unlicense",
            "nostr/sync.bundle.mjs",
            "package-lock.json",
            "MIT",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_release_notes_exist_for_manifest_version(self):
        self.assertTrue(RELEASE_NOTES.is_file())
        text = RELEASE_NOTES.read_text(encoding="utf-8")

        self.assertIn("0.5.6", text)
        self.assertIn("Agent CLI", text)
        self.assertIn("OpenCode", text)

    def test_preview_capture_instructions_record_reference_environment(self):
        self.assertTrue(PREVIEW_CAPTURE.is_file())
        text = PREVIEW_CAPTURE.read_text(encoding="utf-8")

        required = (
            "preview.png",
            "1920x1080",
            "1.25",
            "60 Hz",
            "Wayland",
            "Hyprland",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)


if __name__ == "__main__":
    unittest.main()
