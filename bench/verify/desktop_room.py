"""In the real Hermes Desktop: the Room panel (add a source, decide a proposed memory) and the 'Files the agent changed' panel (restore).

    python desktop_room.py [cdp url]            default http://127.0.0.1:9222

Builds a throwaway project, adds it through the page, then makes the agent-side calls through the same service the tools use (a proposed memory, a snapshot) and
reads the panels back from the DOM. Screenshots go to bench/ui_shots/.
"""

import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))
import desktop_flow as flow  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
SHOTS = HERE.parent / "ui_shots"
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="wr_room_"))
    (root / "notes.txt").write_text("keep me")
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        pg.wait_for_timeout(6000)
        try:
            flow.open_workroom(pg)
        except AssertionError:
            pg.get_by_text("WORKROOM", exact=False).first.click()
            pg.wait_for_timeout(2500)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("complementary", name="Project room").get_by_role("tab", name="Room", exact=True).click()
        pg.wait_for_timeout(800)
        check("the Room panel is shown for the project", pg.get_by_role("region", name="Room", exact=True).count() > 0)
        pg.get_by_label("Source reference").fill("Board meets on the 12th")
        pg.get_by_label("Source label").fill("Board date")
        pg.get_by_role("button", name="Add", exact=True).click()
        pg.wait_for_selector("text=Board date", timeout=10000)
        check("a source added in the panel is listed with who added it", "added by owner" in pg.get_by_role("region", name="Room", exact=True).inner_text())
        # the agent side: the same service the tools call
        data = Path.home() / "AppData" / "Roaming"  # not used: the service below talks to the plugin's own data folder
        svc_dir = None
        for cand in (Path(__file__).resolve().parents[3] / ".hermes-test" / "plugin-data" / "workroom",):
            if cand.exists():
                svc_dir = cand
        check("the plugin data folder is found", svc_dir is not None)
        svc = Service(svc_dir)
        pid = next(x["project"] for x in svc.projects() if Path(x["folder"]).resolve() == root.resolve())
        svc.room_propose_memory(pid, "Show negatives in brackets", "preference", "the owner said so in chat")
        svc.snapshot_take(pid, str(root / "notes.txt"), "write_file")
        (root / "notes.txt").write_text("changed by the agent")
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_timeout(1500)
        pg.reload()
        pg.wait_for_timeout(6000)
        try:
            flow.open_workroom(pg)
        except AssertionError:
            pg.get_by_text("WORKROOM", exact=False).first.click()
            pg.wait_for_timeout(2500)
        pg.locator("select").first.select_option(label=str(root))
        pg.get_by_role("complementary", name="Project room").get_by_role("tab", name="Room", exact=True).click()
        pg.wait_for_timeout(800)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SHOTS / "room_panel.png"))
        room_text = pg.get_by_role("region", name="Room", exact=True).inner_text() if pg.get_by_role("region", name="Room", exact=True).count() else ""
        check("a memory the agent proposed waits for the owner", "Show negatives in brackets" in room_text and "Remember this" in room_text)
        pg.get_by_role("button", name="Remember this").first.click()
        pg.wait_for_selector("text=Remembered (1)", timeout=10000)
        check("approving moves it under Remembered", True)
        pg.get_by_role("complementary", name="Project room").get_by_role("tab", name="Made", exact=True).click()
        pg.wait_for_timeout(1500)
        changes = pg.get_by_role("region", name="Files the agent changed", exact=True)
        check("the changed file is listed with a Restore button", changes.count() > 0 and "notes.txt" in changes.inner_text())
        changes.get_by_role("button", name="Restore").first.click()
        pg.wait_for_selector("text=restored", timeout=10000)
        check("restoring puts the old content back on disk", (root / "notes.txt").read_text() == "keep me")
        pg.screenshot(path=str(SHOTS / "room_after.png"))
        check("no page or console errors", not errors)
        if errors:
            print(errors[:5])
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
