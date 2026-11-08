"""The small number-format language of a Spec: [currency]#,##0[.0..][suffix], suffix one of % K M B."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_FORMAT = re.compile(r"^(?P<cur>[$€£¥₹]?)(?P<int>#,##0|0)(?:\.(?P<dec>0+))?(?P<suf>%|K|M|B)?$")
_DIVISOR = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9}


class FormatError(ValueError):
    pass


def _parse(fmt: str) -> re.Match:
    m = _FORMAT.match(fmt or "")
    if not m:
        raise FormatError(f"unknown number format {fmt!r}; use for example #,##0  $#,##0.0M  0.0%  #,##0.00")
    return m


def format_class(fmt: str) -> str:
    m = _parse(fmt)
    if m.group("suf") == "%":
        return "percent"
    return "currency" if m.group("cur") else "plain"


def plain(value: float) -> str:
    """A number as people read it in a list: thousands separators, no exponent for ordinary sizes."""
    return format(float(value), ",.10g")


def excel_format(fmt: str) -> str:
    """The Excel number format for a Spec format. K, M and B scaling has no cell-format equivalent that keeps the stored value, so it is refused."""
    m = _parse(fmt)
    if m.group("suf") in ("K", "M", "B"):
        raise FormatError(f"{fmt} scales the number; a workbook cell keeps the real value, so use a format without K, M or B")
    cur = f'"{m.group("cur")}"' if m.group("cur") else ""
    return f"{cur}{m.group('int')}{'.' + m.group('dec') if m.group('dec') else ''}{m.group('suf') or ''}"


def format_value(fmt: str, value: float) -> str:
    """Render ``value`` the way the format says. A percent format multiplies by 100; K, M and B divide."""
    m = _parse(fmt)
    suf = m.group("suf") or ""
    shown = value * 100.0 if suf == "%" else value / _DIVISOR.get(suf, 1.0)
    decimals = len(m.group("dec") or "")
    rounded = Decimal(repr(abs(shown))).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    body = f"{rounded:,.{decimals}f}" if m.group("int") == "#,##0" else f"{rounded:.{decimals}f}"
    text = f"{m.group('cur')}{body}{suf}"
    return f"-{text}" if shown < 0 and float(body.replace(",", "")) != 0 else text
