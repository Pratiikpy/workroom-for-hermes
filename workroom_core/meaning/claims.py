"""Read the claims a sentence makes about its own numbers and check them: "up from", "grew from X to Y", "exceeded", "record".

Deterministic and closed. A pattern either matches or the sentence is reported as not checked; nothing is inferred from loose wording.
English only. The grammar, its limits and the abstentions are part of the contract and are measured in `bench/claims_bench.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..match.numbers import NumberMention, parse_numbers

# Only words that state a numeric direction. "Improved", "gained", "weakened" and the like depend on whether more is better, so they are not read.
_UP = (r"(?:up|higher|increase[sd]?|increasing|rose|rise[sn]?|rising|grew|grow(?:s|n|ing)?|growth|"
       r"climb(?:ed|s|ing)?|expand(?:ed|s|ing)?|expansion|surg(?:ed|es|ing)|jump(?:ed|s|ing)?)")
_DOWN = (r"(?:down|lower|decreas(?:e|ed|es|ing)|declin(?:e|ed|es|ing)|fell|fall(?:s|en|ing)?|drop(?:ped|s|ping)?|shr(?:ank|unk|ink(?:s|ing)?)|"
         r"contract(?:ed|s|ing|ion)?|slid(?:e|es|ing)?|slipp?(?:ed|s|ing)?|dipp?(?:ed|s|ing)?|reduc(?:ed|es|tion|ing)|"
         r"sank|plunge[sd]?|tumbl(?:ed|e|es))")
_FROM = r"(?:from|vs\.?|versus|compared (?:to|with)|relative to|against|than)"
_ABOVE = r"(?:exceed(?:ed|s|ing)?|beat|beating|surpass(?:ed|es|ing)?|topp(?:ed|ing)|above|ahead of|outpac(?:ed|ing))"
_BELOW = r"(?:below|missed|short of|under|behind|trail(?:ed|ing)|fell short of)"
_HIGH = r"(?:record|all[- ]time high|highest|largest|biggest|best|peak|strongest)"
_LOW = r"(?:all[- ]time low|lowest|smallest|worst|weakest)"

_G = lambda n: rf"[^⟦⟧.;!?]{{0,{n}}}"  # noqa: E731  words between two figures, never across a sentence or another figure

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("direction_from_to", re.compile(rf"\b(?P<v>{_UP}|{_DOWN})\b{_G(40)}\bfrom\b{_G(15)}⟦(?P<b>\d+)⟧{_G(25)}\bto\b{_G(15)}⟦(?P<a>\d+)⟧", re.I)),
    ("direction_to_from", re.compile(rf"\b(?P<v>{_UP}|{_DOWN})\b{_G(40)}\bto\b{_G(15)}⟦(?P<a>\d+)⟧{_G(25)}\bfrom\b{_G(15)}⟦(?P<b>\d+)⟧", re.I)),
    ("figure_direction_from", re.compile(rf"⟦(?P<a>\d+)⟧{_G(25)}\b(?P<v>{_UP}|{_DOWN})\b{_G(25)}\b{_FROM}\b{_G(15)}⟦(?P<b>\d+)⟧", re.I)),
    ("figure_than", re.compile(rf"⟦(?P<a>\d+)⟧{_G(20)}\b(?P<v>higher|greater|more|larger|bigger|lower|less|fewer|smaller)\b{_G(10)}\bthan\b{_G(15)}⟦(?P<b>\d+)⟧", re.I)),
    ("figure_compared", re.compile(rf"⟦(?P<a>\d+)⟧{_G(40)}\b(?P<v>{_ABOVE}|{_BELOW})\b{_G(12)}⟦(?P<b>\d+)⟧", re.I)),
]
_UNANCHORED: list[tuple[str, re.Pattern[str]]] = [
    ("direction_to", re.compile(rf"\b(?P<v>{_UP}|{_DOWN})\b{_G(40)}\bto\b{_G(15)}⟦(?P<a>\d+)⟧", re.I)),
    ("figure_direction", re.compile(rf"⟦(?P<a>\d+)⟧{_G(25)}\b(?P<v>{_UP}|{_DOWN})\b", re.I)),
]
_RANK_BEFORE = re.compile(rf"\b(?P<c>{_HIGH}|{_LOW})\b{_G(40)}⟦(?P<a>\d+)⟧", re.I)
_RANK_AFTER = re.compile(rf"⟦(?P<a>\d+)⟧{_G(40)}\b(?P<c>{_HIGH}|{_LOW})\b", re.I)
_UP_WORDS = re.compile(rf"^(?:{_UP}|higher|greater|more|larger|bigger|{_ABOVE})$", re.I)
_SIGN_AMBIGUOUS = re.compile(r"\b(?:loss(?:es)?|deficit|negative|burn)\b", re.I)
_CUE = re.compile(rf"\b(?:{_UP}|{_DOWN}|{_ABOVE}|{_BELOW}|{_HIGH}|{_LOW})\b", re.I)


@dataclass(frozen=True)
class Figure:
    index: int
    start: int
    end: int
    raw: str
    value: float
    unit: str


@dataclass(frozen=True)
class Claim:
    pattern: str  # direction_from_to | direction_to_from | figure_direction_from | figure_than | figure_compared | direction_to | figure_direction | rank
    relation: str  # gt | lt | max | min (for direction_to and figure_direction, gt and lt mean: against the previous period)
    a: int  # the figure the sentence is about
    b: int | None  # the figure it is compared with (none for a rank claim)
    cue: str
    span: tuple[int, int]
    text: str


@dataclass(frozen=True)
class Reading:
    claims: tuple[Claim, ...]
    not_checked: tuple[str, ...]  # direction or comparison words the grammar saw but could not turn into a claim, or declined to


def figures_in(text: str) -> list[Figure]:
    out: list[Figure] = []
    for m in parse_numbers(text):
        digits = re.sub(r"[^0-9.]", "", m.raw)
        if m.unit == "plain" and m.decimals == 0 and digits.isdigit() and 1900 <= int(digits) <= 2100:
            continue  # a year
        out.append(Figure(len(out), m.start, m.start + len(m.raw.rstrip(")")) if m.raw.endswith(")") and "(" not in m.raw else m.end, m.raw, m.scaled, m.unit))
    return out


def _class(unit: str) -> str:
    return unit.split(":")[0]


_RATIO = ("percent", "bps", "pp")


def _tokenised(text: str, figs: list[Figure], ratios: bool) -> str:
    """Figures become tokens. In amounts mode a percent is a bridge word ("up 8% from $14.0M"); in ratios mode only percents are figures."""
    out, pos = [], 0
    for f in figs:
        out.append(text[pos:f.start])
        primary = (f.unit in _RATIO) if ratios else (f.unit not in _RATIO)
        out.append(f"⟦{f.index}⟧" if primary else f"⟪{f.index}⟫")
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


def _sentence(token: str, m: re.Match[str]) -> str:
    start = max(token.rfind(c, 0, m.start()) for c in ".!?") + 1
    ends = [i for i in (token.find(c, m.end()) for c in ".!?") if i >= 0]
    return token[start:min(ends) if ends else len(token)]


def read_claims(text: str, figs: list[Figure] | None = None) -> Reading:
    """Every claim the grammar can read in `text`, and the cue words it could not read."""
    figs = figures_in(text) if figs is None else figs
    claims: list[Claim] = []
    used: set[tuple[int, int | None]] = set()
    cues_used: set[str] = set()
    skipped: list[str] = []
    for ratios in (False, True):
        token = _tokenised(text, figs, ratios)

        def add(name: str, m: re.Match[str], up: bool, a: int, b: int | None, word: str) -> None:
            claims.append(Claim(name, "gt" if up else "lt", a, b, word, (m.start(), m.end()), token[m.start():m.end()]))
            used.add((a, b))
            cues_used.add(word.lower())

        for name, rx in _PATTERNS:
            for m in rx.finditer(token):
                a, b = int(m.group("a")), int(m.group("b"))
                if (a, b) in used or a == b:
                    continue
                fa, fb = figs[a], figs[b]
                if _class(fa.unit) != _class(fb.unit) or fa.unit.startswith("currency") and fa.unit != fb.unit:
                    continue  # not the same kind of quantity, so there is nothing to compare
                if _SIGN_AMBIGUOUS.search(_sentence(token, m)):
                    skipped.append(f"'{m.group('v')}' in a sentence about a loss or deficit: the sign convention is not stated")
                    cues_used.add(m.group("v").lower())
                    continue
                word = m.group("v")
                up = bool(re.match(_ABOVE + "$", word, re.I)) if name == "figure_compared" else bool(_UP_WORDS.match(word))
                add(name, m, up, a, b, word)
        for rx in (_RANK_BEFORE, _RANK_AFTER):
            for m in rx.finditer(token):
                a = int(m.group("a"))
                if any(c.pattern == "rank" and c.a == a for c in claims):
                    continue
                cue = m.group("c").lower()
                claims.append(Claim("rank", "max" if re.match(_HIGH + "$", cue, re.I) else "min", a, None, cue, (m.start(), m.end()), token[m.start():m.end()]))
                cues_used.add(cue)
        for name, rx in _UNANCHORED:
            for m in rx.finditer(token):
                a = int(m.group("a"))
                if any(c.a == a or c.b == a for c in claims) or _SIGN_AMBIGUOUS.search(_sentence(token, m)):
                    continue
                word = m.group("v")
                add(name, m, bool(_UP_WORDS.match(word)), a, None, word)
    token = _tokenised(text, figs, False)
    for m in _CUE.finditer(token):
        w = m.group(0).lower()
        if w in cues_used or w in ("up", "down", "more", "less") or w == "growth":
            continue
        if w == "fell" and token[m.end():m.end() + 7].strip().startswith("short"):
            continue
        if re.match(r"\s*(?:of|by)?\s*[⟪⟦]", token[m.end():m.end() + 14]):
            continue  # "an increase of 8%" states an amount; the calculation layer checks it
        if figs:
            skipped.append(f"'{w}' was seen but the sentence did not match any claim pattern")
    return Reading(tuple(claims), tuple(dict.fromkeys(skipped)))


def holds(claim: Claim, values: list[float]) -> bool | None:
    """Is the claim true if the figures read `values` (index-aligned with the figures of the sentence)? None when it cannot be told."""
    if claim.b is None:
        return None
    a, b = values[claim.a], values[claim.b]
    if claim.relation == "gt":
        return a > b
    if claim.relation == "lt":
        return a < b
    return None


def rank_holds(value: float, peers: list[float], relation: str) -> bool:
    """A record-high claim holds when no peer is higher; a record-low claim when no peer is lower. A tie keeps the claim true."""
    return all(value >= p for p in peers) if relation == "max" else all(value <= p for p in peers)
