import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class CiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exists = WORKFLOW.is_file()
        cls.text = WORKFLOW.read_text(encoding="utf-8") if cls.exists else ""

    def test_ci_workflow_exists(self):
        self.assertTrue(self.exists, ".github/workflows/ci.yml is missing")

    def test_ci_has_read_only_repository_permission(self):
        self.assertIn("permissions:", self.text)
        self.assertIn("contents: read", self.text)

    def test_ci_runs_on_push_and_pull_request(self):
        self.assertIn("push:", self.text)
        self.assertIn("pull_request:", self.text)

    def test_ci_uses_explicit_runner(self):
        self.assertIn("runs-on: ubuntu-24.04", self.text)

    def test_ci_pins_checkout_action(self):
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
            self.text,
        )

    def test_ci_pins_python_action_and_tested_version(self):
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
            self.text,
        )
        self.assertIn('python-version: "3.14.7"', self.text)

    def test_ci_pins_node_action_and_tested_version(self):
        self.assertIn(
            "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
            self.text,
        )
        self.assertIn('node-version: "26.8.2"', self.text)

    def test_ci_runs_portable_repository_test_entry_point(self):
        self.assertIn("run: ./tests/run", self.text)

    def test_ci_does_not_install_runtime_dependencies(self):
        forbidden = (
            "npm install",
            "npm ci",
            "pip install",
            "apt-get",
            "sudo ",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.text)


if __name__ == "__main__":
    unittest.main()
