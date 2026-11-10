"""Cells that print a dash for nothing, and the figure that may now belong in them.

A statement prints a dash where a line was nil. A dash is not a figure, so it is never linked and a refresh leaves it alone, yet the workbook cell
behind it can become a number next period. This looks at every dash beside linked figures of its row, finds the workbook cells of that figure's own
column group in the same row that hold a value the row does not already show, and, when exactly one remains, says so. It only ever lists; it writes nothing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..ooxml.xlsx import SourceCell
from .periods import parse_period

if TYPE_CHECKING:
    from ..project import Project, Tie


def heading_key(labels) -> tuple:
    """Headings compared without footnote marks, case or spacing: "Agriculture(i)" this year is "Agriculture" next year."""
    return tuple(re.sub(r"\s+", " ", re.sub(r"\s*\((?:[ivxlc]+|[a-z]|\d{1,2})\)\s*$", "", x.strip().lower())) for x in labels)


_NOTE_REF = re.compile(r"\d{1,2}(?:\.\d{1,2})+[a-z]?(?:\([a-z]\))?")


def without_note_refs(labels) -> tuple:
    """Row headings without the note numbers a statement prints beside a line ("3.1.4"): the numbers are renumbered between years, the wording stays."""
    kept = tuple(x for x in labels if not _NOTE_REF.fullmatch(x.strip()))
    return kept or tuple(labels)


def group_of(cell: SourceCell) -> tuple:
    """A cell's headings apart from any period: the two year columns of one group share it, the columns of another group do not."""
    return heading_key(x for x in (*cell.row_labels, *cell.col_labels) if parse_period(x) is None)


def nil_notes(project: Project, docs: dict[str, object], ties: list[Tie], source_of: Callable[[Tie], SourceCell | None], cells: list[SourceCell]) -> list[str]:
    by_row: dict[tuple, list[SourceCell]] = defaultdict(list)
    for c in cells:
        if not c.hidden and not c.is_date:
            by_row[(c.file, c.sheet, c.row)].append(c)
    out: list[str] = []
    for rel, doc in docs.items():
        nil_cells = getattr(doc, "nil_cells", None)
        if nil_cells is None:
            continue
        nils = list(nil_cells())
        if not nils:
            continue
        dms = {}
        for d in doc.mentions():
            dms[project._mkey(d)] = d
            dms.setdefault(project._mkey(d, f"#{d.slide}"), d)
        row_ties: dict[tuple, list[tuple[int, SourceCell]]] = defaultdict(list)
        for t in ties:
            if t.deck != rel or t.kind != "text" or t.state not in ("accepted", "confirmed"):
                continue
            dm = dms.get(project._tkey(t))
            src = source_of(t)
            if dm is None or dm.cell is None or src is None:
                continue
            row_ties[(project._table_id(dm), dm.cell[0])].append((dm.cell[1], src))
        for nil in nils:
            siblings = row_ties.get(((nil.slide_uid or f"#{nil.slide}", 0, nil.table), nil.row))
            if not siblings:
                continue
            near = sorted(siblings, key=lambda s: abs(s[0] - nil.col))
            if abs(near[0][0] - nil.col) != 1 or (len(near) > 1 and abs(near[1][0] - nil.col) == 1 and group_of(near[1][1]) != group_of(near[0][1])):
                continue  # the dash is not in the group of exactly one linked neighbour
            anchor = near[0][1]
            group = group_of(anchor)
            shown = [c.value for _, c in siblings if group_of(c) == group]
            candidates = [c for c in by_row[(anchor.file, anchor.sheet, anchor.row)]
                          if c is not anchor and group_of(c) == group and abs(c.value) > 0 and not any(abs(c.value - v) <= 1e-9 * max(1.0, abs(v)) for v in shown)]
            if len(candidates) != 1:
                continue
            c = candidates[0]
            name = nil.row_head.strip()[:50]
            heads = " / ".join(dict.fromkeys((*c.row_labels, *c.col_labels)))[:60]
            out.append(f"{rel}: the '{nil.mark}' beside '{name}' may now hold a figure: {heads} is {c.value:,.6g} in {c.file}!{c.sheet}!{c.ref}. A dash is not a figure and is not updated by itself")
    return out
