"""Read colour and font tokens from a project's DESIGN.md. Only validated tokens come out: six-digit hex colours and a plain font name.

Three shapes are understood: `key: value` lines or front matter, the "Quick Color Reference" lists that design-system files use
(`- Primary CTA: "Rausch (#ff385c)"`), and the first bullet under a Font Family heading. Colours must be readable on a white slide
(accent 3:1, ink 7:1, muted 4.5:1); a token that is not is dropped rather than guessed around.
"""

from __future__ import annotations

import re

MAX_CHARS = 64 * 1024
HEX_ANY = re.compile(r"#([0-9A-Fa-f]{6})\b")
HEX_ONLY = re.compile(r"^#?([0-9A-Fa-f]{6})$")
FONT = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]{0,39}$")
GENERIC_FONTS = {"system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "sans-serif", "serif", "monospace", "blinkmacsystemfont", "-apple-system", "inherit"}
LINE = re.compile(r"^[\s>*\-+]*([A-Za-z][A-Za-z \-/]{1,34}?)\s*(?:\*+\s*)?[:=]\s*(?:\*+\s*)?(\S(?:.*\S)?)\s*$")
LINE_MAX = 400
KEYS = {
    "accent": ("accent", "primary", "brand", "primary color", "primary colour", "brand color", "brand colour", "accent color", "accent colour", "primary cta", "cta", "primary button"),
    "ink": ("ink", "text", "foreground", "text color", "text colour", "body text", "primary text", "heading / body text", "heading text", "heading", "body"),
    "muted": ("muted", "muted text", "secondary text", "muted color", "muted colour", "caption", "tertiary text", "subtle text"),
    "font": ("font", "font family", "font-family", "typeface", "typography", "body font"),
}
LOOKUP = {name: slot for slot, names in KEYS.items() for name in names}
ROLE_WORDS = {"display", "headlines", "headline", "heading", "headings", "body", "editorial", "code", "technical", "ui", "system", "icons", "mono", "monospace",
              "primary", "secondary", "text", "sans", "serif", "labels", "label", "emoji", "brand", "marketing", "product", "data", "numeric"}
MIN_CONTRAST ={"accent": 3.0, "ink": 7.0, "muted": 4.5}


def _lum(h: str) -> float:
    def c(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)


def contrast_on_white(h: str) -> float:
    return 1.05 / (_lum(h) + 0.05)


def _good_color(slot: str, h: str) -> bool:
    return contrast_on_white(h) >= MIN_CONTRAST[slot]


def _font_name(value: str) -> str | None:
    """The first family in a font list or bullet, if it is a real name and not a generic keyword, a size or a weight."""
    m = re.search(r"\*\*([^*]+)\*\*", value) or re.search(r"`([^`]+)`", value)
    first = (m.group(1) if m else value).split(",")[0].strip().strip("'\"` *")
    low = first.lower()
    if not FONT.match(first) or low in GENERIC_FONTS or re.search(r"emoji|icon|mono|code|symbol", low) or re.search(r"(?<!\d)\d{1,6}\s{0,4}px|weight|\bpt\b|\brem\b", low) or len(first) < 2:
        return None
    return first


def parse_design_md(text: str) -> dict[str, str]:
    """The first valid value for each of accent, ink, muted and font. Anything else in the file (prose, links, other tokens) is ignored."""
    if not isinstance(text, str) or not text or len(text) > MAX_CHARS:
        return {}
    out: dict[str, str] = {}
    section = ""
    for raw in text.splitlines():
        if raw.startswith("#"):
            section = re.sub(r"^#+\s*(\d+\.\s*)?", "", raw).strip().lower()
            continue
        if "font" not in out and ("font family" in section or section.startswith("typography")) and raw.lstrip().startswith(("-", "*")):
            bold = re.search(r"\*\*([^*]+)\*\*", raw)
            is_role = bool(bold) and set(re.findall(r"[a-z]+", bold.group(1).lower())) <= ROLE_WORDS
            body = raw.split(":", 1)[1] if is_role and ":" in raw else raw
            name = _font_name(body.lstrip(" -"))
            if name:
                out["font"] = name
                continue
        m = LINE.match(raw) if len(raw) <= LINE_MAX else None
        if not m:
            continue
        label, value = m.group(1).strip().lower(), m.group(2).strip()
        slot = LOOKUP.get(label)
        if slot is None and "font family" in section and re.match(r"^[\s\-*]+", raw):
            slot, value = "font", raw  # a bullet under a Font Family heading: `- **Name** ...` or `- Label: `Name``
            if ":" in raw and "`" in raw.split(":", 1)[1]:
                value = raw.split(":", 1)[1]
        if slot is None or slot in out:
            continue
        if slot == "font":
            name = _font_name(value.strip().strip("'\"` "))
            if name:
                out["font"] = name
            continue
        h = HEX_ONLY.match(value.strip("'\"` ")) or HEX_ANY.search(value)
        if h and _good_color(slot, h.group(1)):
            out[slot] = h.group(1).upper()
    return out
