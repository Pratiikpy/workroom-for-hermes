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
    (?P<sign>[-–]|−\s?)?
    (?P<cur>[$€£¥₹])?\s?
    (?P<num>\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
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
    aside: bool = False   # a percentage in brackets inside a sentence, "283 skills (7.1%) leaking": an aside, not an accounting negative


_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY_AFTER_MONTH = re.compile(_MONTH + r"\.?\s+$", re.I)
_DAY_BEFORE_MONTH = re.compile(r"^\s+(?:of\s+)?" + _MONTH + chr(92) + "b", re.I)


def _part_of_longer_token(text: str, start: int, end: int) -> bool:
    """A clock time (1:50), a version or section number (2.1.3), a date (12/05/2026, January 30), or an ordinal (30th): one token, not a
    quantity, and it must not be edited piece by piece."""
    prev = text[start - 1] if start > 0 else ""
    prev2 = text[start - 2] if start > 1 else ""
    nxt = text[end] if end < len(text) else ""
    nxt2 = text[end + 1] if end + 1 < len(text) else ""
    if text[start] == "." and prev.isdigit():
        return True
    tail = text[end:end + 4]
    if nxt == "," and nxt2.isdigit() and not (len(tail) >= 4 and tail[2].isdigit() and tail[3].isdigit()):
        digits_after = len(tail) - 1 - len(tail[1:].lstrip("0123456789"))
        if digits_after in (1, 2) and not tail[1 + digits_after:2 + digits_after].isdigit():
            return True  # 189,45: a decimal comma, which Workroom does not read as a quantity
    if prev == "," and prev2.isdigit() and 1 <= len(text[start:end]) <= 2 and text[start:end].isdigit():
        return True
    if text[end:end + 2].lower() in ("st", "nd", "rd", "th") and not text[end + 2:end + 3].isalpha():
        return True  # an ordinal: 30th, 3rd
    digits = text[start:end]
    if digits.isdigit() and len(digits) <= 2 and 1 <= int(digits) <= 31 and (_DAY_AFTER_MONTH.search(text[max(0, start - 12):start]) or _DAY_BEFORE_MONTH.match(text[end:end + 16])):
        return True  # the day of a date: January 30, 30 January
    if prev in (":", "/") and prev2.isdigit():
        return True
    if nxt in (":", "/") and nxt2.isdigit():
        return True
    return nxt == "." and nxt2.isdigit()


_CALL = re.compile(r"[A-Za-z_][A-Za-z_0-9]*\([^()]*\)|\{[^{}]*\}|\[\d+(?:\s?[,–-]\s?\d+)*\]")


def parse_numbers(text: str) -> list[NumberMention]:
    """All numeric mentions in ``text``. Years such as 2024 are returned like any number; callers decide.

    Arguments of a call written like code (RGB(79,129,189), f(2, 3)), values in braces ({0,0,76}) and bracketed citation numbers ([12], [3, 4]) are not
    quantities and are skipped."""
    out: list[NumberMention] = []
    calls = [(c.start(), c.end()) for c in _CALL.finditer(text)]
    for m in _NUMBER.finditer(text):
        if calls and any(lo <= m.start("num") < hi for lo, hi in calls):
            continue
        raw_num = m.group("num")
        # a bare number glued to letters (A1, Q2, FY25) is a label, not a quantity
        before = text[m.start("num") - 1] if m.start("num") > 0 else " "
        if before.isalpha() and not m.group("cur"):
            continue
        if _part_of_longer_token(text, m.start("num"), m.end("num")):
            continue
        decimals = len(raw_num.split(".")[1]) if "." in raw_num else 0
        value = float(raw_num.replace(",", ""))
        balanced = bool(m.group("neg_open")) and bool(m.group("neg_close"))
        pct_unit = (m.group("pct") or "").lower() in ("%", "pp")
        before_text = text[: m.start("neg_open")].rstrip() if balanced else ""
        aside = balanced and pct_unit and bool(before_text) and (before_text[-1].isalnum() or before_text[-1] in "%)")
        if aside:
            balanced = False
        sign_at = m.start("sign")
        # a dash glued to the figure before it (10-15%, 2026-27) is a range, not a minus sign
        is_range = sign_at >= 1 and (text[sign_at - 1].isalnum() or text[sign_at - 1] in "%)")
        if m.group("sign") in ("-", "–") and not m.group("cur") and text[m.end("sign"):m.start("num")].strip() == "" and m.start("num") > m.end("sign"):
            is_range = True  # a dash then a space is punctuation ("Custom transition – 0.25 s"), not a minus sign
        negative = (bool(m.group("sign")) and not is_range) or balanced
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
        firsts = (m.start("cur"), m.start("num")) if is_range else (m.start("sign"), m.start("cur"), m.start("num"))
        lo = m.start("neg_open") if (balanced or aside) else min(i for i in firsts if i >= 0)
        hi = m.end("neg_close") if (balanced or aside) else max(m.end(g) for g in ("num", "scale", "pct") if m.group(g))
        whole = text[lo:hi]
        start = lo + (len(whole) - len(whole.lstrip()))
        end = hi - (len(whole) - len(whole.rstrip()))
        out.append(NumberMention(whole.strip(), sign * value, sign * value * scale, decimals, unit, scale, negative, start, end, aside))
    return out


def consistent_with_source(mention: NumberMention, source_value: float) -> tuple[bool, str]:
    """Can ``source_value`` plausibly be what the mention displays? Returns (ok, transform name).

    Equal numbers are not enough on their own; this only answers whether the digits are compatible once scale,
    percent-versus-fraction and displayed rounding are allowed for.
    """
    tol = 0.5 * 10 ** (-mention.decimals)
    if mention.aside:
        source_value = abs(source_value)  # the brackets carry no sign: 7.1% can be a cell of 0.071 or of -0.071
    candidates: list[tuple[str, float]] = [("exact", source_value)]
    if mention.unit in ("percent", "pp"):
        candidates.append(("fraction_to_percent", source_value * 100.0))
    if mention.scale != 1.0:
        candidates.append(("scaled", source_value / mention.scale))
    for factor, name in ((1e3, "thousands"), (1e6, "millions"), (1e9, "billions")):
        candidates.append((name, source_value / factor))
    for name, v in candidates:
        shown = mention.value
        if abs(shown - v) <= tol * 1.0001 + 1e-12:
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


def display_round(value: float, decimals: int):
    """Round the way a spreadsheet displays: halves go away from zero, judged on the number as written in decimal (2.675 shows as 2.68, 2414.5
    as 2,415). Python's round() sends exact halves to the even neighbour, which printed 2,414 where the workbook cell shows 2,415."""
    from decimal import ROUND_HALF_UP, Decimal, localcontext

    with localcontext() as ctx:
        ctx.prec = 80
        return Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _indian(integer_text: str) -> str:
    """12345678 -> 1,23,45,678: the last three digits, then groups of two."""
    if len(integer_text) <= 3:
        return integer_text
    head, last = integer_text[:-3], integer_text[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [last])


def format_like(old: NumberMention, new_source_value: float, transform: str) -> str:
    """Write ``new_source_value`` the way ``old`` was written: same affixes, decimals, separators and sign style.

    ``transform`` is the one the matcher found when it linked the mention to its source (see consistent_with_source).
    """
    shown = _TRANSFORMS[transform](new_source_value, old.scale)
    if old.aside:
        body = f"{display_round(abs(shown), old.decimals):,.{old.decimals}f}" if "," in old.raw else f"{display_round(abs(shown), old.decimals):.{old.decimals}f}"
        m = _NUM_IN_RAW.search(old.raw)
        pre, post = old.raw[1:m.start()], old.raw[m.end():-1]
        return f"({'-' if shown < 0 and float(body.replace(',', '')) != 0 else ''}{pre}{body}{post})"
    rounded = display_round(abs(shown), old.decimals)
    use_commas = "," in old.raw
    body = f"{rounded:,.{old.decimals}f}" if use_commas else f"{rounded:.{old.decimals}f}"
    if use_commas and re.search(r"\d{1,2}(?:,\d{2})+,\d{3}", old.raw):
        whole, _, frac = f"{rounded:.{old.decimals}f}".partition(".")
        body = _indian(whole) + ("." + frac if frac else "")
    m = _NUM_IN_RAW.search(old.raw)
    if m.group(0).startswith(".") and body.startswith("0."):
        body = body[1:]  # a figure written without its leading zero (.5) keeps that style
    prefix = old.raw[: m.start()].replace("(", "").replace("-", "").replace("−", "").replace("–", "").replace("+", "")
    suffix = old.raw[m.end():].replace(")", "")
    explicit = old.raw.lstrip()[:1] in ("+", "-", "−", "–")  # a column of changes written with its sign keeps its sign style
    if shown < 0 and rounded != 0:
        minus = old.raw.lstrip()[:1] if old.raw.lstrip()[:1] in ("-", "−", "–") else "-"
        return f"({prefix}{body}{suffix})" if old.raw.lstrip().startswith("(") else f"{minus}{prefix}{body}{suffix}"
    return f"{'+' if explicit and rounded != 0 else ''}{prefix}{body}{suffix}"
