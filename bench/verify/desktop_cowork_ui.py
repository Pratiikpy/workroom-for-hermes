"""Real Hermes Desktop check of the newest panels: linked figures underlined in a drawn deck, helper agents in the Room, a failed scheduled check in Needs-you.

Needs the test Desktop running (study-clones/run-desktop.sh) and the project 'Deliv test' prepared with a tied deck.pptx, a recorded helper and a failed receipt.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).resolve().parent.parent / "ui_shots"
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


with sync_playwright() as p:
    pg = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0].pages[0]
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
    pg.get_by_role("button", name="Workroom:", exact=False).first.wait_for(timeout=240000)
    pg.keyboard.press("Escape")
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(1000)
    pg.keyboard.type("Deliv test")
    pg.wait_for_timeout(1500)
    pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(6000)
    # Needs you: the failed scheduled check
    pg.get_by_role("tab", name="Needs you").first.click()
    pg.wait_for_timeout(2500)
    body = pg.locator("body").inner_text()
    check("a failed scheduled check is listed in Needs you with its reason", "scheduled check failed" in body and "source workbook could not be opened" in body)
    pg.screenshot(path=str(SHOTS / "cowork_needs_you.png"))
    # Made: the deck drawn with its linked figure underlined
    pg.get_by_role("tab", name="Made").first.click()
    pg.wait_for_timeout(2500)
    deliv = pg.get_by_role("region", name="Deliverables", exact=True).first
    row = deliv.locator("div", has_text="deck.pptx").filter(has=pg.get_by_role("button", name="Open")).last
    row.get_by_role("button", name="Open").first.click()
    pg.wait_for_timeout(4000)
    img = pg.get_by_role("img", name="Slide 1")
    loaded = img.count() > 0 and img.first.evaluate("e => e.complete && e.naturalWidth > 0")
    check("the deck is drawn as an image", bool(loaded))
    src = img.first.get_attribute("src") if img.count() else ""
    from urllib.parse import unquote

    svg = unquote(src.split(",", 1)[1]) if "," in src else ""
    check("the linked figure is underlined in the drawing", 'text-decoration="underline">120<' in svg)
    check("the pane says how many figures are marked", "underlined in green" in pg.locator("body").inner_text())
    pg.screenshot(path=str(SHOTS / "cowork_marked_deck.png"))
    # Room: helper agents
    pg.locator("[role=tablist]").filter(has_text="Needs you").get_by_role("tab", name="Room", exact=True).first.click()
    pg.wait_for_timeout(2500)
    room = pg.locator("body").inner_text()
    check("the helper agent is listed in the Room with its goal, outcome and files", "Helper agents" in room and "researcher" in room and "summarise it" in room and "deck.pptx" in room)
    pg.screenshot(path=str(SHOTS / "cowork_room_crew.png"))
    check("no page errors", not errors)
    print(f"{sum(ok for _, ok in results)}/{len(results)} passed", errors[:3])
