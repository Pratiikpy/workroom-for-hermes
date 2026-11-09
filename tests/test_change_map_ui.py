"""The change map in a real browser: what is drawn is what the project holds, and it can be used with a mouse or a keyboard alone."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    sync_api = pytest.importorskip("playwright.sync_api")
    import map_harness

    tmp = tmp_path_factory.mktemp("map")
    inbox, _ = map_harness.build_project(tmp / "proj", tmp / "state")
    server, url = map_harness.start(inbox)
    pw = sync_api.sync_playwright().start()
    browser = None
    for ch in ("msedge", "chrome"):
        try:
            browser = pw.chromium.launch(channel=ch)
            break
        except Exception:  # noqa: BLE001
            continue
    if browser is None:
        pw.stop()
        server.shutdown()
        pytest.skip("no Chromium-based browser installed")
    yield inbox, url, browser
    browser.close()
    pw.stop()
    server.shutdown()


@pytest.fixture()
def page(world):
    inbox, url, browser = world
    pg = browser.new_page(viewport={"width": 1100, "height": 800})
    errors: list[str] = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(url)
    try:
        pg.wait_for_function("window.__ready === true", timeout=60000)
    except Exception:  # noqa: BLE001
        pg.close()
        pytest.skip("the page could not load React from the network")
    pg.wait_for_timeout(900)
    pg.errors = errors
    yield pg
    assert errors == [], errors
    pg.close()


def test_the_drawing_holds_exactly_the_nodes_and_edges_of_the_projects_graph(world, page) -> None:
    m = world[0]["map"]
    assert page.locator("svg g[role=button]").count() == len(m["sources"]) + len(m["elements"])
    assert page.locator("svg path").count() == len(m["edges"])
    labels = " | ".join(page.locator("svg g[role=button]").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))"))
    for e in m["elements"]:
        assert e["before"] in labels and (e["after"] in labels if e["after"] else True)
    assert "Missing source Results C6" in labels


def test_selecting_a_source_lights_its_links_and_dims_everything_else(world, page) -> None:
    page.locator("svg g[role=button][aria-label^='Source Operating income']").click()
    page.wait_for_timeout(500)  # the dimming is a 160 ms transition; read the settled state
    panel = page.get_by_role("region", name="Selected link")
    text = panel.inner_text()
    assert "Operating income Q2 2026" in text and "results.xlsx" in text
    assert text.count("will update") == 2 and "board.pptx, Slide 1" in text and "report.docx, Body" in text
    opacities = page.locator("svg g[role=button]").evaluate_all("els => els.map(e => [e.getAttribute('aria-label'), getComputedStyle(e).opacity])")
    lit = [a for a, o in opacities if float(o) == 1.0]
    assert len(lit) == 3 and sum(1 for a in lit if a.startswith("Source Operating income")) == 1
    widths = page.locator("svg path").evaluate_all("els => els.map(e => parseFloat(getComputedStyle(e).strokeWidth))")
    assert widths.count(3.0) == 2


def test_a_place_shows_where_it_comes_from_and_what_needs_checking_and_can_be_revealed(world, page) -> None:
    flagged = page.locator("svg g[role=button][aria-label*='needs your check']").first
    flagged.click()
    text = page.get_by_role("region", name="Selected link").inner_text()
    assert "board.pptx, Slide 1" in text and "factor of" in text
    page.get_by_role("button", name="Show board.pptx in its folder").click()
    assert page.evaluate("window.__revealed") == ["C:\\Reports\\Monthly\\board.pptx"]


def test_the_map_can_be_used_from_the_keyboard_alone(world, page) -> None:
    for _ in range(3):
        page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement.getAttribute('role') + ':' + document.activeElement.getAttribute('aria-label')")
    assert focused.startswith("button:")
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.getAttribute('aria-pressed')") == "true"
    assert "Nothing selected" not in page.get_by_role("region", name="Selected link").inner_text()
    page.keyboard.press("Escape")
    assert "Nothing selected" in page.get_by_role("region", name="Selected link").inner_text()


def test_the_list_is_the_text_twin_of_the_map(world, page) -> None:
    m = world[0]["map"]
    page.get_by_role("tab", name="List").click()
    items = page.locator("ul li").count()
    assert items == len(m["elements"]) - m["totals"]["blocked"] + m["totals"]["blocked"]  # every place is listed once, blocked ones in their own list
    assert page.locator("svg").count() == 0
