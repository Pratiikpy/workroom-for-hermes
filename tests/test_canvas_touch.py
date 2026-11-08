"""Touch input on the page editor: a finger can select and drag an item, using real touch events from the browser's input layer."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))


def test_a_finger_drag_moves_an_item_and_a_tap_selects_what_is_under_it(tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    import canvas_harness as ch

    server, url = ch.start()
    try:
        with sync_api.sync_playwright() as p:
            browser = None
            for name in ("msedge", "chrome"):
                try:
                    browser = p.chromium.launch(channel=name)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if browser is None:
                pytest.skip("no Chromium-based browser available")
            ctx = browser.new_context(viewport={"width": 420, "height": 800}, has_touch=True, is_mobile=True)
            page = ctx.new_page()
            page.goto(url + "/")
            page.wait_for_timeout(1500)
            frame = next(f for f in page.frames if f.url.endswith("/frame"))
            box = frame.locator("#svg").bounding_box()
            scene = ch.svc.scene_open(ch.pid, ch.REL)["scene"]
            title = next(n for n in scene["nodes"] if n["id"] == "title")
            k = box["width"] / scene["canvas"]["w"]
            start = (box["x"] + (title["x"] + 40) * k, box["y"] + (title["y"] + 20) * k)
            cdp = ctx.new_cdp_session(page)

            def touch(kind, x, y):
                points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
                cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

            touch("touchStart", *start)
            for i in range(1, 9):
                touch("touchMove", start[0] + i * 6, start[1] + i * 3)
            touch("touchEnd", 0, 0)
            page.wait_for_timeout(800)
            moved = next(n for n in ch.svc.scene_open(ch.pid, ch.REL)["scene"]["nodes"] if n["id"] == "title")
            assert moved["x"] > title["x"] + 20 and moved["y"] > title["y"] + 8, (title["x"], moved["x"])
            assert frame.evaluate("() => document.getElementById('handles') !== null"), "the dragged item stays selected"
            empty = (box["x"] + 5, box["y"] + box["height"] - 5)
            touch("touchStart", *empty)
            touch("touchEnd", 0, 0)
            page.wait_for_timeout(300)
            width = frame.evaluate("() => Number(document.querySelector('#over rect').getAttribute('width'))")
            assert width == scene["canvas"]["w"], "a tap on the page background selects the background item, not the title"
            # the controls are big enough to hit with a finger
            heights = frame.evaluate("() => Array.from(document.querySelectorAll('#bar button')).map(b => b.getBoundingClientRect().height)")
            assert min(heights) >= 44, 'toolbar buttons are at least 44 px tall on a touch screen'
            browser.close()
    finally:
        server.shutdown()
