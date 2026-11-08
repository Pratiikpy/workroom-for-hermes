"""Where a source cell sits in time: its period, and the cells for the previous period and the same period a year earlier.

Time runs along columns (period headings across the top) or down rows (period labels in the first column); a cell whose labels
name no period, or two periods, has no timeline and nothing here guesses one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..ooxml.xlsx import SourceCell
from .periods import Period, parse_period


@dataclass(frozen=True)
class Placed:
    cell: SourceCell
    period: Period
    axis: str  # col: time runs across the columns of this row | row: time runs down the rows of this column


def _period_of(labels: tuple[str, ...]) -> Period | None:
    found = {p for p in (parse_period(x) for x in labels) if p is not None}
    return next(iter(found)) if len(found) == 1 else None


def place(cell: SourceCell) -> Placed | None:
    across, down = _period_of(cell.col_labels), _period_of(cell.row_labels)
    if (across is None) == (down is None):
        return None  # none, or two competing time axes
    return Placed(cell, across, "col") if across is not None else Placed(cell, down, "row")  # type: ignore[arg-type]


class Timeline:
    def __init__(self, cells: list[SourceCell]) -> None:
        self._series: dict[tuple, dict[Period, list[SourceCell]]] = defaultdict(lambda: defaultdict(list))
        self._placed: dict[tuple[str, str, str], Placed] = {}
        for c in cells:
            if c.is_date or c.hidden:
                continue
            p = place(c)
            if p is None:
                continue
            key = (c.file, c.sheet, p.axis, c.row if p.axis == "col" else c.col)
            self._series[key][p.period].append(c)
            self._placed[(c.file, c.sheet, c.ref)] = p

    def placed(self, cell: SourceCell) -> Placed | None:
        return self._placed.get((cell.file, cell.sheet, cell.ref))

    def _at(self, p: Placed, period: Period | None) -> SourceCell | None:
        if period is None:
            return None
        key = (p.cell.file, p.cell.sheet, p.axis, p.cell.row if p.axis == "col" else p.cell.col)
        hits = self._series.get(key, {}).get(period, [])
        return hits[0] if len(hits) == 1 else None  # two cells for one period is a conflict, not an answer

    def previous(self, cell: SourceCell) -> SourceCell | None:
        p = self.placed(cell)
        return self._at(p, p.period.previous) if p else None

    def year_ago(self, cell: SourceCell) -> SourceCell | None:
        p = self.placed(cell)
        return self._at(p, p.period.year_ago) if p else None

    def shifted(self, cell: SourceCell, n: int) -> SourceCell | None:
        """The cell of the same series n periods later (earlier when negative), or None when the series has no such period."""
        p = self.placed(cell)
        return self._at(p, p.period.shifted(n)) if p and p.period.kind != "ytd" else None

    def next(self, cell: SourceCell) -> SourceCell | None:
        p = self.placed(cell)
        return self._at(p, p.period.shifted(1)) if p and p.period.kind != "ytd" else None

    def history(self, cell: SourceCell) -> list[SourceCell]:
        """Every other cell of the same series that is not later than this one, oldest first (for "record" claims)."""
        p = self.placed(cell)
        if p is None:
            return []
        key = (cell.file, cell.sheet, p.axis, cell.row if p.axis == "col" else cell.col)
        out = [(per, cs[0]) for per, cs in self._series.get(key, {}).items() if len(cs) == 1 and per.kind == p.period.kind and per.index < p.period.index]
        return [c for _, c in sorted(out, key=lambda x: x[0].index)]
