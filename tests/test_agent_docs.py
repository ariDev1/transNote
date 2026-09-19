import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


class AgentDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = README.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()

    def test_readme_has_optional_agent_cli_section(self):
        self.assertIn("## Optional Agent CLI", self.text)

    def test_readme_documents_explicit_install_and_remove(self):
        self.assertIn("./tools/install-agent-cli.sh", self.text)
        self.assertIn("./tools/uninstall-agent-cli.sh", self.text)
        self.assertIn("~/.local/bin/transnote-agent", self.text)

    def test_readme_documents_supported_commands(self):
        for command in (
            "transnote-agent status",
            "transnote-agent capabilities",
            "transnote-agent list",
            "transnote-agent get",
            "transnote-agent search",
            "transnote-agent create",
            "transnote-agent comment",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.text)

    def test_readme_documents_json_protocol(self):
        self.assertIn("JSON", self.text)
        self.assertIn("protocolVersion", self.text)
        self.assertIn("current protocol version is `1`", self.lower)

    def test_readme_documents_exit_codes(self):
        for code in ("`0`", "`2`", "`3`", "`4`", "`5`"):
            with self.subTest(code=code):
                self.assertIn(code, self.text)

    def test_readme_documents_private_creation(self):
        self.assertIn("private by default", self.lower)
        self.assertIn("does not share", self.lower)

    def test_readme_documents_local_identity(self):
        self.assertIn("existing local transnote identity", self.lower)
        self.assertIn("author override", self.lower)

    def test_readme_documents_restricted_capabilities(self):
        for word in (
            "delete",
            "share",
            "unshare",
            "hide",
            "pairing",
            "attachment",
        ):
            with self.subTest(word=word):
                self.assertIn(word, self.lower)

    def test_readme_documents_security_boundary(self):
        self.assertIn("not a sandbox", self.lower)
        self.assertIn("full shell access", self.lower)

    def test_project_structure_lists_agent_files(self):
        for path in (
            "Agent.js",
            "bin/transnote-agent",
            "tools/install-agent-cli.sh",
            "tools/uninstall-agent-cli.sh",
        ):
            with self.subTest(path=path):
                self.assertIn(path, self.text)



    def test_readme_documents_machine_readable_contract_constraints(self):
        self.assertIn("non-empty", self.lower)
        self.assertIn("at least one", self.lower)
        self.assertIn("expected command errors", self.lower)

    def test_readme_states_protocol_version_is_on_errors_too(self):
        self.assertIn("including locally generated errors", self.lower)

if __name__ == "__main__":
    unittest.main()
