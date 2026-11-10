"""In the real Hermes Desktop: a text deliverable written with recorded evidence shows its proof badge, marked figures and an evidence card.

    python desktop_proof.py "<hermes project name>" <project folder>
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from workroom.adapters.proof_hooks import make_proof_hooks  # noqa: E402
from workroom.workroom_core.figure_proof import EvidenceStore  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

NAME, FOLDER = sys.argv[1], Path(sys.argv[2])
DATA = Path("C:/Users/prate/nous/.hermes-test/plugin-data/workroom")
SHOTS = HERE.parent / "ui_shots"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


svc = Service(DATA)
pid = next(x["project"] for x in svc.projects() if Path(x["folder"]).resolve() == FOLDER.resolve())
capture, _o, written, _v, _r = make_proof_hooks(lambda: EvidenceStore(DATA / "evidence.db"))
capture(tool_name="web_extract", args={"url": "https://example.org/q3-results"}, result='{"content": "Revenue for the quarter was $4,210 million, up from $3,980 million a year earlier."}', session_id="desk-proof")
memo = FOLDER / "memo.md"
svc.snapshot_take(pid, str(memo), "write_file")
memo.write_text("# Q3 memo\nRevenue for the quarter was $4,210 million, up from $3,980 million a year earlier.\nThe market will grow 37.5% a year.\n")
line = written(tool_name="write_file", args={"path": str(memo)}, result="{}", session_id="desk-proof")
check("the agent's write result carries the proof line", bool(line) and "37.5%" in line)

with sync_playwright() as p:
    pg = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0].pages[0]
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    if "--reload" in sys.argv:
        pg.reload()
    pg.get_by_role("button", name="Workroom:", exact=False).first.wait_for(timeout=180000)
    pg.wait_for_timeout(3000)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(1200)
    pg.keyboard.type(NAME)
    pg.wait_for_timeout(1500)
    pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(6000)
    pg.get_by_role("tab", name="Made").first.click()
    pg.wait_for_timeout(3000)
    body = pg.locator("body").inner_text()
    check("the deliverable shows its badge", "of 3 figures supported" in body)
    deliv = pg.get_by_role("region", name="Deliverables", exact=True).first
    row = deliv.locator("div", has_text="memo.md").filter(has=pg.get_by_role("button", name="Open")).last
    row.get_by_role("button", name="Open").first.click()
    pg.wait_for_timeout(3000)
    mark = pg.get_by_role("button", name="37.5%: not verified")
    try:
        mark.first.wait_for(timeout=30000)
    except Exception:
        pass
    check("the unsourced figure is marked in the text", mark.count() > 0)
    if mark.count():
        mark.first.click()
        pg.wait_for_timeout(1000)
        check("clicking it says nothing read contains it", "Not verified: nothing the agent read in that session supports this figure." in pg.locator("body").inner_text())
    src = pg.get_by_role("button", name="$4,210 million", exact=False)
    if src.count():
        src.first.click()
        pg.wait_for_timeout(1000)
        check("a sourced figure names where it came from", "https://example.org/q3-results" in pg.locator("body").inner_text())
    pg.screenshot(path=str(SHOTS / "proof_marks.png"))
    check("no page errors", not errors)
failed = [n for n, ok in checks if not ok]
print(f"{len(checks) - len(failed)}/{len(checks)} passed")
