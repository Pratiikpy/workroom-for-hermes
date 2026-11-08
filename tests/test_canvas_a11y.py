"""Keyboard and screen-reader pass of the page editor, in a real Chromium-based browser."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))


def _lum(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture()
def editor():
    sync_api = pytest.importorskip("playwright.sync_api")
    import canvas_harness

    server, url = canvas_harness.start()
    with sync_api.sync_playwright() as p:
        browser = None
        for ch in ("msedge", "chrome"):
            try:
                browser = p.chromium.launch(channel=ch)
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            server.shutdown()
            pytest.skip("no Chromium-based browser available")
        yield browser, url, canvas_harness
        browser.close()
    server.shutdown()


def _open(browser, url, scheme="light"):
    ctx = browser.new_context(viewport={"width": 1100, "height": 760}, color_scheme=scheme)
    page = ctx.new_page()
    page.goto(url + "/")
    page.wait_for_timeout(1500)
    frame = next(f for f in page.frames if f.url.endswith("/frame"))
    return ctx, page, frame


def test_every_control_has_an_accessible_name_and_the_canvas_is_announced(editor) -> None:
    browser, url, _ = editor
    ctx, page, frame = _open(browser, url)
    unnamed = frame.evaluate("""() => Array.from(document.querySelectorAll('button, input, textarea, svg[role]')).filter(e => !(e.getAttribute('aria-label') || e.textContent.trim() || e.getAttribute('title'))).map(e => e.outerHTML.slice(0, 80))""")
    assert unnamed == []
    assert frame.evaluate("() => document.getElementById('svg').getAttribute('role')") == "application"
    assert "Arrow keys" in frame.evaluate("() => document.getElementById('svg').getAttribute('aria-label')")
    assert frame.evaluate("() => document.getElementById('status').getAttribute('role')") == "status"
    assert frame.evaluate("() => document.documentElement.lang") == "en"
    assert frame.evaluate("() => document.getElementById('list').children.length") >= 2, "a text list of items exists for screen readers"
    ctx.close()


def test_the_whole_editor_works_from_the_keyboard(editor) -> None:
    browser, url, ch = editor
    ctx, page, frame = _open(browser, url)
    frame.focus("#svg")
    page.keyboard.press("Tab")
    first = frame.evaluate("() => document.getElementById('status').textContent")
    assert "rect" in first or "text" in first, "Tab selects an item and announces it"
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    assert "text" in frame.evaluate("() => document.getElementById('status').textContent")
    # the title text node: Enter edits, typing replaces, Ctrl+Enter commits
    scene = ch.svc.scene_open(ch.pid, ch.REL)["scene"]
    title_x = next(n for n in scene["nodes"] if n["id"] == "title")["x"]
    page.keyboard.press("Shift+Tab")
    sel = frame.evaluate("() => document.getElementById('status').textContent")
    assert "title" in sel
    page.keyboard.press("Enter")
    assert frame.is_visible("#edit")
    page.keyboard.type("Typed by keyboard")
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(600)
    assert next(n for n in ch.svc.scene_open(ch.pid, ch.REL)["scene"]["nodes"] if n["id"] == "title")["text"] == "Typed by keyboard"
    # arrows move, undo restores
    frame.focus("#svg")
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_timeout(500)
    moved = next(n for n in ch.svc.scene_open(ch.pid, ch.REL)["scene"]["nodes"] if n["id"] == "title")["x"]
    assert moved == title_x + 10
    page.keyboard.press("Control+z")
    page.wait_for_timeout(500)
    assert next(n for n in ch.svc.scene_open(ch.pid, ch.REL)["scene"]["nodes"] if n["id"] == "title")["x"] == title_x
    # every toolbar button is reachable with Tab and shows a visible focus ring
    page.keyboard.press("Escape")
    frame.focus("#bar button")
    seen = set()
    for _ in range(30):
        label = frame.evaluate("() => document.activeElement && document.activeElement.getAttribute('aria-label')")
        outline = frame.evaluate("() => getComputedStyle(document.activeElement).outlineStyle")
        if label:
            seen.add(label)
            assert outline != "none", f"no focus ring on {label}"
        page.keyboard.press("Tab")
    assert {"Select tool", "Draw a rectangle", "Fit the page to the window"} <= seen
    ctx.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_text_contrast_meets_wcag_aa_in_both_themes(editor, scheme) -> None:
    browser, url, _ = editor
    ctx, page, frame = _open(browser, url, scheme)
    pairs = frame.evaluate("""() => {
      const cs = (sel, prop) => getComputedStyle(document.querySelector(sel))[prop];
      const rgb = s => s.match(/[0-9.]+/g).slice(0, 3).map(Number);
      const pick = (fg, bg) => [rgb(fg), rgb(bg)];
      return {
        toolbar: pick(cs('#bar button', 'color'), cs('#bar button', 'backgroundColor')),
        status: pick(cs('#status', 'color'), cs('#side', 'backgroundColor')),
        input: pick(cs('#comment', 'color'), cs('#comment', 'backgroundColor')),
        primary: pick(cs('button.primary', 'color'), cs('button.primary', 'backgroundColor')),
      };
    }""")
    for name, (fg, bg) in pairs.items():
        assert _ratio(fg, bg) >= 4.5, f"{scheme} {name}: {_ratio(fg, bg):.2f}"
    ctx.close()
