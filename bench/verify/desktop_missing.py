"""In the real Hermes Desktop: a document that goes missing for a moment keeps its links, the page says so, and the links resume when it is back.

    python desktop_missing.py [cdp url]
"""

import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_flow as flow  # noqa: E402

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_missing_"))
    flow.sources(root, 15_100_000)
    flow.deck(root)
    deck = next(p for p in root.iterdir() if p.suffix == ".pptx")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        pg.reload()
        pg.wait_for_timeout(6000)
        flow.open_workroom(pg)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        linked = pg.locator("text=/\\d+ linked/").first.inner_text()
        away = deck.with_suffix(".away")
        deck.rename(away)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=missing from the folder", timeout=30000)
        text = pg.locator("text=missing from the folder").first.inner_text()
        check("the page names the missing document and says its links are kept", deck.name in text and "kept" in text)
        check("the links are still counted", pg.locator("text=/\\d+ linked/").first.inner_text() == linked)
        pg.screenshot(path=str(flow.SHOTS / "depth_missing_document.png"))
        away.rename(deck)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_timeout(4000)
        check("the notice is gone when the document is back", pg.locator("text=missing from the folder").count() == 0)
        check("the links are the same as before", pg.locator("text=/\\d+ linked/").first.inner_text() == linked)
    shutil.rmtree(root, ignore_errors=True)
    failed = [n for n, ok in checks if not ok]
    print({"passed": len(checks) - len(failed), "failed": len(failed)})
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
