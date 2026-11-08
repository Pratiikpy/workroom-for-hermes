"""A stand-in host for the page editor so it can be driven in a plain browser: python canvas_harness.py <port>.

It plays the host's role exactly as the Desktop page does: the frame runs in an iframe, the host checks messages from it, forwards edits to the real
Service (the authority) and answers with ack or error. Every message is logged to /log so a test can read what crossed the boundary.
"""

import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.tests.test_create_flow import _workbook  # noqa: E402
from workroom.tests.test_scene_flow import SPEC  # noqa: E402
from workroom.workroom_core.service import Service, ServiceError  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "dashboard"
REL = "pages/q2.scene.json"

PAGE = """<!doctype html><meta charset=utf-8><title>host</title>
<iframe id=f src="/frame" style="width:100%;height:96vh;border:0" sandbox="allow-scripts"></iframe>
<script>
const f = document.getElementById('f');
async function call(path, body) { const r = await fetch(path, {method:'POST', body: JSON.stringify(body)}); return r.json(); }
async function load() { const d = await call('/open', {}); f.contentWindow.postMessage({op:'load', scene:d.scene, rev:d.rev}, '*'); }
window.addEventListener('message', async (e) => {
  if (e.source !== f.contentWindow) return;
  const m = e.data; call('/log', {dir:'frame->host', origin:e.origin, m});
  if (m.op === 'ready') load();
  else if (m.op === 'patch') { const r = await call('/apply', {rev:m.rev, ops:m.ops}); f.contentWindow.postMessage(r.error ? {op:'error', message:r.error, scene:r.scene, rev:r.rev} : {op:'ack', rev:r.rev, scene:r.scene}, '*'); }
  else if (m.op === 'save') { const r = await call('/save', {}); f.contentWindow.postMessage({op:'say', message: r.error || ('Staged release ' + r.release_id)}, '*'); }
});
</script>"""


svc = pid = root = None
LOG: list[dict] = []


def setup() -> None:
    global svc, pid, root
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "proj"
    root.mkdir()
    _workbook(root, 175)
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    staged = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    LOG.clear()


def start(port: int = 0):
    """Start the harness on a free port and return (server, base url). Call server.shutdown() when done."""
    import threading

    setup()
    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class H(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/frame":
            self._send((HERE / "canvas.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/log":
            self._send(json.dumps(LOG).encode())
        elif self.path == "/disk":
            self._send((root / REL).read_bytes())
        else:
            self._send(PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/open":
                out = svc.scene_open(pid, REL)
            elif self.path == "/apply":
                try:
                    out = svc.scene_apply(pid, REL, body["rev"], body["ops"])
                except ServiceError as exc:
                    cur = svc.scene_open(pid, REL)
                    out = {"error": str(exc), "scene": cur["scene"], "rev": cur["rev"]}
            elif self.path == "/save":
                out = svc.scene_save(pid, REL)
            else:
                LOG.append(body)
                out = {"ok": True}
        except ServiceError as exc:
            out = {"error": str(exc)}
        self._send(json.dumps(out).encode())

    def log_message(self, *a) -> None:
        pass


if __name__ == "__main__":
    server, url = start(int(sys.argv[1]))
    print(url, flush=True)
    import time

    while True:
        time.sleep(3600)
