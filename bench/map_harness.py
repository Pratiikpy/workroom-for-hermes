"""Draw the change map from a real project in a real browser, and exercise it.

    python map_harness.py <output folder for screenshots>

A real Service builds a project (a deck, a report, a workbook), the workbook changes, and the Changes inbox JSON the Desktop screen receives is served to a
page that loads the real desktop/plugin.js with a stub of the Hermes SDK. React comes from a CDN, so this needs network access and a Chromium-based browser.
"""

import http.server
import json
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKROOM = HERE.parent
sys.path.insert(0, str(WORKROOM.parent))

PLUGIN = WORKROOM / "desktop" / "plugin.js"

SDK = """
export const TRANSCRIPT_DIRECTIVE_AREA = 'transcript.directive'
export const host = { composer: { submit: async () => true }, request: async () => ({}) }
export function SandboxedFrame() { return null }
"""

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>map</title>
<script type="importmap">{ "imports": { "react": "https://esm.sh/react@19.1.0", "react/jsx-runtime": "https://esm.sh/react@19.1.0/jsx-runtime", "@hermes/plugin-sdk": "/sdk.js",
  "react-dom/client": "https://esm.sh/react-dom@19.1.0/client?deps=react@19.1.0" } }</script>
<style>
:root { color-scheme: light dark; --ui-text-primary:#1c1c1e; --ui-text-tertiary:#6b6b70; --ui-stroke-secondary:#d6d6da; --ui-stroke-tertiary:#e6e6ea; --ui-bg-elevated:#fff; --ui-control-hover-background:#f0f0f3; --ui-accent:#2f6feb; --ui-red:#d33; --ui-green:#1a8f4b; --ui-amber:#b45309; background:#f6f6f8; }
body.dark { --ui-text-primary:#f2f2f4; --ui-text-tertiary:#9a9aa2; --ui-stroke-secondary:#3a3a40; --ui-stroke-tertiary:#2a2a2f; --ui-bg-elevated:#1c1c20; --ui-control-hover-background:#26262b; --ui-accent:#5a8dff; --ui-red:#ff6b6b; --ui-green:#4cc38a; --ui-amber:#f59e0b; background:#141417; color:#f2f2f4; }
body { margin:0; font-family:"Segoe UI",system-ui,sans-serif; font-size:13px; padding:16px; }
</style></head><body><div id="root"></div>
<script type="module">
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { ChangeViews } from '/plugin-test.js'
const inbox = await (await fetch('/inbox.json')).json()
const revealed = []
window.__revealed = revealed
const ctx = { os: { revealPath: async (p) => { revealed.push(p); return true } } }
if (location.hash.includes('dark')) document.body.classList.add('dark')
createRoot(document.getElementById('root')).render(createElement(ChangeViews, { inbox, folder: 'C:\\\\Reports\\\\Monthly', ctx }))
window.__ready = true
</script></body></html>"""


def build_project(root: Path, state: Path) -> tuple[dict, dict]:
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches
    from xlsxwriter import Workbook

    from workroom.workroom_core.service import Service

    def workbook(revenue, income, margin, headcount, cogs):
        with Workbook(str(root / "results.xlsx")) as wb:
            ws = wb.add_worksheet("Results")
            ws.write_row(0, 0, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"])
            ws.write_row(1, 0, ["Net revenue", 13_000_000, revenue, 15_100_000])
            ws.write_row(2, 0, ["Operating income", 1_850_000, income, 2_640_000])
            ws.write_row(3, 0, ["Gross margin", 0.41, margin, 0.43])
            ws.write_row(4, 0, ["Headcount", 410, headcount, 455])
            if cogs is not None:
                ws.write_row(5, 0, ["Cost of goods sold", 7_100_000, cogs, 8_900_000])

    root.mkdir(parents=True, exist_ok=True)
    workbook(14_000_000, 2_210_000, 0.42, 431, 8_200_000)
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[5])
    first.shapes.title.text = "Quarterly business review"
    for i, line in enumerate(["Net revenue was $14.0 million in Q2 2026.", "Operating income was $2.2 million in Q2 2026."]):
        first.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8)).text_frame.text = line
    second = prs.slides.add_slide(prs.slide_layouts[5])
    second.shapes.title.text = "Costs and people"
    for i, line in enumerate(["Cost of goods sold was $8.2 million in Q2 2026.", "Headcount reached 431 in Q2 2026.", "Gross margin was 42% in Q2 2026."]):
        second.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8)).text_frame.text = line
    prs.save(str(root / "board.pptx"))
    doc = Document()
    doc.add_heading("Q2 2026 report", level=1)
    doc.add_paragraph("Net revenue for Q2 2026 was $14.0 million and operating income was $2.2 million.")
    doc.add_paragraph("Headcount at the end of Q2 2026 was 431.")
    doc.save(str(root / "report.docx"))
    svc = Service(state)
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    # a new workbook: revenue up, income a thousand times too large (a unit slip), the cost row gone
    workbook(15_000_000, 2_210_000_000, 0.42, 438, None)
    inbox = svc.changes_inbox(pid)
    return inbox, {"project": pid}


class Handler(http.server.BaseHTTPRequestHandler):
    inbox_json = b"{}"

    def do_GET(self) -> None:  # noqa: N802
        routes = {"/": (PAGE.encode(), "text/html; charset=utf-8"), "/sdk.js": (SDK.encode(), "text/javascript"), "/inbox.json": (self.inbox_json, "application/json"),
                  "/plugin-test.js": ((PLUGIN.read_text(encoding="utf-8") + "\nexport { ChangeViews, layoutMap }\n").encode(), "text/javascript")}
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        hit = routes.get(self.path.split("#")[0])
        body, ctype = hit if hit else (b"not found", "text/plain")
        self.send_response(200 if hit else 404)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:
        pass


def start(inbox: dict):
    Handler.inbox_json = json.dumps(inbox).encode()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="map_"))
    inbox, _ = build_project(tmp / "proj", tmp / "state")
    server, url = start(inbox)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = None
        for ch in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=ch)
                break
            except Exception:  # noqa: BLE001
                continue
        assert browser, "no Chromium-based browser"
        for name, w, hgt, hash_ in (("light_wide", 1100, 760, ""), ("dark_wide", 1100, 760, "#dark"), ("light_narrow", 420, 820, "")):
            page = browser.new_page(viewport={"width": w, "height": hgt})
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url + hash_)
            page.wait_for_function("window.__ready === true", timeout=60000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out / f"map_{name}.png"), full_page=True)
            print(name, "console errors:", errors)
            page.close()
    server.shutdown()
    print(json.dumps(inbox["map"]["totals"]))


if __name__ == "__main__":
    main()
