"""Capture the meaning-layer screens of the real Hermes Desktop in both themes and at desktop and narrow widths, and check for overflow.

    python desktop_visual.py [cdp url]

Leaves a project with a prepared release that holds three flagged sentences, then takes four screenshots (light and dark, wide and
narrow) of the release step and checks each for horizontal overflow and for text with too little contrast against its background.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desktop_flow as flow  # noqa: E402

CDP = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9222"
SHOTS = flow.SHOTS

CONTRAST_JS = """() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1
  const cx = cv.getContext('2d', { willReadFrequently: true })
  const norm = (css) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255] }
  const lum = (c) => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }); return 0.2126 * r + 0.7152 * g + 0.0722 * b }
  const bg = (el) => { while (el) { const c = norm(getComputedStyle(el).backgroundColor); if (c[3] > 0.5) return c.slice(0, 3); el = el.parentElement } return [255, 255, 255] }
  const bad = []
  const region = document.querySelector('[aria-label="Release"]')
  if (!region) return { checked: 0, bad: ['no release region'] }
  let n = 0
  for (const el of region.querySelectorAll('*')) {
    if (![...el.childNodes].some(x => x.nodeType === 3 && x.textContent.trim())) continue
    const cs = getComputedStyle(el), fg = norm(cs.color)
    const L1 = lum(fg.slice(0, 3)), L2 = lum(bg(el)), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)
    n++
    if (ratio < 3.0) bad.push([el.textContent.trim().slice(0, 40), ratio.toFixed(2)])
  }
  return { checked: n, bad: bad.slice(0, 6) }
}"""


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_visual_"))
    flow.sources(root, 15_100_000)
    flow.deck(root)
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        pg = browser.contexts[0].pages[0]
        pg.reload()
        pg.wait_for_timeout(6000)
        flow.open_workroom(pg)
        pg.get_by_label("Folder path").fill(str(root))
        pg.get_by_role("button", name="Add project").click()
        pg.wait_for_selector("text=Project added", timeout=20000)
        pg.get_by_role("button", name="Find links").click()
        pg.wait_for_selector("text=numbers found", timeout=30000)
        pg.get_by_role("button", name="Find calculated numbers").click()
        pg.wait_for_selector('[aria-label="Calculated numbers"]', timeout=20000)
        pg.get_by_role("button", name="Accept", exact=True).first.click()
        pg.wait_for_selector("text=will now follow its sources", timeout=20000)
        flow.sources(root, 13_000_000)
        pg.get_by_role("button", name="Check the sources").click()
        pg.wait_for_selector("text=to read before you approve", timeout=30000)
        pg.get_by_role("button", name="Prepare release").click()
        pg.wait_for_selector("text=Approve the release", timeout=30000)
        session = browser.contexts[0].new_cdp_session(pg)
        for theme in ("light", "dark"):
            pg.evaluate("(t) => { document.documentElement.classList.toggle('dark', t === 'dark'); document.documentElement.style.colorScheme = t }", theme)
            pg.emulate_media(color_scheme=theme)
            for width in ("wide", "narrow"):
                session.send("Emulation.setDeviceMetricsOverride", {"width": 1500 if width == "wide" else 560, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
                pg.wait_for_timeout(1500)
                pg.locator('[aria-label="Release"]').scroll_into_view_if_needed()
                shot = SHOTS / f"depth_visual_{theme}_{width}.png"
                pg.screenshot(path=str(shot))
                overflow = pg.evaluate("() => { const e = document.querySelector('[aria-label=\"Release\"]'); return [e.scrollWidth, e.clientWidth, document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth] }")
                contrast = pg.evaluate(CONTRAST_JS)
                out[f"{theme}_{width}"] = {"release_scroll_vs_client": overflow[:2], "page_scroll_vs_client": overflow[2:], "contrast": contrast}
                print(theme, width, json.dumps(out[f"{theme}_{width}"]))
        session.send("Emulation.clearDeviceMetricsOverride")
        pg.emulate_media(color_scheme="light")
        pg.evaluate("() => { document.documentElement.classList.remove('dark') }")
    shutil.rmtree(root, ignore_errors=True)
    bad = [k for k, v in out.items() if v["release_scroll_vs_client"][0] > v["release_scroll_vs_client"][1] + 1 or v["contrast"]["bad"]]
    print(json.dumps({"variants": len(out), "with_a_problem": bad}))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
