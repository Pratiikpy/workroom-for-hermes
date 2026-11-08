"""Link numbers in documents to source cells using value fit and label evidence, and abstain when unsure.

Equal numbers never create a link by themselves. A link is accepted only with label support, no period conflict
and a clear margin over the next candidate; everything else is reported as needs-confirmation or no-candidate.
"""

from __future__ import annotations

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
    (re.compile(r"([1-4])\s?\.?\s?q\.?"), r"q"),       # 1.Q.  1Q  1 Q
    (re.compile(r"q\s?\.?\s?([1-4])"), r"q"),           # Q 1  Q.1
    (re.compile(r"(first|1st)\s+quarter"), "q1"),
    (re.compile(r"(second|2nd)\s+quarter"), "q2"),
    (re.compile(r"(third|3rd)\s+quarter"), "q3"),
    (re.compile(r"(fourth|4th)\s+quarter"), "q4"),
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


@dataclass(frozen=True)
class Scored:
    cell: SourceCell
    transform: str
    label_score: float
    period_conflict: bool
    score: float


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
        self.label_tokens: dict[int, set[str]] = {}
        df: Counter[str] = Counter()
        for i, c in enumerate(self.cells):
            toks = set(tokens(" ".join(c.row_labels + c.col_labels + (c.sheet,))))
            self.label_tokens[i] = toks
            df.update(toks)
        n = max(len(self.cells), 1)
        self.idf = {t: math.log(1 + n / f) for t, f in df.items()}
        self.periods = {i: periods(" ".join(c.row_labels + c.col_labels)) for i, c in enumerate(self.cells)}

    def label_score(self, i: int, ctx_tokens: set[str]) -> float:
        labels = self.label_tokens[i]
        if not labels:
            return 0.0
        total = sum(self.idf.get(t, 1.0) for t in labels)
        hit = sum(self.idf.get(t, 1.0) for t in labels if t in ctx_tokens)
        return hit / total if total else 0.0


def match_mentions(mentions: list[Mention], index: SourceIndex, top: int = 5) -> list[MatchResult]:
    results: list[MatchResult] = []
    for m in mentions:
        ctx = list(m.context)
        if m.span and ctx and ctx[0][m.span[0] : m.span[1]] == m.number.raw:
            ctx[0] = ctx[0][: m.span[0]] + " " + ctx[0][m.span[1] :]
        ctx_text = " ".join(ctx)
        ctx_tokens = set(tokens(ctx_text))
        ctx_periods = periods(ctx_text)
        scored: list[Scored] = []
        for i, cell in enumerate(index.cells):
            ok, transform = consistent_with_source(m.number, cell.value)
            if not ok:
                continue
            ls = index.label_score(i, ctx_tokens)
            cp = index.periods[i]
            conflict = bool(ctx_periods and cp and not (ctx_periods & cp))
            score = ls - (1.0 if conflict else 0.0) + (0.02 if transform == "exact" else 0.0)
            scored.append(Scored(cell, transform, ls, conflict, score))
        scored.sort(key=lambda s: -s.score)
        if not scored:
            results.append(MatchResult(m, "none", None, None, "no source cell is consistent with this number"))
            continue
        best = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        margin = best.score - (runner.score if runner else -1.0)
        if best.period_conflict:
            decision, reason = "confirm", "the period in the text does not match the period of the closest cell"
        elif best.label_score >= ACCEPT_LABEL and margin >= ACCEPT_MARGIN:
            decision, reason = "accept", "value, label and period agree with a clear margin"
        elif best.label_score >= ACCEPT_LABEL:
            decision, reason = "confirm", "several cells fit about equally well"
        elif runner is None:
            decision, reason = "confirm", "one cell has this value but nothing in the text names it"
        else:
            decision, reason = "confirm", "this value appears in several cells and the text does not tell them apart"
        results.append(MatchResult(m, decision, best, runner, reason, tuple(scored[:top])))
    return results
