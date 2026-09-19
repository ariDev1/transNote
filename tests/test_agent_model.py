import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "Agent.js"


def node_eval(script):
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip())


class AgentModelTests(unittest.TestCase):
    def test_agent_module_exists(self):
        self.assertTrue(AGENT.is_file())

    def test_protocol_version_is_one(self):
        out = node_eval(
            "const A=require('./Agent.js');"
            "console.log(JSON.stringify(A.PROTOCOL_VERSION));"
        )
        self.assertEqual(out, 1)

    def test_note_serialization_has_fixed_public_fields(self):
        out = node_eval(
            """
const A=require('./Agent.js');
const note={
  id:'note-1',
  title:'Measurement',
  body:'Tests PASS',
  author:'labor',
  createdAt:'2026-09-19T08:00:00.000Z',
  updatedAt:'2026-09-19T08:01:00.000Z',
  shared:false,
  comments:[],
  attachments:[{id:'att-secret',name:'secret.bin'}],
  secretPath:'/home/user/private',
  internalState:'hidden'
};
console.log(JSON.stringify(A.serializeNote(note,'local')));
"""
        )

        self.assertEqual(
            list(out.keys()),
            [
                "id",
                "title",
                "body",
                "author",
                "createdAt",
                "updatedAt",
                "shared",
                "source",
                "comments",
            ],
        )
        self.assertEqual(out["source"], "local")
        self.assertNotIn("attachments", out)
        self.assertNotIn("secretPath", out)
        self.assertNotIn("internalState", out)

    def test_comment_serialization_has_fixed_public_fields(self):
        out = node_eval(
            """
const A=require('./Agent.js');
console.log(JSON.stringify(A.serializeComment({
  id:'c-1',
  author:'labor',
  text:'Confirmed',
  createdAt:'2026-09-19T08:02:00.000Z',
  secret:'no'
})));
"""
        )

        self.assertEqual(
            list(out.keys()),
            ["id", "author", "text", "createdAt"],
        )
        self.assertNotIn("secret", out)

    def test_invalid_source_is_rejected(self):
        out = node_eval(
            """
const A=require('./Agent.js');
console.log(JSON.stringify(A.serializeNote({
  id:'note-1',
  title:'x',
  body:'y',
  author:'labor',
  createdAt:'a',
  updatedAt:'b',
  shared:false,
  comments:[]
},'filesystem')));
"""
        )
        self.assertIsNone(out)

    def test_search_matches_title_and_body_case_insensitively(self):
        out = node_eval(
            """
const A=require('./Agent.js');
const notes=[
  {id:'1',title:'Voltage Test',body:'alpha'},
  {id:'2',title:'Other',body:'MEASUREMENT result'},
  {id:'3',title:'Other',body:'nothing'}
];
console.log(JSON.stringify(A.searchNotes(notes,'measurement')));
"""
        )

        self.assertEqual([n["id"] for n in out], ["2"])

        out = node_eval(
            """
const A=require('./Agent.js');
const notes=[
  {id:'1',title:'Voltage Test',body:'alpha'},
  {id:'2',title:'Other',body:'beta'}
];
console.log(JSON.stringify(A.searchNotes(notes,'VOLTAGE')));
"""
        )

        self.assertEqual([n["id"] for n in out], ["1"])

    def test_search_preserves_input_order(self):
        out = node_eval(
            """
const A=require('./Agent.js');
const notes=[
  {id:'b',title:'match',body:''},
  {id:'a',title:'match',body:''},
  {id:'c',title:'match',body:''}
];
console.log(JSON.stringify(A.searchNotes(notes,'match')));
"""
        )

        self.assertEqual([n["id"] for n in out], ["b", "a", "c"])

    def test_search_does_not_match_internal_fields(self):
        out = node_eval(
            """
const A=require('./Agent.js');
const notes=[{
  id:'secret-match',
  title:'ordinary',
  body:'ordinary',
  author:'match-author',
  comments:[{text:'match-comment'}],
  attachments:[{name:'match-file'}]
}];
console.log(JSON.stringify(A.searchNotes(notes,'match')));
"""
        )

        self.assertEqual(out, [])


    def test_capabilities_manifest_is_fixed_and_restricted(self):
        out = node_eval(
            "const A=require('./Agent.js');"
            "console.log(JSON.stringify(A.capabilities()));"
        )

        self.assertEqual(
            list(out.keys()),
            ["commands", "errorExitCodes", "unsupported"],
        )

        self.assertEqual(
            list(out["commands"].keys()),
            [
                "status",
                "capabilities",
                "list",
                "get",
                "search",
                "create",
                "comment",
            ],
        )

        self.assertEqual(
            out["commands"]["status"],
            {
                "mutates": False,
                "arguments": [],
                "errors": [],
            },
        )
        self.assertEqual(
            out["commands"]["capabilities"],
            {
                "mutates": False,
                "arguments": [],
                "errors": [],
            },
        )
        self.assertEqual(
            out["commands"]["list"],
            {
                "mutates": False,
                "arguments": [],
                "errors": ["TRANSNOTE_NOT_READY"],
            },
        )
        self.assertEqual(
            out["commands"]["get"],
            {
                "mutates": False,
                "arguments": [
                    {
                        "name": "noteId",
                        "kind": "positional",
                        "required": True,
                        "nonEmpty": True,
                    }
                ],
                "errors": [
                    "TRANSNOTE_NOT_READY",
                    "NOTE_NOT_FOUND",
                ],
            },
        )
        self.assertEqual(
            out["commands"]["search"],
            {
                "mutates": False,
                "arguments": [
                    {
                        "name": "query",
                        "kind": "positional",
                        "required": True,
                        "nonEmpty": True,
                    }
                ],
                "errors": [
                    "TRANSNOTE_NOT_READY",
                    "INVALID_ARGUMENT",
                ],
            },
        )
        self.assertEqual(
            out["commands"]["create"],
            {
                "mutates": True,
                "arguments": [
                    {
                        "name": "title",
                        "kind": "option",
                        "flag": "--title",
                        "required": False,
                    },
                    {
                        "name": "body",
                        "kind": "option",
                        "flag": "--body",
                        "required": False,
                    },
                ],
                "constraints": [
                    {
                        "kind": "atLeastOneNonEmpty",
                        "arguments": ["title", "body"],
                    }
                ],
                "errors": [
                    "TRANSNOTE_NOT_READY",
                    "EMPTY_NOTE",
                ],
            },
        )
        self.assertEqual(
            out["commands"]["comment"],
            {
                "mutates": True,
                "arguments": [
                    {
                        "name": "noteId",
                        "kind": "positional",
                        "required": True,
                        "nonEmpty": True,
                    },
                    {
                        "name": "text",
                        "kind": "option",
                        "flag": "--text",
                        "required": True,
                        "nonEmpty": True,
                    },
                ],
                "errors": [
                    "TRANSNOTE_NOT_READY",
                    "NOTE_NOT_FOUND",
                    "EMPTY_COMMENT",
                ],
            },
        )

        self.assertEqual(
            out["errorExitCodes"],
            {
                "MISSING_ARGUMENT": 2,
                "INVALID_ARGUMENT": 2,
                "UNKNOWN_OPTION": 2,
                "UNKNOWN_COMMAND": 2,
                "EMPTY_NOTE": 2,
                "EMPTY_COMMENT": 2,
                "TRANSNOTE_NOT_READY": 3,
                "TRANSNOTE_UNAVAILABLE": 3,
                "NOTE_NOT_FOUND": 4,
                "PROTOCOL_ERROR": 5,
            },
        )

        self.assertEqual(
            out["unsupported"],
            [
                "delete",
                "share",
                "unshare",
                "hide",
                "pairing",
                "syncAdministration",
                "attachmentMutation",
                "filesystemAccess",
                "commandForwarding",
                "identityOverride",
            ],
        )

if __name__ == "__main__":
    unittest.main()
