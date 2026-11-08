"""Parse numbers as a reader sees them: with currency, percent, scale words and brackets, keeping displayed precision."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SCALE_WORDS = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9, "t": 1e12, "trillion": 1e12,
}
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"}

_NUMBER = re.compile(
    r"""
    (?P<neg_open>\()?
    (?P<sign>[-−–]\s?)?
    (?P<cur>[$€£¥₹])?\s?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    \s?(?P<scale>(?:thousand|millions?|billions?|trillion|bn|mm|mn|k|m|b|t)\b)?
    \s?(?P<pct>%|pp\b|bps\b|bp\b)?
    (?P<neg_close>\))?
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberMention:
    raw: str
    value: float          # the number as displayed (before applying the scale word)
    scaled: float         # value multiplied by its scale word
    decimals: int         # digits after the decimal point as written
    unit: str             # "percent", "bps", "pp", "currency:USD", or "plain"
    scale: float          # 1.0 when no scale word
    negative: bool
    start: int
    end: int


def parse_numbers(text: str) -> list[NumberMention]:
    """All numeric mentions in ``text``. Years such as 2024 are returned like any number; callers decide."""
    out: list[NumberMention] = []
    for m in _NUMBER.finditer(text):
        raw_num = m.group("num")
        # a bare number glued to letters (A1, Q2, FY25) is a label, not a quantity
        before = text[m.start("num") - 1] if m.start("num") > 0 else " "
        if before.isalpha() and not m.group("cur"):
            continue
        decimals = len(raw_num.split(".")[1]) if "." in raw_num else 0
        value = float(raw_num.replace(",", ""))
        negative = bool(m.group("sign")) or (bool(m.group("neg_open")) and bool(m.group("neg_close")))
        scale_word = (m.group("scale") or "").lower()
        scale = _SCALE_WORDS.get(scale_word, 1.0)
        pct = (m.group("pct") or "").lower()
        if pct == "%":
            unit = "percent"
        elif pct in ("bp", "bps"):
            unit = "bps"
        elif pct == "pp":
            unit = "pp"
        elif m.group("cur"):
            unit = "currency:" + _CURRENCY[m.group("cur")]
        else:
            unit = "plain"
        sign = -1.0 if negative else 1.0
        whole = m.group(0)
        start = m.start() + (len(whole) - len(whole.lstrip()))
        end = m.end() - (len(whole) - len(whole.rstrip()))
        out.append(NumberMention(whole.strip(), sign * value, sign * value * scale, decimals, unit, scale, negative, start, end))
    return out


def consistent_with_source(mention: NumberMention, source_value: float) -> tuple[bool, str]:
    """Can ``source_value`` plausibly be what the mention displays? Returns (ok, transform name).

    Equal numbers are not enough on their own; this only answers whether the digits are compatible once scale,
    percent-versus-fraction and displayed rounding are allowed for.
    """
    tol = 0.5 * 10 ** (-mention.decimals)
    candidates: list[tuple[str, float]] = [("exact", source_value)]
    if mention.unit in ("percent", "pp"):
        candidates.append(("fraction_to_percent", source_value * 100.0))
    if mention.scale != 1.0:
        candidates.append(("scaled", source_value / mention.scale))
    for factor, name in ((1e3, "thousands"), (1e6, "millions"), (1e9, "billions")):
        candidates.append((name, source_value / factor))
    for name, v in candidates:
        shown = mention.value
        if abs(shown - round(v, mention.decimals)) <= tol * 1.0001 and abs(shown - v) <= tol * 1.0001 + 1e-12:
            return True, name
    return False, ""


_NUM_IN_RAW = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")
_TRANSFORMS = {
    "exact": lambda v, scale: v,
    "fraction_to_percent": lambda v, scale: v * 100.0,
    "scaled": lambda v, scale: v / scale,
    "thousands": lambda v, scale: v / 1e3,
    "millions": lambda v, scale: v / 1e6,
    "billions": lambda v, scale: v / 1e9,
}


def format_like(old: NumberMention, new_source_value: float, transform: str) -> str:
    """Write ``new_source_value`` the way ``old`` was written: same affixes, decimals, separators and sign style.

    ``transform`` is the one the matcher found when it linked the mention to its source (see consistent_with_source).
    """
    shown = _TRANSFORMS[transform](new_source_value, old.scale)
    rounded = round(abs(shown), old.decimals)
    use_commas = "," in old.raw
    body = f"{rounded:,.{old.decimals}f}" if use_commas else f"{rounded:.{old.decimals}f}"
    m = _NUM_IN_RAW.search(old.raw)
    prefix = old.raw[: m.start()].replace("(", "").replace("-", "").replace("−", "").replace("–", "")
    suffix = old.raw[m.end():].replace(")", "")
    if shown < 0 and rounded != 0:
        return f"({prefix}{body}{suffix})" if old.raw.lstrip().startswith("(") else f"-{prefix}{body}{suffix}"
    return f"{prefix}{body}{suffix}"
