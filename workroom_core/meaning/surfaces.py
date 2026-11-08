"""Places a number can hide that the editor does not rewrite: speaker notes, chart titles and labels, picture descriptions, and chart axes.

Two checks, both read-only:
  stale mentions   a number in those places that equals the old value of a cell this update changes, beside that cell's own words
  clipped charts   a chart whose axis limits are fixed by hand, so a new value would be drawn outside the plot
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterator

from lxml import etree

from ..match.numbers import consistent_with_source, parse_numbers
from ..ooxml.pptx import A_NS, C_NS, NS, P_NS, R_NS, Deck
from ..ooxml.xlsx import parse_xml, rels_for
from .decisions import Decisions
from .findings import Finding, mask_digits
from .periods import Period, find_periods

if TYPE_CHECKING:
    from ..project import Plan, Project

_STOP = {"total", "net", "the", "and", "for", "from", "with", "per", "number", "other", "income", "revenue"}


def _tokens(labels: tuple[str, ...]) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", " ".join(labels).lower()) if w not in _STOP or w in ("revenue", "income")}


def _paragraphs(root: etree._Element, ns_text: str) -> Iterator[str]:
    for p in root.iter("{%s}p" % A_NS):
        text = "".join(t.text or "" for t in p.iter("{%s}t" % A_NS))
        if text.strip():
            yield text


def _hidden_text(deck: Deck, slide_no: int) -> Iterator[tuple[str, str]]:
    """(where, text) for the notes, chart text and picture descriptions that belong to one slide."""
    part, root = deck._slide(slide_no)
    for nv in root.iter("{%s}cNvPr" % P_NS):
        for attr in ("descr", "title"):
            if (nv.get(attr) or "").strip():
                yield "a picture or shape description", nv.get(attr)
    for rid, (rtype, target) in rels_for(deck.pkg, part).items():
        if rtype.endswith("notesSlide"):
            for t in _paragraphs(parse_xml(deck.pkg.read(target)), ""):
                yield "the speaker notes", t
        elif rtype.endswith("chart"):
            croot = parse_xml(deck.pkg.read(target))
            for tag in ("title", "dLbls"):
                for el in croot.iter("{%s}%s" % (C_NS, tag)):
                    for t in _paragraphs(el, ""):
                        yield "a chart title or label", t


def stale_mentions(project: "Project", plan: "Plan", roll: dict | None = None) -> list[Finding]:
    from ..project import open_document

    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    now = {k: c.value for k, c in cells.items()}
    changed = []
    rolled = {it["id"]: it for it in (roll or {}).get("ties", [])}
    for t in project.ties():
        if t.kind in ("text", "chart", "derived") and t.state in ("accepted", "confirmed"):
            cell = cells.get((t.src_file, t.sheet, t.ref))
            if t.id in rolled:
                new = rolled[t.id]["new_value"]
            else:
                new = project._tie_value(t, now)
            if new is not None and cell is not None and new != t.linked_value:
                changed.append((t, cell, t.linked_value, new))
    if not changed:
        return []
    decided = Decisions(project.db)
    out: list[Finding] = []
    for path in project._files((".pptx",)):
        rel = project._rel(path)
        deck = Deck(plan.files.get(rel) or path.read_bytes())
        for slide_no in range(1, len(deck.slide_parts()) + 1):
            for where, text in _hidden_text(deck, slide_no):
                low = text.lower()
                for nm in parse_numbers(text):
                    if nm.unit == "plain" and nm.decimals == 0 and abs(nm.value) < 10:
                        continue
                    for t, cell, old, new in changed:
                        ok, _ = consistent_with_source(nm, old)
                        if not ok or consistent_with_source(nm, new)[0]:
                            continue
                        window = low[max(0, nm.start - 90):nm.end + 90]
                        if not any(tok in window for tok in _tokens(cell.row_labels + cell.col_labels)):
                            continue
                        label = " ".join(dict.fromkeys(cell.row_labels + cell.col_labels))[:60]
                        out.append(Finding(Decisions.key("stale", rel, where, mask_digits(text), nm.raw), "stale_mention", "medium", rel, slide_no, text[:200], text[:200],
                                           f"\"{nm.raw}\" in {where} still shows the old {label}",
                                           (f"Old value {format(old, ',.10g')}, new value {format(new, ',.10g')}; this text is not rewritten because it is not tied to the cell",)))
                        break
    return out


def clipped_charts(project: "Project", plan: "Plan") -> list[Finding]:
    out: list[Finding] = []
    for rel, data in plan.files.items():
        if not rel.lower().endswith(".pptx"):
            continue
        deck = Deck(data)
        for slide, _uid, shape_id, name in deck.chart_shapes():
            _, croot = deck._chart_part(slide, shape_id)
            if croot.xpath("./c:chart//c:grouping[@val='stacked' or @val='percentStacked']", namespaces=NS):
                continue
            ax = croot.xpath(".//c:valAx/c:scaling", namespaces=NS)
            if not ax:
                continue
            hi, lo = ax[0].find("{%s}max" % C_NS), ax[0].find("{%s}min" % C_NS)
            top = float(hi.get("val")) if hi is not None else None
            bottom = float(lo.get("val")) if lo is not None else None
            if top is None and bottom is None:
                continue
            for s in deck.chart_series(slide, shape_id):
                for cat, v in zip(s.categories, s.values):
                    if v is None:
                        continue
                    if (top is not None and v > top) or (bottom is not None and v < bottom):
                        bound = f"maximum {format(top, ',.10g')}" if top is not None and v > top else f"minimum {format(bottom, ',.10g')}"
                        out.append(Finding(Decisions.key("axis", rel, slide, shape_id, cat), "chart_axis_clipped", "high", rel, slide, name, name,
                                           f"The chart \"{name}\" has its axis fixed at {bound}, so {cat or 'a point'} ({format(v, ',.10g')}) would be drawn outside it",
                                           ("Axis limits set by hand do not follow the data; change them in PowerPoint or reset the axis to automatic",)))
    return out


def stale_period_words(project: "Project", plan: "Plan", roll: dict | None) -> list[Finding]:
    """After a roll: a period word in speaker notes, chart text or a picture description that still names a period the roll has left behind."""
    if not roll or not roll.get("ties"):
        return []
    out: list[Finding] = []
    for path in project._files((".pptx",)):
        rel = project._rel(path)
        olds = {Period(it["period"][0], it["period"][1]) for it in roll["ties"] if it["deck"] == rel and it.get("period")}
        if not olds:
            continue
        deck = Deck(plan.files.get(rel) or path.read_bytes())
        for slide_no in range(1, len(deck.slide_parts()) + 1):
            for where, text in _hidden_text(deck, slide_no):
                for _a, _b, p in find_periods(text):
                    if p in olds:
                        word = text[_a:_b]
                        out.append(Finding(Decisions.key("stale_period", rel, where, mask_digits(text), word), "stale_period", "medium", rel, slide_no, text[:200], text[:200],
                                           f"\"{word}\" in {where} still names the period this release moves on from",
                                           ("Workroom advances period words in slide text and tables, not in notes, chart text or picture descriptions; change this one yourself",)))
                        break
    return out
