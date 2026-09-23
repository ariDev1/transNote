import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"
README = ROOT / "README.md"


def node_eval(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip())


class AgentProvenanceModelTests(unittest.TestCase):
    def test_sanitize_provenance_accepts_only_safe_unique_ids(self):
        out = node_eval(
            '''
const A=require('./Agent.js');
console.log(JSON.stringify(A.sanitizeProvenance({
  notes:['note-a','note-a','../bad',''],
  comments:['c-1','c-1','/bad'],
  extra:['secret']
})));
'''
        )
        self.assertEqual(out, {"notes": ["note-a"], "comments": ["c-1"]})

    def test_mark_and_lookup_note_provenance(self):
        out = node_eval(
            '''
const A=require('./Agent.js');
let p=A.markProvenance({},'note','note-1');
console.log(JSON.stringify({
  p:p,
  note:A.hasProvenance(p,'note','note-1'),
  comment:A.hasProvenance(p,'comment','note-1')
}));
'''
        )
        self.assertEqual(
            out,
            {
                "p": {"notes": ["note-1"], "comments": []},
                "note": True,
                "comment": False,
            },
        )

    def test_mark_and_lookup_comment_provenance(self):
        out = node_eval(
            '''
const A=require('./Agent.js');
let p=A.markProvenance({},'comment','c-1');
console.log(JSON.stringify({
  p:p,
  comment:A.hasProvenance(p,'comment','c-1')
}));
'''
        )
        self.assertEqual(
            out,
            {
                "p": {"notes": [], "comments": ["c-1"]},
                "comment": True,
            },
        )


class AgentProvenancePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")

    def function_block(self, name):
        start = self.panel.index(f"  function {name}(")
        next_function = self.panel.find("\n  function ", start + 1)
        if next_function == -1:
            return self.panel[start:]
        return self.panel[start:next_function]

    def test_local_state_persists_provenance_but_snapshot_does_not(self):
        persist = self.function_block("persist")
        snapshot = self.function_block("writeSnapshot")

        self.assertIn(
            "agentProvenance: Agent.sanitizeProvenance(agentProvenance)",
            persist,
        )
        self.assertNotIn("agentProvenance", snapshot)

    def test_local_load_restores_provenance(self):
        load = self.function_block("loadLocal")
        self.assertIn(
            "Agent.sanitizeProvenance(parsed && parsed.agentProvenance)",
            load,
        )
        self.assertIn("agentProvenance = provenance", load)

    def test_agent_create_marks_note_only(self):
        body = self.function_block("agentCreateJson")
        self.assertIn(
            'Agent.markProvenance(agentProvenance, "note", note.id)',
            body,
        )

        human = self.function_block("addNote")
        self.assertNotIn("markProvenance", human)

    def test_agent_comment_marks_comment_only(self):
        body = self.function_block("agentCommentJson")
        self.assertIn(
            'Agent.markProvenance(agentProvenance, "comment", comment.id)',
            body,
        )

        human = self.function_block("addComment")
        self.assertNotIn("markProvenance", human)

    def test_ui_has_subtle_agent_markers(self):
        self.assertIn("visible: root.isAgentNote(note.id)", self.panel)
        self.assertIn('text: "AI"', self.panel)
        self.assertIn(
            'root.isAgentComment(modelData.id) ? "AI · " : ""',
            self.panel,
        )

    def test_readme_states_provenance_is_local_only(self):
        lower = self.readme.lower()
        self.assertIn("agent provenance", lower)
        self.assertIn("local-only", lower)
        self.assertIn("not synchronized", lower)


if __name__ == "__main__":
    unittest.main()
