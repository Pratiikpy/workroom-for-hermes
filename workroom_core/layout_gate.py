"""Layout gate: code, not a model, checks a deck before anyone sees it.

For every slide of a .pptx: text that does not fit its box (measured with the real font file when the machine has it, otherwise an average glyph width,
which the finding says), text smaller than readable, shapes that run off the slide, text boxes that overlap, text whose colour is too close to what is
behind it (WCAG contrast), tables taller than the room left on the slide, and empty titles. Findings are "block" (a release would show a visible fault) or
"warn". The gate never changes the file.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EMU_PER_PT = 12700
MIN_BLOCK_PT = 9
MIN_WARN_PT = 12
DEFAULT_PT = 18
LINE_FACTOR = 1.2
CONTRAST_TEXT = 4.5
CONTRAST_LARGE = 3.0
LARGE_PT = 18
OVERLAP_SHARE = 0.1
AVG_GLYPH_EM = 0.52
FIT_SLACK = 1.04  # measuring is an estimate; 4% grace before calling text overflowing
FONT_DIRS = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path("/usr/share/fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]


@dataclass
class Finding:
    slide: int
    shape: str
    kind: str  # overflow | small_text | off_slide | overlap | contrast | table_height | empty_title
    severity: str  # block | warn
    message: str


_font_cache: dict[tuple[str, bool, int], Any] = {}


def _font(name: str, bold: bool, size_pt: float):
    """A Pillow font for measuring, when the font file is on this machine; None otherwise."""
    key = (name.lower(), bold, int(round(size_pt * 4)))
    if key in _font_cache:
        return _font_cache[key]
    found = None
    try:
        from PIL import ImageFont

        stem = name.lower().replace(" ", "")
        wanted = [stem + ("b" if bold else ""), stem + ("bd" if bold else ""), stem + ("-bold" if bold else ""), stem]
        for d in FONT_DIRS:
            if not d.is_dir():
                continue
            for w in wanted:
                for ext in (".ttf", ".otf"):
                    hits = list(d.rglob(w + ext)) if d.name != "Fonts" else [d / (w + ext)]
                    for f in hits:
                        if f.is_file():
                            found = ImageFont.truetype(str(f), max(1, int(round(size_pt * 4))))  # measured at 4x then divided, for sub-point precision
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
    except Exception:  # noqa: BLE001  measuring falls back to an average glyph width
        found = None
    _font_cache[key] = found
    return found


def text_width_pt(text: str, name: str, bold: bool, size_pt: float) -> tuple[float, bool]:
    f = _font(name, bold, size_pt)
    if f is not None:
        try:
            return f.getlength(text) / 4.0, True
        except Exception:  # noqa: BLE001
            pass
    return len(text) * size_pt * (AVG_GLYPH_EM + (0.04 if bold else 0)), False


def _lines(text: str, width_pt: float, name: str, bold: bool, size_pt: float) -> tuple[int, bool]:
    """Lines a paragraph takes when wrapped at word boundaries in a box of this width."""
    measured = True
    lines = 0
    for part in text.split("\n"):
        words = part.split(" ")
        current = ""
        n = 1
        for w in words:
            trial = (current + " " + w).strip()
            wpt, m = text_width_pt(trial, name, bold, size_pt)
            measured = measured and m
            if wpt <= width_pt or not current:
                current = trial
                if text_width_pt(current, name, bold, size_pt)[0] > width_pt:  # one word wider than the box breaks across lines
                    n += int(text_width_pt(current, name, bold, size_pt)[0] // max(1.0, width_pt))
            else:
                n += 1
                current = w
        lines += n
    return lines, measured


def _rel_luminance(hex6: str) -> float:
    def ch(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_rel_luminance(a), _rel_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _solid(fill) -> str | None:
    try:
        if fill.type == 1:  # MSO_FILL.SOLID
            return str(fill.fore_color.rgb)
    except Exception:  # noqa: BLE001  theme colours and gradients are not resolved here
        return None
    return None


_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _theme_color(master, name: str) -> str | None:
    for rel in master.part.rels.values():
        if rel.reltype.endswith("/theme"):
            from lxml import etree

            root = etree.fromstring(rel.target_part.blob)
            slot = root.find(f".//{_A}clrScheme/{_A}{name}")
            if slot is None or len(slot) == 0:
                return None
            kid = slot[0]
            val = kid.get("val") if kid.tag == f"{_A}srgbClr" else kid.get("lastClr")
            return val if val and len(val) == 6 else None
    return None


def _background_of(element, master) -> tuple[bool, str | None]:
    """(has a background of its own, its colour or None when it is a gradient, picture, style reference or a modified theme colour)."""
    bg = element.find(f".//{_P}bg")
    if bg is None:
        return False, None
    ref = bg.find(f"{_P}bgRef")
    if ref is not None and ref.get("idx") == "1001" and len(ref) == 1:  # the theme's first background style is a plain fill of the colour named inside
        solid = ref
    else:
        solid = bg.find(f"{_P}bgPr/{_A}solidFill")
    if solid is None or len(solid) == 0:
        return True, None
    kid = solid[0]
    if len(kid):  # shade, tint, luminance changes: not resolved here
        return True, None
    if kid.tag == f"{_A}srgbClr":
        return True, kid.get("val")
    if kid.tag == f"{_A}schemeClr":
        alias = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}.get(kid.get("val") or "", kid.get("val") or "")
        return True, _theme_color(master, alias)
    return True, None


def effective_background(slide) -> str | None:
    """The colour behind a slide's text: the slide's own background, else its layout's, else its master's. White when none sets one; None when the
    one that applies is a gradient, a picture or a modified theme colour (contrast cannot be judged there, so the gate does not guess)."""
    master = slide.slide_layout.slide_master
    for el in (slide._element, slide.slide_layout._element, master._element):
        has, colour = _background_of(el, master)
        if has:
            return colour
    return "FFFFFF"


def check_pptx(data: bytes) -> list[Finding]:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    sw, sh = prs.slide_width, prs.slide_height
    out: list[Finding] = []
    for si, slide in enumerate(prs.slides, 1):
        try:
            bg = effective_background(slide)
        except Exception:  # noqa: BLE001  a background that cannot be read is not guessed at
            bg = None
        unjudged: list[tuple[int, int, int, int]] = []  # shapes filled with a gradient, picture or pattern: text over them has no known colour behind it
        boxes = []
        fills: list[tuple[tuple[int, int, int, int], str]] = []
        for shp in slide.shapes:
            if shp.left is None or shp.width is None:
                continue
            box = (shp.left, shp.top, shp.left + shp.width, shp.top + shp.height)
            name = shp.name or f"shape {shp.shape_id}"
            if box[0] < 0 or box[1] < 0 or box[2] > sw * 1.001 or box[3] > sh * 1.001:
                out.append(Finding(si, name, "off_slide", "block", f"{name} runs off the slide"))
            f = _solid(shp.fill) if hasattr(shp, "fill") else None
            if f:
                fills.append((box, f))
            else:
                try:
                    if hasattr(shp, "fill") and shp.fill.type in (2, 3, 6):
                        unjudged.append(box)
                except Exception:  # noqa: BLE001
                    pass
            if getattr(shp, "has_table", False) and shp.has_table:
                rows = len(shp.table.rows)
                needed = sum(r.height for r in shp.table.rows) if all(r.height for r in shp.table.rows) else rows * 0.4 * 914400
                if shp.top + needed > sh:
                    out.append(Finding(si, name, "table_height", "block", f"{name} ({rows} rows) runs below the slide; split it or move it to its own slide"))
            if not getattr(shp, "has_text_frame", False) or not shp.has_text_frame:
                continue
            tf = shp.text_frame
            text_all = tf.text.strip()
            is_title = shp.is_placeholder and getattr(shp.placeholder_format, "type", None) in (1, 3)
            if is_title and not text_all:
                out.append(Finding(si, name, "empty_title", "warn", f"{name} is an empty title"))
            if not text_all:
                continue
            body = tf._txBody.find(f"{_A}bodyPr")
            if getattr(shp, "rotation", 0) or (body is not None and body.get("vert") not in (None, "horz")):
                continue  # rotated or vertical text runs along a different axis; its box says nothing about whether it fits
            boxes.append((box, name))
            inset_w = (tf.margin_left or 91440) + (tf.margin_right or 91440)
            inset_h = (tf.margin_top or 45720) + (tf.margin_bottom or 45720)
            width_pt = max(1.0, (shp.width - inset_w) / EMU_PER_PT)
            height_pt = max(1.0, (shp.height - inset_h) / EMU_PER_PT)
            need = 0.0
            measured_all = True
            for para in tf.paragraphs:
                runs = [r for r in para.runs if r.text]
                if not runs:
                    continue
                size = max((r.font.size.pt if r.font.size else DEFAULT_PT) for r in runs)
                bold = any(bool(r.font.bold) for r in runs)
                fname = next((r.font.name for r in runs if r.font.name), None) or "Calibri"
                for r in runs:
                    rs = r.font.size.pt if r.font.size else DEFAULT_PT
                    if rs < MIN_BLOCK_PT:
                        out.append(Finding(si, name, "small_text", "block", f"'{r.text[:30]}' in {name} is {rs:g} pt, too small to read"))
                    elif rs < MIN_WARN_PT and rs < size:
                        pass
                    elif rs < MIN_WARN_PT:
                        out.append(Finding(si, name, "small_text", "warn", f"'{r.text[:30]}' in {name} is {rs:g} pt"))
                    color = None
                    try:
                        color = str(r.font.color.rgb) if r.font.color and r.font.color.type is not None else None
                    except Exception:  # noqa: BLE001
                        color = None
                    if color:
                        covered = lambda fb: fb[0] <= box[0] and fb[1] <= box[1] and fb[2] >= box[2] and fb[3] >= box[3]  # noqa: E731
                        behind = next((fc for fb, fc in reversed(fills) if covered(fb)), None) or bg
                        if behind is None or any(covered(ub) for ub in unjudged):
                            continue
                        need_ratio = CONTRAST_LARGE if rs >= LARGE_PT or (r.font.bold and rs >= 14) else CONTRAST_TEXT
                        ratio = contrast(color, behind)
                        if ratio < need_ratio:
                            out.append(Finding(si, name, "contrast", "block", f"'{r.text[:30]}' in {name}: contrast {ratio:.1f}:1 against #{behind}, needs {need_ratio:g}:1"))
                text = "".join(r.text for r in runs)
                if tf.word_wrap is False:
                    w, m = text_width_pt(text, fname, bold, size)
                    measured_all = measured_all and m
                    if w > width_pt * FIT_SLACK:
                        out.append(Finding(si, name, "overflow", "block", f"'{text[:40]}' is wider than {name} and does not wrap"))
                    lines = 1
                else:
                    lines, m = _lines(text, width_pt, fname, bold, size)
                    measured_all = measured_all and m
                space = (para.space_after.pt if para.space_after is not None else 0)
                need += lines * size * LINE_FACTOR + space
            autofit = tf.auto_size
            how = "measured with the font" if measured_all else "estimated (font file not on this machine)"
            used_bottom = shp.top + int((min(need, height_pt) + inset_h / EMU_PER_PT) * EMU_PER_PT)
            boxes[-1] = ((box[0], box[1], box[2], used_bottom), name)  # overlap is judged on where the text is, not on the empty part of its box
            if need > height_pt * FIT_SLACK:
                if autofit == 1:  # "resize shape to fit text": PowerPoint grows the box downwards, so the question is where it ends
                    grown_bottom = shp.top + int((need + inset_h / EMU_PER_PT) * EMU_PER_PT)
                    boxes[-1] = ((box[0], box[1], box[2], grown_bottom), name)
                    if grown_bottom > sh * 1.001:
                        out.append(Finding(si, name, "overflow", "block", f"{name} grows to fit its text and then runs below the slide ({how})"))
                else:
                    out.append(Finding(si, name, "overflow", "block", f"the text of {name} needs about {need:.0f} pt of height and has {height_pt:.0f} pt ({how})"))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (a, an), (b, bn) = boxes[i], boxes[j]
                ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
                iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
                smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
                if ix * iy / smaller > OVERLAP_SHARE:
                    out.append(Finding(si, f"{an} / {bn}", "overlap", "warn", f"{an} and {bn} overlap"))
    return out


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]


def as_dicts(findings: list[Finding]) -> list[dict[str, Any]]:
    return [asdict(f) for f in findings]


_ = math  # kept for callers that compute line counts with ceil
