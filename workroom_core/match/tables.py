"""Table-level matching: a column of a report table that agrees, row by row, with one column of one source sheet verifies every cell of that column at once.

One number that equals a cell is weak evidence; five rows of one column that each equal the cell on the matching row of the same source column, under the same
row headings, are strong evidence. A cell is accepted this way only when

  * its row heading matches the heading of a source row (most words shared);
  * at least MIN_ROWS rows of its column agree with the same source column, with the same transform, and at least MIN_SHARE of the rows that have a source row;
  * no other source column agrees about as often (the alignment is unique);
  * the transform is exact or a percent written as a fraction (a thousand-fold scale is never accepted this way).

Cells whose own value does not agree stay as they were, so an exception in a verified column is never papered over.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..ooxml.pptx import DocMention
from .engine import MatchResult, Scored, SourceIndex, tokens
from .numbers import consistent_with_source

MIN_ROWS = 3
MIN_OPEN_ROWS = 2  # a column question is worth asking when at least this many of its figures are still waiting
MIN_SHARE = 0.75
ROW_OVERLAP = 0.6
RUNNER_RATIO = 0.5
TRANSFORMS = ("exact", "fraction_to_percent")
REASON = "table alignment"


class _Rows:
    """The source cells of every sheet by row, and an inverted index from heading words to rows."""

    def __init__(self, index: SourceIndex) -> None:
        self.cells: dict[tuple[str, str], dict[int, dict[int, object]]] = defaultdict(lambda: defaultdict(dict))
        for c in index.cells:
            self.cells[(c.file, c.sheet)][c.row][c.col] = c
        self.tokens: dict[tuple[str, str, int], frozenset[str]] = {}
        self.by_word: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for (f, s), rows in self.cells.items():
            for r, cols in rows.items():
                words = set()
                for c in cols.values():
                    words.update(w for w in tokens(" ".join(c.row_labels)) if _is_word(w))
                if not words:
                    continue
                key = (f, s, r)
                self.tokens[key] = frozenset(words)
                for w in words:
                    self.by_word[w].append(key)

    def candidates(self, heading: str) -> list[tuple[str, str, int]]:
        want = frozenset(w for w in tokens(heading) if _is_word(w))
        if not want:
            return []
        seen: set[tuple[str, str, int]] = set()
        for w in want:
            seen.update(self.by_word.get(w, ()))
        out = []
        for key in seen:
            have = self.tokens[key]
            if len(want & have) / len(want | have) >= ROW_OVERLAP:
                out.append(key)
        return out


def _is_word(w: str) -> bool:
    return len(w) >= 3 and w[0].isalpha()


def _rows_of(index: SourceIndex) -> _Rows:
    cached = getattr(index, "_table_rows", None)
    if cached is None:
        cached = _Rows(index)
        index._table_rows = cached  # type: ignore[attr-defined]
    return cached


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _tables_by_section(mentions: list[DocMention]) -> dict[str, list[int]]:
    found: dict[str, set[int]] = defaultdict(set)
    for m in mentions:
        if m.cell is not None:
            found[m.section].add(m.table)
    return {k: sorted(v) for k, v in found.items()}


def column_signature(mentions: list[DocMention], members: list[int], column: int, tables: dict[str, list[int]] | None = None) -> str:
    """A name for one column of one report table that survives the document being copied or its other tables being edited: the section the table
    sits under, which of that section's tables it is, and the column's position and heading."""
    first = mentions[members[0]]
    if first.shape_id:  # PowerPoint: the slide's own id and the shape
        base = f"{first.slide_uid or first.slide}/{first.shape_id}"
    else:
        same = (tables if tables is not None else _tables_by_section(mentions)).get(first.section, [])
        base = f"{_norm(first.section)}#{same.index(first.table) if first.table in same else 0}"
    head = next((mentions[i].col_head for i in members if mentions[i].cell and mentions[i].cell[1] == column and mentions[i].col_head), "")
    return f"{base}|{column}|{_norm(head)}"


def align_tables(mentions: list[DocMention], results: list[MatchResult], index: SourceIndex, chosen: dict[str, tuple[str, str, int]] | None = None,
                 questions: list[dict[str, Any]] | None = None) -> list[MatchResult]:
    """Results with every verified table cell accepted. Mentions and results are parallel lists; the lists passed in are not changed.

    ``chosen`` maps a column signature to the source column the owner picked for it; ``questions`` collects the columns that fit two or more source
    columns about equally, each with its alternatives, so the owner is asked once for the column and not once for every figure."""
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, m in enumerate(mentions):
        if m.cell is not None and m.row_head:
            groups[(m.slide, m.shape_id, m.table)].append(i)
    if not groups:
        return results
    rows = _rows_of(index)
    out = list(results)
    tables = _tables_by_section(mentions)
    for members in groups.values():
        by_cell: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i in members:
            by_cell[mentions[i].cell].append(i)
        singles = {rc: v[0] for rc, v in by_cell.items() if len(v) == 1 and rc[1] > 0}
        if len(singles) < MIN_ROWS:
            continue
        candidates = {r: rows.candidates(mentions[i].row_head) for (r, _c), i in singles.items()}
        columns: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for (r, c), i in singles.items():
            if candidates.get(r):
                columns[c].append((r, i))
        for column, items in columns.items():
            if len(items) < MIN_ROWS:
                continue
            sig = column_signature(mentions, members, column, tables)
            _verify_column(items, mentions, candidates, rows, out, chosen.get(sig) if chosen else None, questions, sig)
    return out


def _verify_column(items: list[tuple[int, int]], mentions: list[DocMention], candidates: dict[int, list], rows: _Rows, out: list[MatchResult],
                   picked: tuple[str, str, int] | None = None, questions: list[dict[str, Any]] | None = None, sig: str = "") -> None:
    votes: dict[tuple[tuple[str, str], int], dict[int, tuple[int, object, str, float]]] = defaultdict(dict)
    with_rows: dict[tuple[str, str], int] = defaultdict(int)
    for r, i in items:
        number = mentions[i].number
        per_sheet: dict[tuple[str, str], list[tuple[str, str, int]]] = defaultdict(list)
        for key in candidates[r]:
            per_sheet[(key[0], key[1])].append(key)
        for sheet, keys in per_sheet.items():
            with_rows[sheet] += 1
            hits: dict[int, list[tuple[object, str, float]]] = defaultdict(list)
            for key in keys:
                overlap = len(frozenset(w for w in tokens(mentions[i].row_head) if _is_word(w)) & rows.tokens[key]) / max(len(rows.tokens[key]), 1)
                for col, cell in rows.cells[sheet][key[2]].items():
                    ok, transform = consistent_with_source(number, cell.value)
                    if ok and transform in TRANSFORMS:
                        hits[col].append((cell, transform, overlap))
            for col, found in hits.items():
                if picked is not None and (sheet[0], sheet[1], col) == picked and len(found) > 1:
                    found = sorted(found, key=lambda f: -f[2])
                    found = found[:1] if found[0][2] > found[1][2] else []  # the owner chose the column; the row heading settles the row, or the row stays a question
                if len(found) == 1:  # two candidate rows agreeing at one column is an ambiguous row, not a vote
                    votes[(sheet, col)][i] = (i, found[0][0], found[0][1], found[0][2])
    ranked = sorted(votes.items(), key=lambda kv: -len(kv[1]))
    if not ranked:
        return
    if picked is not None:  # the owner said which source column this report column is: every row that agrees with it is accepted
        mine = next(((k, v) for k, v in ranked if (k[0][0], k[0][1], k[1]) == picked), None)
        if mine is None:
            return
        ranked = [mine] + [r for r in ranked if r is not mine]
    (sheet, col), best = ranked[0]
    n = len(best)
    if n < MIN_ROWS or n / max(with_rows[sheet], 1) < (MIN_SHARE if picked is None else 0.5):
        return
    if picked is None and len(ranked) > 1 and len(ranked[1][1]) > n * RUNNER_RATIO:
        if questions is not None:
            alternatives = [{"file": k[0][0], "sheet": k[0][1], "column": k[1], "agree": len(v)} for k, v in ranked[:4] if len(v) >= MIN_ROWS and len(v) >= n * RUNNER_RATIO]
            open_rows = [i for _, i in items if out[i].decision != "accept"]
            if len(alternatives) > 1 and len(open_rows) >= MIN_OPEN_ROWS:  # a column whose rows were all linked one by one needs no answer
                questions.append({"signature": sig, "rows": len(open_rows), "alternatives": alternatives, "figures": open_rows})
        return
    if len({v[2] for v in best.values()}) != 1:
        return
    why = f"{REASON}: {n} of the {with_rows[sheet]} rows of this column agree with column {col} of {sheet[1]}, row by row"
    for i, cell, transform, overlap in best.values():
        if out[i].decision == "accept":
            continue
        out[i] = MatchResult(out[i].mention, "accept", Scored(cell, transform, round(overlap, 3), False, 1.0), None, why, ())
