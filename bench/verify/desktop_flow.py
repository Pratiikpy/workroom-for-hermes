"""Drive the real Hermes Desktop (Electron, over its debug port) through the meaning-layer flow and check the files afterwards.

    python desktop_flow.py [cdp url]            default http://127.0.0.1:9222

Needs a running Hermes Desktop with the Workroom desktop half switched on. Builds a throwaway project, then, as a person would:
add it, find links, find calculated numbers and accept them, change a source so a comparison turns false, read the flagged sentence,
prepare the release, find the approve button locked until the sentence is acknowledged, approve, then roll forward and restore.
Every claim about the files is checked with python-pptx afterwards. Screenshots go to bench/ui_shots/.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

SHOTS = Path(__file__).resolve().parents[1] / "ui_shots"
CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail and not ok else ""))


def sources(root: Path, q3: float, q4: float | None = None) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"] + (["Q4 2026"] if q4 is not None else []))
        ws.write_row(1, 0, ["Net revenue", 13_000_000, 14_000_000, q3] + ([q4] if q4 is not None else []))
        ws.write_row(2, 0, ["Operating income", 1_850_000, 2_210_000, 2_640_000] + ([2_900_000] if q4 is not None else []))


def deck(root: Path) -> None:
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = "Q3 2026 Board Update"
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Quarterly results"
    for i, line in enumerate(["Net revenue reached $15.1 million in Q3 2026, up 7.9% from $14.0 million in Q2 2026.", "Operating income was $2.6 million in Q3 2026."]):
        slide.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8)).text_frame.text = line
    slide.notes_slide.notes_text_frame.text = "Say: net revenue hit $15.1 million, our best quarter."
    prs.save(str(root / "board.pptx"))


def texts(root: Path) -> list[str]:
    return [sh.text_frame.text for s in Presentation(root / "board.pptx").slides for sh in s.shapes if sh.has_text_frame]


def open_workroom(pg) -> None:
    """Bring the Workroom page to the front once the Desktop has loaded it (the tab appears a few seconds after a reload and its label may be shortened)."""
    find = "() => { const e = Array.from(document.querySelectorAll('div,button,span')).find(x => x.children.length === 0 && /^WORKRO/i.test(x.innerText || '') && x.getBoundingClientRect().y < 40 && x.getBoundingClientRect().width > 0); if (!e) return null; const r = e.getBoundingClientRect(); return [r.x + 10, r.y + r.height / 2]; }"
    for _ in range(40):
        if pg.get_by_label("Folder path").count():
            pg.wait_for_timeout(1500)
            return
        box = pg.evaluate(find)
        if box:
            pg.mouse.click(box[0], box[1])
        pg.wait_for_timeout(1000)
    raise AssertionError("the Workroom tab did not appear in the Desktop")


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_depth_"))
    sources(root, 15_100_000)
    deck(root)
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        pg.wait_for_timeout(6000)
        open_workroom(pg)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        check("links found", "linked" in pg.inner_text("body"))
        pg.get_by_role("button", name="Find calculated numbers").click()
        pg.wait_for_selector('[aria-label="Calculated numbers"]', timeout=20000)
        body = pg.inner_text("body")
        check("the percentage is offered as a calculation with its formula", "(Net revenue" in body and "= 7.857" in body, body[-400:])
        pg.screenshot(path=str(SHOTS / "depth_01_calculation.png"), full_page=True)
        pg.get_by_role("button", name="Accept", exact=True).first.click()
        pg.wait_for_selector("text=will now follow its sources", timeout=20000)
        sources(root, 13_000_000)
        pg.get_by_role("button", name="Check the sources").click()
        pg.wait_for_selector("text=to read before you approve", timeout=30000)
        body = pg.inner_text("body")
        check("the sentence the update makes false is shown with its evidence", "was true and is not true after this update" in body or "no longer fit" in body or "turned" in body, body[-600:])
        pg.screenshot(path=str(SHOTS / "depth_02_flagged.png"), full_page=True)
        pg.get_by_role("button", name="Prepare release").click()
        pg.wait_for_selector("text=Approve the release", timeout=30000)
        approve = pg.get_by_role("button", name="Approve and publish")
        locked = approve.is_disabled()
        check("approve is locked until the flagged sentence is acknowledged", locked)
        pg.screenshot(path=str(SHOTS / "depth_03_release_locked.png"), full_page=True)
        before = (root / "board.pptx").read_bytes()
        pg.get_by_label("I have read the flagged sentences").check()
        check("acknowledging unlocks approve", not approve.is_disabled())
        check("nothing was written before approval", (root / "board.pptx").read_bytes() == before)
        approve.click()
        pg.wait_for_selector("text=Published", timeout=30000)
        after = texts(root)
        check("the figures were updated", any("$13.0 million" in t for t in after), str(after))
        check("the calculated percent was held, not rewritten", any("up 7.9%" in t for t in after), str(after))
        pg.screenshot(path=str(SHOTS / "depth_04_published.png"), full_page=True)
        # roll forward: the next period arrives in the workbook
        sources(root, 13_000_000, 16_400_000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        pg.get_by_role("button", name="See what changes").click()
        pg.get_by_text("Moving to the next period?").click()
        pg.get_by_role("button", name="Roll forward one period").click()
        pg.wait_for_selector("text=roll your documents forward", timeout=30000)
        pg.screenshot(path=str(SHOTS / "depth_05_roll.png"), full_page=True)
        body = pg.inner_text("body")
        check("the roll is described in plain words", "period words advance" in body and "Restore undoes the whole roll" in body, body[-500:])
        boxes = pg.get_by_label("I have read the flagged sentences")
        if boxes.count():
            boxes.check()
        pg.get_by_role("button", name="Approve and publish").click()
        pg.wait_for_selector("text=Published", timeout=30000)
        rolled = texts(root)
        check("the title and the figures moved to Q4 2026", "Q4 2026 Board Update" in rolled and any("Q4 2026" in t and "$16.4 million" in t for t in rolled), str(rolled))
        check("the calculated percent was rolled with the rest and reads correctly", "Net revenue reached $16.4 million in Q4 2026, up 26.2% from $13.0 million in Q3 2026." in rolled, str(rolled))
        pg.screenshot(path=str(SHOTS / "depth_06_rolled.png"), full_page=True)
        check("no script error in the renderer", not errors, "; ".join(errors[:3]))
    failed = [r for r in results if not r[1]]
    print(json.dumps({"passed": len(results) - len(failed), "failed": len(failed)}))
    shutil.rmtree(root, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
