"""In the real Hermes Desktop: the Changes inbox draws the change map from a project the Desktop itself registered, and it can be used.

    python desktop_map.py [cdp url]

Needs the Desktop running with its debugging port (see the notes in SESSION_STATE.md). The project is added through the page, the workbook changes underneath it,
and the map is read back from the page's own DOM: nodes, lines, a selection, the finding on a place and the keyboard.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import desktop_flow as flow  # noqa: E402
import map_harness  # noqa: E402

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_map_"))
    map_harness.write_files(root)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.reload()
        pg.wait_for_timeout(6000)
        flow.open_workroom(pg)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        map_harness.write_files(root, changed=True)
        pg.get_by_role("button", name="Check the sources").click()
        pg.wait_for_selector("[aria-label^='Change map']", timeout=60000)
        pg.wait_for_timeout(1200)
        nodes = pg.locator("svg g[role=button]").count()
        lines = pg.locator("svg[aria-label^='Change map'] path").count()
        check("the Map and List tabs are there and Map is shown first", pg.get_by_role("tab", name="Map").get_attribute("aria-selected") == "true")
        check("the map holds 4 source boxes and 7 places", nodes == 11)
        check("it holds 7 lines, one per link", lines == 7)
        text = pg.locator("svg[aria-label^='Change map']").text_content()
        check("it names the missing source cell and the places in both documents", "Source cell is gone" in text and "board.pptx" in text and "report.docx" in text)
        pg.screenshot(path=str(flow.SHOTS / "desktop_map_01_overview.png"))
        pg.locator("svg g[role=button][aria-label^='Source Operating income']").click()
        panel = pg.get_by_role("region", name="Selected link").inner_text()
        check("selecting a source lists the places it reaches", "board.pptx, Slide 1" in panel and "report.docx" in panel)
        pg.screenshot(path=str(flow.SHOTS / "desktop_map_02_source.png"))
        pg.locator("svg g[role=button][aria-label*='needs your check']").first.click()
        panel = pg.get_by_role("region", name="Selected link").inner_text()
        check("selecting a flagged place shows the finding", "factor of" in panel and "Show this file in its folder" in panel)
        pg.screenshot(path=str(flow.SHOTS / "desktop_map_03_finding.png"))
        pg.keyboard.press("Escape")
        pg.locator("svg g[role=button]").first.focus()
        pg.keyboard.press("Enter")
        check("the keyboard selects a box", pg.locator("svg g[role=button][aria-pressed=true]").count() == 1)
        pg.get_by_role("tab", name="List").click()
        pg.wait_for_timeout(300)
        check("the list shows the same places as text", pg.locator("text=/board.pptx, Slide 1/").count() >= 1 and pg.locator("svg[aria-label^='Change map']").count() == 0)
        pg.get_by_role("tab", name="Map").click()
        check("no page errors", errors == [])
    shutil.rmtree(root, ignore_errors=True)
    failed = [n for n, ok in checks if not ok]
    print({"passed": len(checks) - len(failed), "failed": len(failed)})
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
