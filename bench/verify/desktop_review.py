"""In the real Hermes Desktop: the review room draws a Word report with Office, marks the linked figures, and shows the page after the release.

    python desktop_review.py [cdp url]            default http://127.0.0.1:9222

Builds a throwaway project (a workbook and a Word report), adds it through the page, finds the links, changes the workbook underneath, opens the review
room and reads the page back from the DOM: the drawn page, the marks, the before and after pages, and the explanation behind a figure. Nothing is written
to the report by looking. Screenshots go to bench/ui_shots/.
"""

import io
import shutil
import sys
import tempfile
from pathlib import Path

from docx import Document
from playwright.sync_api import sync_playwright
from xlsxwriter import Workbook

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import desktop_flow as flow  # noqa: E402

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def files(root: Path, q2: float) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1", "Q2"])
        ws.write_row(1, 0, ["Revenue", 100, q2])
        ws.write_row(2, 0, ["Costs", 60, 90])
        ws.write_row(3, 0, ["Margin", 0.40, 0.25])
    if not (root / "report.docx").exists():
        d = Document()
        d.add_heading("Q2 results", level=1)
        d.add_paragraph("Revenue in Q2 was 120 and margin was 25%.")
        d.add_paragraph("Headcount reached 120 people.")
        t = d.add_table(rows=2, cols=3)
        for c, v in enumerate(["Metric", "Q1", "Q2"]):
            t.cell(0, c).text = v
        for c, v in enumerate(["Revenue", "100", "120"]):
            t.cell(1, c).text = v
        buf = io.BytesIO()
        d.save(buf)
        (root / "report.docx").write_bytes(buf.getvalue())


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_review_"))
    files(root, 120)
    before_bytes = None
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        pg.wait_for_timeout(6000)
        flow.open_workroom(pg)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        files(root, 150)
        before_bytes = (root / "report.docx").read_bytes()
        pg.get_by_role("button", name="Open the review room").click()
        pg.wait_for_selector("[aria-label='Review room'] img", timeout=120000)
        pg.wait_for_timeout(1500)
        room = pg.locator("[aria-label='Review room']")
        check("a drawn page is shown", room.locator("img").count() == 1)
        marks = room.locator("button[aria-label*='change']")
        check("the changes are marked on the page (after the release by default)", marks.count() >= 2)
        labels = [marks.nth(i).get_attribute("aria-label") for i in range(marks.count())]
        check("a mark names the new figure and the old one", any("150" in (x or "") and "120" in (x or "") for x in labels))
        room.screenshot(path=str(flow.SHOTS / "desktop_review_01_after.png"))
        pg.get_by_role("button", name="Now", exact=True).click()
        pg.wait_for_timeout(3000)
        labels_now = [b.get_attribute("aria-label") for b in room.locator("button[aria-label*='will change']").all()]
        check("the page as it is now marks the figures that will change", len(labels_now) >= 2)
        room.screenshot(path=str(flow.SHOTS / "desktop_review_02_now.png"))
        room.locator("button[aria-label*='will change']").first.click()
        pg.wait_for_selector("text=Source: results.xlsx", timeout=20000)
        panel = pg.get_by_role("region", name="Selected figure").inner_text()
        check("choosing a figure says where it came from", "Results" in panel and "C2" in panel)
        room.screenshot(path=str(flow.SHOTS / "desktop_review_03_why.png"))
        check("looking changed nothing in the report", (root / "report.docx").read_bytes() == before_bytes)
        pg.get_by_role("button", name="Check the sources").click()
        pg.wait_for_selector("text=Prepare release", timeout=60000)
        pg.get_by_role("button", name="Prepare release").click()
        pg.wait_for_selector("text=Approve the release", timeout=60000)
        pg.get_by_role("button", name="Approve and publish").click()
        pg.wait_for_selector("text=Published", timeout=60000)
        check("the report was rewritten only after approval", (root / "report.docx").read_bytes() != before_bytes)
        pg.get_by_role("button", name="Open the record of this release").first.click()
        pg.wait_for_selector("pre[aria-label='Release record']", timeout=20000)
        record = pg.locator("pre[aria-label='Release record']").inner_text()
        check("the record names the changes, the approver and the limits", "120 -> 150" in record and "desktop:local-session" in record and "does not prove" in record)
        pg.screenshot(path=str(flow.SHOTS / "desktop_review_04_record.png"))
        check("no page error or console error", not errors)
        if errors:
            print(errors[:5])
    shutil.rmtree(root, ignore_errors=True)
    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
