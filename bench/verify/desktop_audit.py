"""Walk every screen of the Workroom tab in the real Hermes Desktop and save a full-page screenshot of each state, for a visual audit.

    python desktop_audit.py [cdp url]
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
OUT = flow.SHOTS / "audit"


def shot(pg, name: str, full: bool = True) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("shot", name, flush=True)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_audit_"))
    map_harness.write_files(root)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        pg.wait_for_timeout(6000)
        for _ in range(4):
            flow.open_workroom(pg)
            pg.wait_for_timeout(2500)
            if pg.get_by_label("Folder path").count():
                break
        shot(pg, "01_home")
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        shot(pg, "02_project_added")
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        pg.wait_for_timeout(800)
        shot(pg, "03_links_found")
        map_harness.write_files(root, changed=True)
        pg.get_by_role("button", name="Check the sources").click()
        pg.wait_for_selector("[aria-label^='Change map']", timeout=60000)
        pg.wait_for_timeout(1500)
        shot(pg, "04b_first_view_after_check", full=False)
        shot(pg, "04_changes_map")
        pg.get_by_role("tab", name="List").click()
        pg.wait_for_timeout(400)
        shot(pg, "05_changes_list")
        pg.get_by_role("button", name="Prepare release").click()
        pg.wait_for_selector("[aria-label='Release']", timeout=60000)
        pg.wait_for_timeout(1000)
        shot(pg, "06_release")
        pg.set_viewport_size({"width": 640, "height": 900})
        pg.wait_for_timeout(800)
        shot(pg, "07_narrow")
        print("page errors:", errors)
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
