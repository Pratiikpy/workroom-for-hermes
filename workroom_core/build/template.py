"""Read the look of a deck the user already has (colours and fonts from its theme) so a new deck is made in that look.

Only data comes out: three six-digit colours and a font name, held to the same readability limits as brand.json (accent 3:1, ink 7:1, muted 4.5:1 on white).
A colour the template uses that is too pale is replaced by the nearest readable shade of itself and the substitution is reported, so the look stays
recognisable and the deck stays readable. The template file is read, never changed, and nothing from it is executed.
"""

from __future__ import annotations

import io
import re
import zipfile

from lxml import etree

from .brand import MIN_CONTRAST, _font_name, contrast_on_white

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
MAX_THEME_BYTES = 512 * 1024
_FALLBACK = {"accent": "2563EB", "ink": "1F2937", "muted": "6B7280"}


def _darken(hex6: str, slot: str) -> str:
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))
    for _ in range(40):
        if contrast_on_white(f"{r:02X}{g:02X}{b:02X}") >= MIN_CONTRAST[slot]:
            break
        r, g, b = int(r * 0.92), int(g * 0.92), int(b * 0.92)
    return f"{r:02X}{g:02X}{b:02X}"


def _color(node) -> str | None:
    if node is None:
        return None
    srgb = node.find(f"{{{A}}}srgbClr")
    if srgb is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", srgb.get("val") or ""):
        return srgb.get("val").upper()
    sysc = node.find(f"{{{A}}}sysClr")
    if sysc is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", sysc.get("lastClr") or ""):
        return sysc.get("lastClr").upper()
    return None


def read_theme(data: bytes) -> tuple[dict[str, str], list[str]]:
    """(tokens, notes) for a .pptx or .docx: accent, ink, muted, font. Empty tokens with a note when nothing usable is there."""
    notes: list[str] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = sorted(n for n in z.namelist() if re.fullmatch(r"(?:ppt|word)/theme/theme\d*\.xml", n))
        if not names:
            return {}, ["the template has no theme to read"]
        info = z.getinfo(names[0])
        if info.file_size > MAX_THEME_BYTES:
            return {}, ["the template's theme is larger than the limit"]
        root = etree.fromstring(z.read(names[0]), etree.XMLParser(resolve_entities=False, no_network=True))
    except (zipfile.BadZipFile, etree.XMLSyntaxError, KeyError, OSError):
        return {}, ["the template could not be read as an Office file"]
    scheme = root.find(f".//{{{A}}}clrScheme")
    tokens: dict[str, str] = {}
    if scheme is not None:
        pick = {t: _color(scheme.find(f"{{{A}}}{t}")) for t in ("dk1", "dk2", "accent1", "accent2", "lt2")}
        accent = pick["accent1"] or _FALLBACK["accent"]
        ink = pick["dk1"] or _FALLBACK["ink"]
        muted = pick["dk2"] or pick["accent2"] or _FALLBACK["muted"]
        for slot, value in (("accent", accent), ("ink", ink), ("muted", muted)):
            good = value if contrast_on_white(value) >= MIN_CONTRAST[slot] else _darken(value, slot)
            if good != value:
                notes.append(f"the template's {slot} colour #{value} is too pale to read on white; used #{good}")
            tokens[slot] = good
    fonts = root.find(f".//{{{A}}}fontScheme")
    if fonts is not None:
        latin = fonts.find(f"{{{A}}}minorFont/{{{A}}}latin")
        name = _font_name(latin.get("typeface") or "") if latin is not None else None
        if name:
            tokens["font"] = name
    if not tokens:
        notes.append("the template's theme holds no colours or fonts Workroom can use")
    return tokens, notes
