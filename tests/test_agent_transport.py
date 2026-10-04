"""Exercise the actual QML descriptor reader and TypeScript adapter transport."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentTransportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("qs"), "Quickshell is required")
    def test_qml_reads_fresh_descriptors_and_rejects_invalid_requests(self):
        panel = (ROOT / "Panel.qml").read_text()
        start = panel.index("  Component {\n    id: agentRequestReader")
        end = panel.index("  IpcHandler {", start)
        transport = panel[start:end]
        cases = [
            ({"method": "create", "arguments": ["private ä", "body\ntext"]},
             {"method": "create", "arguments": ["private ä", "body\ntext"]}),
            ({"method": "comment", "arguments": ["note", "second request"]},
             {"method": "comment", "arguments": ["note", "second request"]}),
            ({"method": "search", "arguments": ["query"]},
             {"method": "search", "arguments": ["query"]}),
            ({"method": "delete", "arguments": []}, {"error": "INVALID_ARGUMENT"}),
            ({"method": "toString", "arguments": []}, {"error": "INVALID_ARGUMENT"}),
            ({"method": "create", "arguments": [1, "text"]}, {"error": "INVALID_ARGUMENT"}),
            ({"method": "create", "arguments": ["title"]}, {"error": "INVALID_ARGUMENT"}),
            (None, {"error": "INVALID_ARGUMENT"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            handles = []
            self.addCleanup(lambda: [f.close() for f in handles])
            paths = []
            for request, _ in cases:
                f = tempfile.TemporaryFile()
                handles.append(f)
                f.write(json.dumps(request).encode())
                f.flush()
                paths.append(f"/proc/{os.getpid()}/fd/{f.fileno()}")
            paths += ["/etc/passwd", "/proc/99999999/fd/0"]
            expected = [result for _, result in cases] + [{"error": "INVALID_ARGUMENT"}] * 2
            stubs = '\n'.join(
                f'function agent{name.capitalize()}Json({params}) {{ return JSON.stringify({{method: "{name}", arguments: [{params}]}}) }}'
                for name, params in [("status", ""), ("capabilities", ""), ("list", ""),
                                     ("get", "a"), ("search", "a"), ("create", "a,b"),
                                     ("comment", "a,b"), ("share", "a")])
            qml = '''import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
 id: root
 function agentError(code, message) { return JSON.stringify({error: code}) }
''' + stubs + transport + '''
 Timer {
 interval: 10; running: true; repeat: false
 onTriggered: {
   var paths = PATHS
   var results = paths.map(function(path) { return JSON.parse(agentRequestJson(path)) })
   console.log("TRANSPORT_RESULT:" + JSON.stringify(results))
   Qt.quit()
 }
 }
}
'''.replace("PATHS", json.dumps(paths))
            config = Path(directory) / "shell.qml"
            config.write_text(qml)
            runtime = Path(directory) / "runtime"
            runtime.mkdir(mode=0o700)
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="", XDG_RUNTIME_DIR=str(runtime),
                       XDG_CACHE_HOME=directory)
            result = subprocess.run(["qs", "-p", str(config), "--no-color"], env=env,
                                    capture_output=True, text=True, timeout=15)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            line = next((line for line in output.splitlines() if "TRANSPORT_RESULT:" in line), "")
            self.assertTrue(line, output)
            self.assertEqual(json.loads(line.split("TRANSPORT_RESULT:", 1)[1]), expected)

    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_adapter_sends_private_arguments_only_through_stdin(self):
        script = r'''
const fs = require("fs");
const {stripTypeScriptTypes} = require("node:module");
let source = fs.readFileSync("tools/opencode/transnote.ts", "utf8");
source = source.replace('import { tool } from "@opencode-ai/plugin"', `
const tool = Object.assign(x => x, {schema: {string: () => ({describe: () => ({})})}})`);
const code = stripTypeScriptTypes(source).replace(/export const (\w+) =/g, "const $1 =");
const calls = [];
global.Bun = {spawn(argv, options) {
  calls.push({argv, stdin: options.stdin});
  return {stdout: new Blob(['{"ok":true}']), stderr: new Blob([]), exited: Promise.resolve(0)};
}};
const mod = {exports: {}};
new Function("module", "exports", code + "\nmodule.exports = {create, comment, search};")(mod, mod.exports);
(async () => {
 await mod.exports.create.execute({title: "private title ä", body: "private body\ntext"});
 await mod.exports.comment.execute({noteId: "note", text: "private comment"});
 await mod.exports.search.execute({query: "private search"});
 console.log(JSON.stringify(await Promise.all(calls.map(async x => ({argv: x.argv, input: await x.stdin.text()})))));
})().catch(e => {console.error(e); process.exit(1)});
'''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = json.loads(result.stdout)
        expected = [["create", "--title", "private title ä", "--body", "private body\ntext"],
                    ["comment", "note", "--text", "private comment"], ["search", "private search"]]
        for call, arguments in zip(calls, expected):
            self.assertEqual(call["argv"], [str(Path.home() / ".local/bin/transnote-agent"), "--json-stdin"])
            self.assertEqual(json.loads(call["input"]), arguments)
