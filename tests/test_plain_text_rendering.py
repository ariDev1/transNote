import json
import re
import unittest

from test_lan_security import PANEL, run_store


def text_formats():
    """Read direct format bindings, excluding nested objects and quoted text."""
    source = PANEL.read_text(encoding="utf-8")
    masked = re.sub(
        r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\x27(?:\\.|[^\x27\\])*\x27',
        lambda match: re.sub(r"[^\n]", " ", match.group()),
        source,
    )
    formats = []
    for match in re.finditer(r"\bText\s*\{", masked):
        depth = 1
        direct = []
        for char in masked[match.end():]:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            if depth == 0:
                break
            direct.append(char if depth == 1 else " ")
        bindings = re.findall(r"\btextFormat\s*:\s*(Text\.\w+)", "".join(direct))
        formats.append((source.count("\n", 0, match.start()) + 1, bindings))
    return formats


class PlainTextRenderingTests(unittest.TestCase):
    def test_panel_text_cannot_auto_detect_network_loading_markup(self):
        formats = text_formats()
        self.assertTrue(formats, "No panel Text renderers found")
        for line, bindings in formats:
            with self.subTest(line=line):
                self.assertEqual(bindings, ["Text.PlainText"])

    def test_nostr_text_survives_the_data_boundary_without_html_rewriting(self):
        author = "a" * 64
        samples = [
            '<img src="https://example.invalid/probe.png">',
            '<a href="https://example.invalid/">click</a>',
            'a < b > c & d https://example.invalid/ **bold**',
            '```html\n<img src="https://example.invalid/code.png">\n```',
        ]
        for text in samples:
            with self.subTest(text=text):
                raw = {
                    "notes": [{"id": "note-safe-1", "author": author,
                               "title": text, "body": text}],
                    "pairs": [{"noteId": "note-safe-1", "comment": {
                        "id": "comment-safe-1", "author": author, "text": text}}],
                }
                result = run_store("Store.sanitizeNostrFetch(" + json.dumps(raw)
                                   + ", [" + json.dumps(author) + "], '', {})")
                self.assertEqual(result["notes"][0]["title"], text)
                self.assertEqual(result["notes"][0]["body"], text)
                self.assertEqual(result["pairs"][0]["comment"]["text"], text)
