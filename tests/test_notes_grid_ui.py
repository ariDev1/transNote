import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Panel.qml"


class NotesGridUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PANEL.read_text(encoding="utf-8")

    def test_list_and_square_grid_are_user_switchable(self):
        self.assertIn('property string notesLayoutMode: "list"', self.text)
        self.assertIn('text: "List"', self.text)
        self.assertIn('text: "Grid"', self.text)
        self.assertIn('onClicked: root.notesLayoutMode = "grid"', self.text)
        self.assertIn('onClicked: root.notesLayoutMode = "list"', self.text)

    def test_grid_tiles_select_without_changing_layout(self):
        self.assertIn('id: notesGrid', self.text)
        self.assertIn('readonly property var notesGridRows', self.text)
        self.assertIn('height: root.notesGridTileSize', self.text)
        self.assertIn('property var bodyPreview: Store.previewBody(note.body)', self.text)
        self.assertIn('root.gridSelectedNoteId = note.id', self.text)
        self.assertIn('border.width: root.gridSelectedNoteId === note.id ? 2 : 1', self.text)
        self.assertIn('text: "Select a square, then choose Open to show full details above its row."', self.text)
        self.assertIn('text: root.gridDetailOpen ? "Close" : "Open"', self.text)
        self.assertIn('Math.floor(root.gridSelectedNoteIndex / root.notesGridColumns) === modelData.rowIndex', self.text)
        self.assertIn('text: root.gridSelectedNote ? root.gridSelectedNote.body : ""', self.text)
        self.assertIn('text: "Full controls in List"', self.text)
        self.assertIn('onClicked: root.notesLayoutMode = "list"', self.text)
        self.assertIn('t === "o" && notesLayoutMode === "grid"', self.text)


if __name__ == "__main__":
    unittest.main()
