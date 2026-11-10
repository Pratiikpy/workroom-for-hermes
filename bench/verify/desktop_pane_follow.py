"""In the real Hermes Desktop: start a chat inside a Hermes project whose folder is a Workroom project and check that the pane beside the chat follows it.

    python desktop_pane_follow.py "<hermes project name>" "<folder name>"
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

NAME, FOLDER = sys.argv[1], sys.argv[2]
SHOTS = Path(__file__).resolve().parent.parent / "ui_shots"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


with sync_playwright() as p:
    pg = p.chromium.connect_over_cdp("http://127.0.0.1:9222").contexts[0].pages[0]
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(1200)
    pg.keyboard.type(NAME)
    pg.wait_for_timeout(1500)
    pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(6000)
    body = pg.locator("body").inner_text()
    check("the pane names the project folder of the chat", FOLDER in body and "This chat is not in a Workroom project" not in body)
    check("the pane shows its tabs", all(t in body for t in ("Needs you", "Made", "Room", "Rules")))
    pg.screenshot(path=str(SHOTS / "shell_pane_project.png"))
    made = pg.get_by_role("tab", name="Made")
    if made.count():
        made.first.click()
        pg.wait_for_timeout(2500)
        check("the Made tab lists the deliverable", "brief.md" in pg.locator("body").inner_text())
        pg.screenshot(path=str(SHOTS / "shell_pane_made.png"))
    check("no page errors", not errors)
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
