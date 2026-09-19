import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"


class AgentIpcContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = PANEL.read_text(encoding="utf-8")

    def function_block(self, name):
        start = self.panel.index(f"  function {name}(")

        next_function = self.panel.find(
            "\n  function ",
            start + 1,
        )
        ipc_marker = self.panel.find(
            "\n  // ---------------------------------------------------------------- IPC",
            start,
        )

        candidates = [
            pos for pos in (next_function, ipc_marker)
            if pos != -1
        ]
        end = min(candidates)

        return self.panel[start:end]

    def agent_section(self):
        start = self.panel.index(
            "  // --------------------------------------------------------- agent API"
        )
        end = self.panel.index(
            "  // ---------------------------------------------------------------- IPC",
            start,
        )
        return self.panel[start:end]

    def test_agent_model_is_imported(self):
        self.assertIn(
            'import "Agent.js" as Agent',
            self.panel,
        )

    def test_agent_has_separate_fixed_ipc_target(self):
        section = self.agent_section()

        self.assertIn(
            'target: "aridev1.transnote.agent"',
            section,
        )

    def test_only_v1_agent_methods_are_exposed(self):
        section = self.agent_section()

        for method in (
            "status",
            "list",
            "search",
            "create",
            "comment",
        ):
            self.assertIn(
                f"function {method}(",
                section,
            )

        for forbidden in (
            "delete",
            "share",
            "unshare",
            "hide",
            "pair",
            "syncthing",
            "attach",
            "execute",
            "dispatch",
            "forward",
        ):
            self.assertNotIn(
                f"function {forbidden}(",
                section,
            )

    def test_agent_list_uses_visible_notes_only(self):
        body = self.function_block("agentListJson")

        self.assertIn("displayNotes", body)
        self.assertIn("Agent.serializeNote", body)
        self.assertNotIn("notesFile", body)
        self.assertNotIn("notesPath", body)
        self.assertNotIn("syncSnapshotPath", body)

    def test_agent_search_filters_visible_notes_only(self):
        body = self.function_block("agentSearchJson")

        self.assertIn(
            "Agent.searchNotes(displayNotes, query)",
            body,
        )
        self.assertNotIn("localNotes.concat", body)
        self.assertNotIn("allPeerNotes()", body)

    def test_agent_create_uses_current_transnote_identity(self):
        body = self.function_block("agentCreateJson")

        self.assertIn(
            "Store.createNote(title, body, myId)",
            body,
        )
        self.assertIn("persist()", body)
        self.assertNotIn("setShared", body)
        self.assertNotIn("authorOverride", body)
        self.assertNotIn("identityOverride", body)

    def test_agent_comment_requires_visible_note(self):
        body = self.function_block("agentCommentJson")

        self.assertIn("agentVisibleNote(noteId)", body)
        self.assertIn("Store.addComment", body)
        self.assertIn(
            "Store.createComment(myId, text)",
            body,
        )
        self.assertIn("outbox", body)
        self.assertIn("persist()", body)

    def test_agent_status_uses_protocol_version(self):
        status = self.function_block("agentStatusJson")
        response = self.function_block("agentResponse")

        self.assertIn("Agent.PROTOCOL_VERSION", response)
        self.assertIn("myId", status)
        self.assertIn("syncConfigured", status)
        self.assertIn("displayNotes.length", status)

    def test_agent_source_is_derived_from_trusted_runtime_sets(self):
        body = self.function_block("agentSourceForNote")

        self.assertIn("isLocalNote", body)
        self.assertIn("peerNotes", body)
        self.assertIn("nostrPeerNotes", body)
        self.assertNotIn("author ==", body)

    def test_agent_visible_lookup_uses_display_notes(self):
        body = self.function_block("agentVisibleNote")

        self.assertIn("displayNotes", body)
        self.assertNotIn("localNotes", body)
        self.assertNotIn("peerNotes", body)

    def test_agent_errors_are_structured_json(self):
        section = self.agent_section()
        error = self.function_block("agentError")

        self.assertIn("ok: false", error)
        self.assertIn("code: code", error)
        self.assertIn("message: message", error)

        for code in (
            "NOTE_NOT_FOUND",
            "EMPTY_NOTE",
            "EMPTY_COMMENT",
        ):
            self.assertIn(
                f'agentError("{code}"',
                section,
            )


    def test_agent_ipc_methods_have_explicit_types(self):
        section = self.agent_section()

        expected = (
            "function status(): string",
            "function capabilities(): string",
            "function list(): string",
            "function get(noteId: string): string",
            "function search(query: string): string",
            "function create(title: string, body: string): string",
            "function comment(noteId: string, text: string): string",
        )

        for signature in expected:
            with self.subTest(signature=signature):
                self.assertIn(signature, section)


    def test_agent_capabilities_are_static_interface_metadata(self):
        body = self.function_block("agentCapabilitiesJson")

        self.assertIn("Agent.capabilities()", body)
        self.assertNotIn("agentReady()", body)
        self.assertNotIn("localNotes", body)
        self.assertNotIn("peerNotes", body)
        self.assertNotIn("displayNotes", body)


    def test_agent_get_uses_visible_note_and_public_serializer(self):
        body = self.function_block("agentGetJson")

        self.assertIn("agentReady()", body)
        self.assertIn("agentVisibleNote(noteId)", body)
        self.assertIn("agentNoteView(visible)", body)
        self.assertIn("agentSourceForNote(visible.id)", body)
        self.assertIn("Agent.serializeNote", body)
        self.assertIn('agentError("NOTE_NOT_FOUND"', body)

        self.assertNotIn("localNotes", body)
        self.assertNotIn("peerNotes", body)
        self.assertNotIn("nostrPeerNotes", body)
        self.assertNotIn("persist()", body)
        self.assertNotIn("Store.createNote", body)
        self.assertNotIn("Store.addComment", body)

if __name__ == "__main__":
    unittest.main()
