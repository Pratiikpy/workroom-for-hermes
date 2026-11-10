"""In the real Hermes Desktop: the Workroom status-bar item, the pane beside the chat, and its tabs.

    python desktop_shell.py [cdp url]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
SHOTS = Path(__file__).resolve().parent.parent / "ui_shots"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(CDP).contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        pg.wait_for_timeout(9000)
        try:
            pg.wait_for_selector("text=Backend ready", timeout=60000)
        except Exception:
            pass
        status = pg.get_by_role("button", name="Workroom:", exact=False)
        check("the status bar shows the Workroom item", status.count() > 0)
        if status.count():
            print("status text:", status.first.inner_text())
            status.first.click()
            pg.wait_for_timeout(2500)
        pane_text = pg.locator("body").inner_text()
        check("the pane beside the chat opens", "Workroom project" in pane_text or "Needs you" in pane_text)
        pg.screenshot(path=str(SHOTS / "shell_pane.png"))
        check("no page or console errors", not errors)
        if errors:
            print(errors[:6])
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
