"""In the real Hermes Desktop: the 'Needs you' inbox and the Deliverables panel (open, see an earlier version, compare, approve).

    python desktop_deliverables.py [cdp url]            default http://127.0.0.1:9222
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
DATA = Path("C:/Users/prate/nous/.hermes-test/plugin-data/workroom")
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name, flush=True)


def ready(pg) -> None:
    pg.wait_for_timeout(4000)
    try:
        pg.wait_for_selector("text=Backend ready", timeout=90000)
    except Exception:
        pass
    pg.wait_for_timeout(3000)


def open_page(pg, root: Path) -> None:
    pg.reload()
    ready(pg)
    try:
        flow.open_workroom(pg)
    except AssertionError:
        pg.get_by_text("WORKROOM", exact=False).first.click()
        pg.wait_for_timeout(2500)
    pg.locator("select").first.select_option(label=str(root))
    pg.wait_for_timeout(2500)


def main() -> None:
    SHOTS.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="wr_deliv_"))
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        pg.reload()
        ready(pg)
        try:
            flow.open_workroom(pg)
        except AssertionError:
            pg.get_by_text("WORKROOM", exact=False).first.click()
            pg.wait_for_timeout(2500)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        svc = Service(DATA)
        pid = next(x["project"] for x in svc.projects() if Path(x["folder"]).resolve() == root.resolve())
        brief = root / "brief.md"
        brief.write_text("# Brief\nRevenue rose.\n")
        svc.snapshot_take(pid, str(brief), "write_file")
        brief.write_text("# Brief\nRevenue rose 20%.\nCosts fell.\n")
        open_page(pg, root)
        needs = pg.get_by_role("region", name="Needs you", exact=True)
        try:
            needs.get_by_text("brief.md", exact=False).first.wait_for(timeout=20000)
        except Exception:
            pass
        check("the Needs-you inbox shows the deliverable to review", needs.count() > 0 and "brief.md" in needs.inner_text())
        panel = pg.get_by_role("region", name="Deliverables", exact=True)
        try:
            panel.get_by_text("not reviewed").first.wait_for(timeout=20000)
        except Exception:
            pass
        check("the Deliverables panel lists brief.md as not reviewed", panel.count() > 0 and "not reviewed" in panel.inner_text())
        panel.get_by_role("button", name="Open").first.click()
        pg.wait_for_selector("text=Costs fell.", timeout=10000)
        check("opening shows the file as it is now", True)
        panel.get_by_role("button", name="Compare with now").first.click()
        pg.wait_for_selector("text=2 lines added, 1 removed", timeout=10000)
        check("compare shows lines added and removed", True)
        pg.screenshot(path=str(SHOTS / "deliverables_compare.png"))
        panel.get_by_role("button", name="Approve this version").first.click()
        try:
            pg.wait_for_selector("text=brief.md approved.", timeout=30000)
            pg.wait_for_timeout(1500)
        except Exception:
            pass
        check("approving marks it approved", "· approved" in panel.inner_text() or "· approved" in panel.inner_text())
        check("the inbox no longer lists it", "brief.md" not in pg.get_by_role("region", name="Needs you", exact=True).inner_text())
        pg.screenshot(path=str(SHOTS / "deliverables_approved.png"))
        check("no page or console errors", not errors)
        if errors:
            print(errors[:5])
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
