"""Optional Qt runtime probe: PYTHONPATH=<PySide6 path> python3 tests/qml_plain_text_probe.py.

Run Text with the panel's actual format bindings. This does not run Quickshell
or prove the full LAN/Nostr field workflow.
"""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from test_plain_text_rendering import text_formats


requests = []


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def pump(app):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QGuiApplication([])
    engine = QQmlEngine()
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    components, objects = [], []

    def render(binding, path):
        component = QQmlComponent(engine)
        component.setData(("import QtQuick\nText { width: 800; "
                           "textFormat: " + binding + " }").encode(), QUrl())
        obj = component.create()
        assert obj is not None, [error.toString() for error in component.errors()]
        payload = ('<img src="http://127.0.0.1:' + str(server.server_port)
                   + '/' + path + '"> <a href="https://example.invalid/">link</a>'
                   + '\n<>& **Markdown** ```code```')
        obj.setProperty("text", payload)
        assert obj.property("text") == payload
        components.append(component)
        objects.append(obj)

    try:
        render("Text.AutoText", "positive-control")
        pump(app)
        assert requests == ["/positive-control"], requests
        requests.clear()
        for line, bindings in text_formats():
            render(bindings[0] if bindings else "Text.AutoText", "panel-" + str(line))
        pump(app)
        assert requests == [], "Panel text fetched URLs: " + repr(requests)
        print("PASS: AutoText fetched the control URL; all 53 panel Text policies made zero requests and retained literal input.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
