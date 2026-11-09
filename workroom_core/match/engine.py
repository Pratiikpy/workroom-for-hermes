"""Link numbers in documents to source cells using value fit and label evidence, and abstain when unsure.

Equal numbers never create a link by themselves. A link is accepted only with label support, no period conflict
and a clear margin over the next candidate; everything else is reported as needs-confirmation or no-candidate.
"""

from __future__ import annotations

import bisect
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..ooxml.xlsx import SourceCell
from .numbers import NumberMention, consistent_with_source

_STOP = frozenset(
    "the a an of in on at to for and or by with from is are was were be as this that these those total sum "
    "all per vs versus year yoy qoq new old".split()
)
_PERIOD = re.compile(r"\b(q[1-4]|h[12]|fy\s?\d{2,4}|20[0-4]\d|19[89]\d|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I)

ACCEPT_LABEL = 0.6
ACCEPT_MARGIN = 0.25


def _stem(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("sses"):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


_QUARTER_FORMS = (
    (re.compile(r"\b([1-4])\s?\.?\s?q\b\.?"), r"q\1"),       # 1.Q.  1Q  1 Q
    (re.compile(r"\bq\s?\.?\s?([1-4])\b"), r"q\1"),           # Q 1  Q.1
    (re.compile(r"\b(first|1st)\s+quarter\b"), "q1"),
    (re.compile(r"\b(second|2nd)\s+quarter\b"), "q2"),
    (re.compile(r"\b(third|3rd)\s+quarter\b"), "q3"),
    (re.compile(r"\b(fourth|4th)\s+quarter\b"), "q4"),
)


def _quarter_forms(text: str) -> str:
    for pat, rep in _QUARTER_FORMS:
        text = pat.sub(rep, text)
    return text


_SYNONYMS = (
    ("revenue", ("sales", "turnover", "top line", "topline", "net sales")),
    ("opex", ("operating costs", "operating expenses", "operating expense", "running costs", "opex")),
    ("margin", ("gross margin", "gross profit rate", "profit margin")),
    ("headcount", ("staff", "employees", "people on payroll", "workforce", "fte")),
    ("churn", ("attrition", "customers lost", "customer churn")),
    ("shipment", ("orders shipped", "shipments", "orders out the door")),
    ("cash", ("cash balance", "cash on hand")),
    ("backlog", ("open orders", "unfilled demand", "order book")),
    ("profit", ("net income", "earnings", "bottom line")),
    ("capex", ("capital expenditure", "capital expenditures", "capital spending")),
)
_SYN_PATTERNS = [(re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(re.escape(p) for p in sorted(phrases + (canon,), key=len, reverse=True))), canon) for canon, phrases in _SYNONYMS]


def _canonical(text: str) -> str:
    for pat, canon in _SYN_PATTERNS:
        text = pat.sub(canon, text)
    return text


def tokens(text: str) -> list[str]:
    text = _canonical(_quarter_forms(text.lower()))
    return [_stem(w) if not w[0].isdigit() else w for w in re.findall(r"[a-z0-9][a-z0-9&]*", text) if w not in _STOP and (len(w) > 1 or w.isdigit())]


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def periods(text: str) -> frozenset[str]:
    """Normalised period tokens: q1, h2, fy2025, 2025, jan."""
    out = set()
    text = _quarter_forms(text.lower())
    for m in _PERIOD.finditer(text):
        p = re.sub(r"\s", "", m.group(1).lower())
        if p.startswith("fy"):
            digits = p[2:]
            p = "fy" + (digits if len(digits) == 4 else "20" + digits)
        elif p[:3] in _MONTHS:
            p = p[:3]
        out.add(p)
    return frozenset(out)


@dataclass(frozen=True)
class Mention:
    where: str
    number: NumberMention
    context: tuple[str, ...]  # strings that describe it: paragraph, row/column headers, series, category, title
    span: tuple[int, int] | None = None  # where the number sits inside context[0], so only that occurrence is masked
    section: str = ""  # the heading it sits under, when the document has one
    row_head: str = ""  # for a figure in a table: the text that heads its row


@dataclass(frozen=True)
class Scored:
    cell: SourceCell
    transform: str
    label_score: float
    period_conflict: bool
    score: float
    in_section: bool = False  # the source sheet is the one the document's own heading names


@dataclass(frozen=True)
class MatchResult:
    mention: Mention
    decision: str  # accept | confirm | none
    best: Scored | None
    runner_up: Scored | None
    reason: str
    candidates: tuple[Scored, ...] = field(default=())


class SourceIndex:
    """Precomputed label tokens and document frequencies for a set of source cells."""

    def __init__(self, cells: list[SourceCell]) -> None:
        self.cells = [c for c in cells if not c.is_date]
        # Counting how many cells carry each word needs every cell's words once; keeping every cell's words would cost gigabytes on a large
        # workbook, so only the counts are kept and a cell's words are worked out again when a number turns out to be a candidate for it.
        self._tokens: dict[int, frozenset[str]] = {}
        self._periods: dict[int, frozenset[str]] = {}
        df: Counter[str] = Counter()
        seen: dict[str, frozenset[str]] = {}
        for c in self.cells:
            text = " ".join(c.row_labels + c.col_labels + (c.sheet,))
            toks = seen.get(text)
            if toks is None:
                toks = frozenset(tokens(text))
                if len(seen) < 200_000:
                    seen[text] = toks
            df.update(toks)
        n = max(len(self.cells), 1)
        self.idf = {t: math.log(1 + n / f) for t, f in df.items()}
        self._order = sorted(range(len(self.cells)), key=lambda i: self.cells[i].value)
        self._sorted_values = [self.cells[i].value for i in self._order]

    def candidates(self, number: NumberMention) -> list[int]:
        """Indices of the cells whose value could display as ``number`` under any transform consistent_with_source allows, in cell order.
        A superset found by value range; the caller still applies consistent_with_source, so the answer is unchanged, only far cheaper."""
        shown = number.value
        pad = 0.5 * 10 ** (-number.decimals) * 1.0001 + 1e-12
        factors = [1.0, 1e3, 1e6, 1e9]
        if number.unit in ("percent", "pp"):
            factors.append(0.01)
        if number.scale != 1.0 and number.scale > 0:
            factors.append(number.scale)
        found: set[int] = set()
        for f in factors:
            lo, hi = (shown - pad) * f, (shown + pad) * f
            slack = 1e-9 * max(abs(lo), abs(hi), 1.0)
            a = bisect.bisect_left(self._sorted_values, lo - slack)
            b = bisect.bisect_right(self._sorted_values, hi + slack)
            found.update(self._order[a:b])
        return sorted(found)

    def label_tokens(self, i: int) -> frozenset[str]:
        got = self._tokens.get(i)
        if got is None:
            c = self.cells[i]
            got = frozenset(tokens(" ".join(c.row_labels + c.col_labels + (c.sheet,))))
            if len(self._tokens) >= 50_000:
                self._tokens.clear()
            self._tokens[i] = got
        return got

    def cell_periods(self, i: int) -> frozenset[str]:
        got = self._periods.get(i)
        if got is None:
            c = self.cells[i]
            got = periods(" ".join(c.row_labels + c.col_labels))
            if len(self._periods) >= 50_000:
                self._periods.clear()
            self._periods[i] = got
        return got

    def label_score(self, i: int, ctx_tokens: set[str]) -> float:
        labels = self.label_tokens(i)
        if not labels:
            return 0.0
        total = sum(self.idf.get(t, 1.0) for t in labels)
        hit = sum(self.idf.get(t, 1.0) for t in labels if t in ctx_tokens)
        return hit / total if total else 0.0


SECTION_BONUS = 0.25  # added to a candidate whose sheet is named by the heading the figure sits under: it breaks ties, it never lifts a weak match
_DOTTED_ID = re.compile(r"(?<![\d.])\d+(?:\.\d+)+(?![\d.])")


def section_agrees(sheet: str, section: str) -> bool:
    """Does the heading a figure sits under name the sheet a candidate cell is on? Statements number their notes and the data sets number their
    sheets the same way ("4.1.2 Departmental Outputs" over sheet "4.1.2"), or the sheet takes the heading's words ("Balance sheet")."""
    if not section or not sheet:
        return False
    ids = set(_DOTTED_ID.findall(sheet))
    if ids:
        return bool(ids & set(_DOTTED_ID.findall(section)))
    words = {t for t in tokens(sheet) if t[0].isalpha()}
    return bool(words) and words <= set(tokens(section))


_MOVEMENT = re.compile(r"\b(?:increas|decreas|chang|grow|grew|declin|ris(?:e|en|ing)\b|rose\b|fall|fell\b|reduc|variance|movement|up by|down by|higher than|lower than)", re.IGNORECASE)
_MOVEMENT_WINDOW = 70  # characters before the figure in which "decreased by" or "up" describes it


def _describes_a_change(window: str) -> bool:
    return bool(_MOVEMENT.search(window))


ROW_WEIGHT = 0.3  # how much a candidate whose row headings cover the document table's own row heading gains
ROW_FIT_MIN = 0.34  # below this share of the document row heading found in the cell's row headings, the row is not the same row


def row_fit(doc_row: set[str], cell_labels: tuple[str, ...], idf: dict[str, float]) -> float:
    """Share (weighted by how telling each word is) of the document table's row heading found among the cell's headings. Tables are often turned
    on their side between the report and the workbook, so the row heading may sit on the cell's column."""
    if not doc_row:
        return 1.0
    have = set(tokens(" ".join(cell_labels)))
    total = sum(idf.get(t, 1.0) for t in doc_row)
    return sum(idf.get(t, 1.0) for t in doc_row if t in have) / total if total else 1.0


UNIQUE_DIGITS = 5  # a number this long that fits exactly one source cell is a fingerprint, not a coincidence
UNNAMED_SCALE_LABEL = 0.5  # a figure that differs from its cell by 1,000 and names no unit is only offered when the text also names at least half of the cell's headings
CHANCE_LABEL = 0.3  # ...and the text names less than this share of the cell's headings (measured on two Victorian department reports: every real short link named more)
CHANCE_DIGITS = 3  # with no label evidence at all, a number with fewer significant digits than this is a coincidence, not a candidate
UNIQUE_LABEL = 0.15  # ...provided the text names at least part of that cell
NEAR_CHARS = 160  # in a long paragraph only the words around the number describe it
_IMPLICIT_SCALES = ("thousands", "millions", "billions")
_SCALE_NAMED = {
    "thousands": re.compile(r"\bthousands?\b|(?<![\d,.])000s?(?![\d,])|\$\s?k\b|\busd\s?k\b|\bin k\b|\bkusd\b"),
    "millions": re.compile(r"\bmillions?\b|\bmm\b|\bmn\b|\$\s?m\b|\busd\s?m\b|\bin m\b|\(m\)|\bmusd\b"),
    "billions": re.compile(r"\bbillions?\b|\bbn\b|\$\s?b\b|\busd\s?b\b|\(bn\)|\(b\)"),
}


def _scale_is_named(transform: str, context_text: str, cell: SourceCell | None) -> bool:
    """A document figure that differs from its cell by 1,000, 1,000,000 or 1,000,000,000 is the same figure only when something names that unit:
    the text around it ("in thousands", "$M") or the cell's own headings. Without that, equal digits at another scale are a coincidence."""
    pattern = _SCALE_NAMED.get(transform)
    if pattern is None:
        return True
    haystack = context_text if cell is None else context_text + " " + " ".join(cell.row_labels + cell.col_labels + (cell.sheet,))
    return bool(pattern.search(haystack.lower()))


def _significant_digits(raw: str) -> int:
    digits = re.sub(r"\D", "", raw).lstrip("0")
    return len(digits)


_OPPOSITES = tuple(
    (tuple(tokens(a))[0], tuple(tokens(b))[0])
    for a, b in (("opening", "closing"), ("receipts", "payments"), ("assets", "liabilities"), ("income", "expenses"), ("increase", "decrease"), ("gain", "loss"), ("debit", "credit"),
                 ("current", "noncurrent"), ("inflow", "outflow"), ("revenue", "cost"), ("profit", "loss"), ("surplus", "deficit"))
)


def _opposite_words(context: set[str], cell: set[str]) -> tuple[str, str] | None:
    """A pair of opposite words, one in the text and the other in the cell's headings, with neither word on the other side. The same value under
    \"closing balance\" in the report and \"opening balance\" in the workbook is an accounting identity, not a match."""
    for a, b in _OPPOSITES:
        if a in context and b in cell and a not in cell and b not in context:
            return a, b
        if b in context and a in cell and b not in cell and a not in context:
            return b, a
    return None


def is_coincidence(label_score: float, raw: str) -> bool:
    """A candidate that rests on almost nothing but an equal value: the text names little of the cell and the number is short enough to equal some cell by chance
    (or by a power of a thousand). Such a candidate stays on offer, but it is not a question the owner needs to answer."""
    return label_score < CHANCE_LABEL and _significant_digits(raw) < CHANCE_DIGITS


def _near(text: str, span: tuple[int, int] | None) -> tuple[str, tuple[int, int] | None]:
    if span is None or len(text) <= 2 * NEAR_CHARS:
        return text, span
    lo = max(0, span[0] - NEAR_CHARS)
    hi = min(len(text), span[1] + NEAR_CHARS)
    return text[lo:hi], (span[0] - lo, span[1] - lo)


def match_mentions(mentions: list[Mention], index: SourceIndex, top: int = 5) -> list[MatchResult]:
    results: list[MatchResult] = []
    for m in mentions:
        ctx = list(m.context)
        span = m.span
        if ctx:
            ctx[0], span = _near(ctx[0], span)
        if span and ctx and ctx[0][span[0] : span[1]] == m.number.raw:
            ctx[0] = ctx[0][: span[0]] + " " + ctx[0][span[1] :]
        short = _significant_digits(m.number.raw) < 3
        ctx_text = " ".join(ctx)
        doc_row = {t for t in tokens(m.row_head) if t[0].isalpha()}
        change_text = ctx[0][max(0, span[0] - _MOVEMENT_WINDOW) : span[0]] if (ctx and span) else ""
        ctx_tokens = set(tokens(ctx_text))
        ctx_periods = periods(ctx_text)
        scored: list[Scored] = []
        for i in index.candidates(m.number):
            cell = index.cells[i]
            ok, transform = consistent_with_source(m.number, cell.value)
            if not ok:
                continue
            if transform in _IMPLICIT_SCALES and m.number.unit in ("percent", "pp"):
                continue  # a percentage is never a scaled money figure
            ls = index.label_score(i, ctx_tokens)
            if transform in _IMPLICIT_SCALES and (
                (short and not _scale_is_named(transform, ctx_text, None))  # a short number says its unit itself or it is a count: the workbook's "$000" is not the document's
                or (not _scale_is_named(transform, ctx_text, cell) and ls < UNNAMED_SCALE_LABEL)
            ):
                continue  # the same digits at a 1,000-fold scale that nothing names, with no words behind them, are a coincidence, not a candidate
            cp = index.cell_periods(i)
            conflict = bool(ctx_periods and cp and not (ctx_periods & cp))
            in_section = section_agrees(cell.sheet, m.section)
            score = ls - (1.0 if conflict else 0.0) + (0.02 if transform == "exact" else 0.0) + (SECTION_BONUS if in_section else 0.0) + ROW_WEIGHT * row_fit(doc_row, cell.row_labels + cell.col_labels, index.idf)
            scored.append(Scored(cell, transform, ls, conflict, score, in_section))
        scored.sort(key=lambda s: -s.score)
        if not scored:
            results.append(MatchResult(m, "none", None, None, "no source cell is consistent with this number"))
            continue
        best = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        margin = best.score - (runner.score if runner else -1.0)
        # a label made only of numbers ("Item 17", "2025") that happens to equal a number elsewhere in the text is not evidence; some word must agree
        shared = set(tokens(" ".join(best.cell.row_labels + best.cell.col_labels + (best.cell.sheet,)))) & ctx_tokens
        no_word = len(index.cells) >= 20 and not any(t[0].isalpha() and index.idf.get(t, 1.0) > 1.2 for t in shared)  # in a workbook of any size, a heading nearly every cell shares ("Value", "Amount") names nothing
        opposite = _opposite_words(ctx_tokens, set(tokens(" ".join(best.cell.row_labels + best.cell.col_labels))))
        a_balance = _describes_a_change(change_text) and not _describes_a_change(" ".join(best.cell.row_labels + best.cell.col_labels))
        if a_balance and m.number.unit != "percent":
            decision, reason = "confirm", "the text describes a change (an increase, a decrease) and the cell is a balance, not a movement"
        elif opposite:
            decision, reason = "confirm", f"the text says \"{opposite[0]}\" and the cell is labelled \"{opposite[1]}\": the same value, opposite words"
        elif best.transform in _IMPLICIT_SCALES and short:
            decision, reason = "confirm", "a short number fits many cells once scaled, so it needs a person"
        elif best.transform in _IMPLICIT_SCALES and not _scale_is_named(best.transform, ctx_text, best.cell):
            factor = {"thousands": "1,000", "millions": "1,000,000", "billions": "1,000,000,000"}[best.transform]
            decision, reason = "confirm", f"the source cell is {factor} times this figure and nothing in the text or the cell's headings names that unit"
        elif best.period_conflict:
            decision, reason = "confirm", "the period in the text does not match the period of the closest cell"
        elif no_word and best.label_score >= UNIQUE_LABEL:
            decision, reason = "confirm", "only numbers in the labels agree with the text; no word names this figure"
        elif runner is None and not short and _significant_digits(m.number.raw) >= UNIQUE_DIGITS and best.label_score >= UNIQUE_LABEL:
            decision, reason = "accept", "this long number fits exactly one source cell and the text names part of it"
        elif best.label_score >= ACCEPT_LABEL and margin >= ACCEPT_MARGIN:
            decision, reason = "accept", "value, label and period agree with a clear margin"
        elif best.label_score >= ACCEPT_LABEL:
            decision, reason = "confirm", "several cells fit about equally well"
        elif runner is None:
            decision, reason = "confirm", "one cell has this value but nothing in the text names it"
        else:
            decision, reason = "confirm", "this value appears in several cells and the text does not tell them apart"
        if decision == "accept" and doc_row and row_fit(doc_row, best.cell.row_labels + best.cell.col_labels, index.idf) < ROW_FIT_MIN:
            decision, reason = "confirm", "the row heading in the document does not match the row of the closest cell"
        elif decision == "accept" and m.section and not best.in_section and any(c.in_section for c in scored[1:]):
            decision, reason = "confirm", "the closest cell is not on the sheet the section names, and a cell on that sheet fits too"
        results.append(MatchResult(m, decision, best, runner, reason, tuple(scored[:top])))
    return results
