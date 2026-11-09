"""Reporting periods named in labels and in text: quarters, halves, years, months, and "three months ended <date>".

A period has a kind and an integer index on that kind's own number line, so "the previous period" and "the same period a year earlier"
are subtraction. Calendar mapping is used only for ordering: a fiscal Q3 is simply the third quarter of its year. Parsing is strict:
a label that is not clearly a period is not a period.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
_STEP = {"q": 4, "m": 12, "h": 2, "y": 1, "dt": 1}  # how many periods of this kind make a year
_NAME = {"q": "quarter", "m": "month", "h": "half", "y": "year"}


@dataclass(frozen=True)
class Period:
    kind: str   # q (quarter) | m (month) | h (half-year) | y (year) | ytd (year to date, tagged with its length in months) | dt (a dated point such as 30 June 2025)
    index: int  # position on the kind's own number line
    months: int = 0  # ytd: the length in months; dt: month * 100 + day, so 30 June 2025 and 1 July 2025 are different series that each step a year

    def shifted(self, n: int) -> Period:
        return Period(self.kind, self.index + n, self.months)

    @property
    def previous(self) -> Period | None:
        return None if self.kind == "ytd" else self.shifted(-1)

    @property
    def year_ago(self) -> Period:
        return self.shifted(-(12 if self.kind == "ytd" else _STEP[self.kind]))

    @property
    def year(self) -> int:
        return self.index // _STEP[self.kind] if self.kind in _STEP else self.index // 12


def _year(text: str) -> int | None:
    n = int(text)
    if len(text) == 2:
        return 2000 + n if n < 70 else 1900 + n
    return n if 1900 <= n <= 2100 else None


_Q1 = re.compile(r"\bq\s*([1-4])\s*[-'’ /]?\s*(?:fy\s*)?((?:19|20)?\d{2})\b", re.I)
_Q2 = re.compile(r"\b([1-4])\s*q\s*[-'’ /]?\s*(?:fy\s*)?((?:19|20)?\d{2})\b", re.I)
_Q3 = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+of)?\s+(?:fiscal\s+|fy\s*)?((?:19|20)\d{2})\b", re.I)
_H1 = re.compile(r"\bh\s*([12])\s*[-'’ /]?\s*(?:fy\s*)?((?:19|20)?\d{2})\b", re.I)
_H2 = re.compile(r"\b(first|second)\s+half(?:\s+of)?\s+(?:fiscal\s+|fy\s*)?((?:19|20)\d{2})\b", re.I)
_FY = re.compile(r"\b(?:fy|fiscal(?:\s+year)?)\s*[-'’ ]?\s*((?:19|20)?\d{2})\b", re.I)
_MON = re.compile(r"\b((?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?))\.?[ \t\-’']*((?:19|20)?\d{2})\b", re.I)
_DMY = re.compile(r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?,?\s+((?:19|20)\d{2})\b", re.I)
_ISO_M = re.compile(r"^\s*((?:19|20)\d{2})[-/](0?[1-9]|1[0-2])\s*$")
_ENDED = re.compile(r"\b(three|six|nine|twelve|3|6|9|12)\s+months?\s+ended\s+(.+)", re.I)
_DATE_ISO = re.compile(r"((?:19|20)\d{2})-(\d{2})-(\d{2})")
_DATE_TXT = re.compile(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+((?:19|20)\d{2})")
_LEN = {"three": 3, "6": 6, "3": 3, "six": 6, "nine": 9, "9": 9, "twelve": 12, "12": 12}


def _end_date(text: str) -> date | None:
    m = _DATE_ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DATE_TXT.search(text)
    if m and m.group(1).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


def parse_period(label: str) -> Period | None:
    """The reporting period a label names, or None. When a label names two (a range, a pair of years) it is not read."""
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    if not text or len(text) > 60:
        return None
    m = _ENDED.search(text)
    if m:
        d = _end_date(m.group(2))
        if d is None:
            return None
        length = _LEN[m.group(1).lower()]
        month_index = d.year * 12 + d.month - 1
        if length == 3:
            return Period("q", d.year * 4 + (d.month - 1) // 3)
        if length == 6:
            return Period("ytd", month_index, 6)
        if length == 9:
            return Period("ytd", month_index, 9)
        return Period("y", d.year)
    found: list[Period] = []
    for rx in (_Q1, _Q2):
        for q, y in rx.findall(text):
            yr = _year(y)
            if yr:
                found.append(Period("q", yr * 4 + int(q) - 1))
    for w, y in _Q3.findall(text):
        found.append(Period("q", int(y) * 4 + _ORD[w.lower()] - 1))
    for h, y in _H1.findall(text):
        yr = _year(y)
        if yr:
            found.append(Period("h", yr * 2 + int(h) - 1))
    for w, y in _H2.findall(text):
        found.append(Period("h", int(y) * 2 + (1 if w.lower() == "first" else 2) - 1))
    if not found:
        for y in _FY.findall(text):
            yr = _year(y)
            if yr:
                found.append(Period("y", yr))
    if not found:
        for day, mon, y in _DMY.findall(text):
            if 1 <= int(day) <= 31:
                found.append(Period("dt", int(y), _MONTHS[mon[:3].lower()] * 100 + int(day)))
    if not found:
        for mon, y in _MON.findall(text):
            yr = _year(y)
            if yr:
                found.append(Period("m", yr * 12 + _MONTHS[mon[:3].lower()] - 1))
        m = _ISO_M.match(text)
        if m:
            found.append(Period("m", int(m.group(1)) * 12 + int(m.group(2)) - 1))
    if not found and re.fullmatch(r"(?:19|20)\d{2}", text):
        found.append(Period("y", int(text)))
    return found[0] if len(set(found)) == 1 else None


def period_label(p: Period, template: str) -> str:
    """Write period `p` in the style of `template` (a label that parsed to a period of the same kind)."""
    t = parse_period(template)
    if t is None or t.kind != p.kind:
        raise ValueError("the template is not a period of the same kind")
    per, y = _STEP[p.kind], p.index // _STEP[p.kind]
    n = p.index % per + 1
    out = template

    def fix_year(match_text: str, y_new: int, short: bool) -> str:
        return str(y_new % 100).zfill(2) if short else str(y_new)

    if p.kind == "q":
        for rx in (_Q1, _Q2, _Q3):
            m = rx.search(out)
            if m:
                ytxt = m.group(2)
                ynew = fix_year(ytxt, y, len(ytxt) == 2)
                if rx is _Q3:
                    word = ("first", "second", "third", "fourth")[n - 1]
                    word = word.capitalize() if m.group(1)[0].isupper() else word
                    return out[:m.start(1)] + word + out[m.end(1):m.start(2)] + ynew + out[m.end(2):]
                a, b = (m.start(1), m.start(2))
                return out[:a] + str(n) + out[a + 1:b] + ynew + out[m.end(2):]
    if p.kind == "h":
        for rx in (_H1, _H2):
            m = rx.search(out)
            if m:
                ytxt = m.group(2)
                ynew = fix_year(ytxt, y, len(ytxt) == 2)
                if rx is _H2:
                    word = "first" if n == 1 else "second"
                    word = word.capitalize() if m.group(1)[0].isupper() else word
                    return out[:m.start(1)] + word + out[m.end(1):m.start(2)] + ynew + out[m.end(2):]
                return out[:m.start(1)] + str(n) + out[m.end(1):m.start(2)] + ynew + out[m.end(2):]
    if p.kind == "y":
        for rx in (_FY, ):
            m = rx.search(out)
            if m:
                ytxt = m.group(1)
                return out[:m.start(1)] + fix_year(ytxt, p.index, len(ytxt) == 2) + out[m.end(1):]
        if re.fullmatch(r"(?:19|20)\d{2}", out.strip()):
            return str(p.index)
    if p.kind == "dt":
        m = _DMY.search(out)
        if m:
            return out[:m.start(3)] + str(p.index) + out[m.end(3):]
    if p.kind == "m":
        m = _MON.search(out)
        if m:
            word = m.group(1)
            names = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
            shown = names[n - 1] if len(word) > 3 else names[n - 1][:3]
            shown = shown if word[0].isupper() else shown.lower()
            ytxt = m.group(2)
            return out[:m.start(1)] + shown + out[m.end(1):m.start(2)] + fix_year(ytxt, y, len(ytxt) == 2) + out[m.end(2):]
    raise ValueError("cannot write this period in the style of the template")


def find_periods(text: str) -> list[tuple[int, int, Period]]:
    """Every period named in a stretch of prose, left to right, as (start, end, period). A match that does not read as exactly one period is skipped."""
    spans: list[tuple[int, int]] = []
    for rx in (_Q3, _Q1, _Q2, _H2, _H1, _FY, _DMY, _MON):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end()))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out: list[tuple[int, int, Period]] = []
    last_end = -1
    for a, b in spans:
        if a < last_end:
            continue
        p = parse_period(text[a:b])
        if p is not None:
            out.append((a, b, p))
            last_end = b
    return out


def describe_period(p: Period) -> str:
    """A plain name for a period, for messages: Q4 2026, Mar 2026, H2 2026, FY2026."""
    if p.kind == "q":
        return f"Q{p.index % 4 + 1} {p.index // 4}"
    if p.kind == "m":
        return f"{('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[p.index % 12]} {p.index // 12}"
    if p.kind == "h":
        return f"H{p.index % 2 + 1} {p.index // 2}"
    if p.kind == "y":
        return f"FY{p.index}"
    if p.kind == "dt":
        return f"{p.months % 100} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[p.months // 100 - 1]} {p.index}"
    return f"{p.months} months to {(p.index % 12) + 1}/{p.index // 12}"
