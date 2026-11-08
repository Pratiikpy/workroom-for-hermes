"""Contract C3 as a gate: hostile scene content is only ever text, the frame never navigates or makes a request, and the server refuses fuzzed edits."""
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

HOSTILE = [
    "</text><script>window.__pwn=1</script>",
    "<img src=x onerror=\"window.__pwn=2\">",
    "<svg onload=\"window.__pwn=3\"></svg>",
    "javascript:window.__pwn=4",
    "<a href=\"https://evil.example/steal\">click</a>",
    "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example/\">",
    "\"><script>parent.location='https://evil.example/'</script>",
    "&lt;b&gt; &amp; &#x3C;script&#x3E; ${7*7} {{7*7}} %00 ‮",
    "<style>*{display:none}</style>",
    "<form action=\"https://evil.example/\"><input name=a></form>",
]


def _browser(p):
    for ch in ("msedge", "chrome"):
        try:
            return p.chromium.launch(channel=ch)
        except Exception:  # noqa: BLE001
            continue
    return None


@pytest.fixture()
def harness():
    import canvas_harness

    server, url = canvas_harness.start()
    yield canvas_harness, url
    server.shutdown()


def test_t_cnv_1_and_2_hostile_text_in_every_field_stays_text_and_nothing_leaves_the_frame(harness) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    ch, url = harness
    ops = []
    for i, text in enumerate(HOSTILE):
        ops.append({"op": "add", "node": {"id": f"h{i}", "type": "text", "x": 20, "y": 20 + i * 40, "w": 600, "h": 30, "text": text, "size": 18}})
    ch.svc.scene_apply(ch.pid, ch.REL, 0, ops)
    with sync_api.sync_playwright() as p:
        browser = _browser(p)
        if browser is None:
            pytest.skip("no Chromium-based browser available")
        page = browser.new_page()
        requests, navigations = [], []
        page.on("request", lambda r: requests.append(r.url))
        page.on("framenavigated", lambda f: navigations.append(f.url[:30]))
        page.goto(url + "/")
        page.wait_for_timeout(1500)
        frame = next(f for f in page.frames if f.url.endswith("/frame"))
        shown = frame.evaluate("() => Array.from(document.querySelectorAll('#nodes text')).map(e => e.textContent)")
        for text in HOSTILE:
            assert text in shown, f"not drawn as plain text: {text!r}"
        assert frame.evaluate("() => window.__pwn === undefined") is True
        assert page.evaluate("() => window.__pwn === undefined") is True, "the host page must not see anything the frame was fed"
        assert frame.evaluate("() => document.querySelectorAll('#nodes script, #nodes img, #nodes a, #nodes form, #nodes style, #nodes meta, #nodes foreignObject').length") == 0
        # interact with every hostile node: select all, nudge, edit text of one
        frame.focus("#svg")
        page.keyboard.press("Control+a")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert frame.url.endswith("/frame") and not [u for u in navigations if "evil" in u]
        outside = [u for u in requests if not u.startswith(url) and not u.startswith("data:")]
        assert outside == [], f"requests left the harness: {outside}"
        assert not any("evil.example" in u for u in requests)
        origins = {m["origin"] for m in json.loads(page.evaluate("async () => JSON.stringify(await (await fetch('/log')).json())")) if "origin" in m}
        assert origins <= {"null"}
        browser.close()


def test_t_cnv_3_fuzzed_patches_are_refused_without_changing_the_draft(harness) -> None:
    ch, _ = harness
    from workroom.workroom_core.service import ServiceError

    rng = random.Random(11)
    before = ch.svc.scene_open(ch.pid, ch.REL)
    junk_values = [None, -1, 10**12, float("nan"), "x" * 5000, [], {}, True, "<script>", {"a": 1}, 1e309]
    for _ in range(400):
        op = rng.choice([
            {"op": rng.choice(["add", "update", "delete", "reorder", "drop", 5, None])},
            {"op": "update", "id": rng.choice(["title", "kpi", "nope", 5, None]), "set": {rng.choice(["x", "w", "fill", "text", "id", "type", "onclick", "size"]): rng.choice(junk_values)}},
            {"op": "add", "node": {"id": rng.choice(["a b", "ok", "title", 5]), "type": rng.choice(["rect", "script", None]), "x": rng.choice(junk_values), "y": 0, "w": 1, "h": 1}},
            {"op": "reorder", "id": "title", "index": rng.choice(junk_values)},
            "not an object", 5, None,
        ])
        try:
            res = ch.svc.scene_apply(ch.pid, ch.REL, before["rev"], [op])
        except ServiceError:
            continue
        # an op that happened to be valid advances the draft; keep following it so the next fuzz round uses the live revision
        before = {"scene": res["scene"], "rev": res["rev"]}
    # the draft is always a valid scene, whatever was thrown at it
    from workroom.workroom_core.scene.model import validate_scene

    assert validate_scene(ch.svc.scene_open(ch.pid, ch.REL)["scene"]) == []
    with pytest.raises(ServiceError):
        ch.svc.scene_apply(ch.pid, ch.REL, 10**9, [])
    with pytest.raises(ServiceError):
        ch.svc.scene_apply(ch.pid, ch.REL, before["rev"], "not a list")
