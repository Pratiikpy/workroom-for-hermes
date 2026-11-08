"""Numbers in a document that are calculated from source cells: a percent change, a margin, a difference, a total.

A calculated number is found by arithmetic, never by wording: the sentence's own figure must be reproduced, at the precision it is
written, by an operation over cells the document already ties (or the previous or year-earlier cell of the same series). When more
than one reading fits, none is chosen for the owner. Once the owner accepts a calculation it is kept in step like any other tie,
and it never changes sign silently: a "grew 8%" that would become a fall is held and reported.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass

from ..match.numbers import NumberMention, consistent_with_source
from .claims import _DOWN, _UP

OPS = ("pct_change", "ratio", "diff", "sum")
_SCALED = ("exact", "thousands", "millions", "billions", "scaled")
_UP_RX = re.compile(rf"\b{_UP}\b", re.I)
_DOWN_RX = re.compile(rf"\b{_DOWN}\b", re.I)


@dataclass(frozen=True)
class Operand:
    file: str
    sheet: str
    ref: str
    value: float
    label: str
    family: str = ""  # the transform its tie uses, so a sum or difference only mixes cells written the same way
    role: str = "cell"  # cell | previous | year_ago

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.file, self.sheet, self.ref)


@dataclass(frozen=True)
class Calc:
    op: str
    terms: tuple[Operand, ...]
    value: float  # in source units, before the display transform
    transform: str
    scope: str  # paragraph | slide
    cue: str  # up | down | ""

    @property
    def formula(self) -> str:
        return json.dumps({"op": self.op, "terms": [list(t.key) for t in self.terms], "cue": self.cue})

    def words(self) -> str:
        names = [f"{t.label}" + ("" if t.role == "cell" else f" ({t.role.replace('_', ' ')})") for t in self.terms]
        if self.op == "pct_change":
            return f"({names[0]} - {names[1]}) / {names[1]}"
        if self.op == "ratio":
            return f"{names[0]} / {names[1]}"
        if self.op == "diff":
            return f"{names[0]} - {names[1]}"
        return " + ".join(names)


def describe(calc: "Calc") -> str:
    """The calculation with its values, for the owner to check by eye."""
    vals = [format(t.value, ",.10g") for t in calc.terms]
    shown = {"pct_change": f"({vals[0]} - {vals[1]}) / {vals[1]}" if len(vals) == 2 else "", "ratio": " / ".join(vals), "diff": " - ".join(vals), "sum": " + ".join(vals)}[calc.op]
    result = calc.value * 100 if calc.transform == "fraction_to_percent" else calc.value
    return f"{shown} = {format(result, ',.6g')}{'%' if calc.transform == 'fraction_to_percent' else ''}"


def compute(op: str, values: list[float]) -> float | None:
    if op == "pct_change":
        return None if values[1] == 0 else (values[0] - values[1]) / abs(values[1])
    if op == "ratio":
        return None if values[1] == 0 else values[0] / values[1]
    if op == "diff":
        return values[0] - values[1]
    if op == "sum":
        return sum(values)
    return None


def evaluate(formula: str, values: dict[tuple[str, str, str], float]) -> float | None:
    """The calculation's value over the current source values, or None when a cell is missing or the arithmetic is undefined."""
    try:
        f = json.loads(formula)
        vals = [values[tuple(t)] for t in f["terms"]]
        return compute(f["op"], vals)
    except (ValueError, KeyError, TypeError):
        return None


def direction_cue(text: str, start: int, end: int) -> str:
    """up or down when a direction word stands right beside the number (\"up 8%\", \"a 3% decline\"), else empty."""
    before, after = text[max(0, start - 22):start], text[end:end + 12]
    best = ("", 10 ** 6)
    for rx, name in ((_UP_RX, "up"), (_DOWN_RX, "down")):
        for m in rx.finditer(before):
            best = min(best, (name, len(before) - m.end()), key=lambda x: x[1])
        for m in rx.finditer(after):
            best = min(best, (name, m.start()), key=lambda x: x[1])
    return best[0]


def _fits(number: NumberMention, op: str, value: float, family: str, cue: str) -> str | None:
    """The display transform under which `value` is what the mention shows, or None."""
    if cue == "up" and value <= 0 and op in ("pct_change", "diff") or cue == "down" and value >= 0 and op in ("pct_change", "diff"):
        return None
    shown = NumberMention(number.raw, abs(number.value), abs(number.scaled), number.decimals, number.unit, number.scale, False, number.start, number.end)
    ok, transform = consistent_with_source(shown, abs(value))
    if not ok:
        return None
    if number.unit in ("percent", "pp"):
        return transform if transform == "fraction_to_percent" and op in ("pct_change", "ratio", "diff") else None
    if op in ("pct_change", "ratio"):
        return None  # a dimensionless result cannot be a money or count figure
    if transform not in _SCALED or (family and transform != family and not (family == "exact" and transform == "exact")):
        return None
    return transform


def explain(number: NumberMention, para_pool: list[Operand], slide_pool: list[Operand], cue: str) -> tuple[str, list[Calc]]:
    """Every way the figure can be calculated from the nearest pool that explains it at all (the paragraph first, then the slide)."""
    for scope, pool in (("paragraph", para_pool), ("slide", slide_pool)):
        found = _search(number, pool, cue, scope)
        if found:
            return scope, found
    return "", []


def _search(number: NumberMention, pool: list[Operand], cue: str, scope: str) -> list[Calc]:
    pool = list({o.key: o for o in pool}.values())[:12]
    out: dict[tuple, Calc] = {}
    pairs = list(itertools.permutations(pool, 2))
    for a, b in pairs:
        same_family = a.family == b.family or "previous" in (a.role, b.role) or "year_ago" in (a.role, b.role)
        if not same_family:
            continue
        for op in ("pct_change", "ratio", "diff"):
            v = compute(op, [a.value, b.value])
            if v is None:
                continue
            t = _fits(number, op, v, a.family, cue)
            if t:
                out[(op, a.key, b.key)] = Calc(op, (a, b), v, t, scope, cue)
    if number.unit not in ("percent", "pp") and len(pool) <= 8:
        for size in (2, 3):
            for combo in itertools.combinations(pool, size):
                if len({o.family for o in combo}) != 1 or any(o.role != "cell" for o in combo):
                    continue
                v = sum(o.value for o in combo)
                t = _fits(number, "sum", v, combo[0].family, cue)
                if t:
                    out[("sum", tuple(sorted(o.key for o in combo)))] = Calc("sum", combo, v, t, scope, cue)
    return list(out.values())
