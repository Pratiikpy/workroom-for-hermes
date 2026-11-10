import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
SHOTS = Path(__file__).resolve().parent.parent / "ui_shots"
with sync_playwright() as p:
    pg = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0].pages[0]
    pg.get_by_role("button", name="Workroom:", exact=False).first.wait_for(timeout=180000)
    pg.keyboard.press("Escape"); pg.keyboard.press("Control+k"); pg.wait_for_timeout(1000)
    pg.keyboard.type("Deliv test"); pg.wait_for_timeout(1500); pg.keyboard.press("Control+Enter"); pg.wait_for_timeout(6000)
    pg.get_by_role("tab", name="Made").first.click(); pg.wait_for_timeout(3000)
    deliv = pg.get_by_role("region", name="Deliverables", exact=True).first
    row = deliv.locator("div", has_text="board.pptx").filter(has=pg.get_by_role("button", name="Open")).last
    row.get_by_role("button", name="Open").first.click(); pg.wait_for_timeout(4000)
    img = pg.get_by_role("img", name="Slide 1")
    ok = img.count() > 0 and img.first.evaluate("e => e.complete && e.naturalWidth > 0")
    print(("PASS" if ok else "FAIL"), "the deck is drawn as an image with no Office program")
    pg.screenshot(path=str(SHOTS / "structural_deck.png"))
