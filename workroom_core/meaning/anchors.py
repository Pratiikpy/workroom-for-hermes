"""Keep each tie pointed at the cell it was made for, when the workbook around it is edited.

A cell address says where a number lives today; the row and column headings say what it is. When rows or columns are inserted or
removed, or a window of recent periods slides along, the address and the meaning part company. A tie remembers the headings of its
source cell and, every time the project is read, checks them:

  same headings at the same address        nothing to do
  same headings found at one other address the tie follows the cell (the move is reported)
  only a period heading changed            a "current period" slot was overwritten; the tie keeps its address (reported)
  anything else                            the tie goes back to "needs you" and says why; nothing is guessed

A source that cannot be read, or a cell that is gone, changes nothing here: the missing-source handling reports it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .periods import parse_period

if TYPE_CHECKING:
    from ..project import Project


def labels_of(cell) -> list[list[str]]:
    return [list(cell.row_labels), list(cell.col_labels)]


def clean_stored(stored):
    """Headings stored before placeholder cells (a dash, a dollar sign) stopped counting as headings: compare them as the reader now reads the same cell."""
    from ..ooxml.xlsx import is_label_text

    return None if stored is None else [[x for x in part if is_label_text(x)] for part in stored]


def label_key(cell) -> str:
    return json.dumps(labels_of(cell), ensure_ascii=False)


def _only_periods_differ(old: tuple[tuple[str, ...], tuple[str, ...]], new: tuple[tuple[str, ...], tuple[str, ...]]) -> bool:
    for a_group, b_group in zip(old, new):
        if len(a_group) != len(b_group):
            return False
        for a, b in zip(a_group, b_group):
            if a != b and not (parse_period(a) is not None and parse_period(b) is not None):
                return False
    return True


def _name(cell) -> str:
    return " ".join(dict.fromkeys(cell.row_labels + cell.col_labels))[:60]


def relocate_sources(project: Project) -> list[str]:
    """Check every tie's source against its remembered headings, follow cells that moved, and return what was done for the owner to read."""
    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    by_labels: dict[tuple, list] = {}
    for c in index.cells:
        by_labels.setdefault((c.file, c.sheet, tuple(c.row_labels), tuple(c.col_labels)), []).append(c)
    notes: list[str] = []
    sheets_with_numbers = {(c.file, c.sheet) for c in index.cells}
    by_file_labels: dict[tuple, list] = {}
    for c in index.cells:
        by_file_labels.setdefault((c.file, tuple(c.row_labels), tuple(c.col_labels)), []).append(c)

    def resolve(file: str, sheet: str, ref: str, stored) -> tuple[str, Any, str]:
        """(outcome, new cell or None, note): ok | moved | slot | needs_you | missing | learn"""
        cell = cells.get((file, sheet, ref))
        if stored is None:
            return ("learn", cell, "") if cell is not None else ("missing", None, "")
        want = (tuple(stored[0]), tuple(stored[1]))
        if cell is not None and (tuple(cell.row_labels), tuple(cell.col_labels)) == want:
            return "ok", cell, ""
        hits = by_labels.get((file, sheet) + want, [])
        if len(hits) == 1:
            return ("ok", hits[0], "") if hits[0].ref == ref else ("moved", hits[0], f"{_name(hits[0])} moved from {ref} to {hits[0].ref} in {file}; the tie followed it")
        if cell is None and (file, sheet) not in sheets_with_numbers:
            # the sheet itself is gone from the workbook: renamed (or its figures moved to another sheet). Follow it only when exactly one sheet carries the headings.
            elsewhere = by_file_labels.get((file,) + want, [])
            if len(elsewhere) == 1:
                return "moved", elsewhere[0], f"sheet {sheet} is now {elsewhere[0].sheet} in {file}; the tie followed it"
            if len(elsewhere) > 1:
                return "needs_you", None, f"sheet {sheet} is gone from {file} and {len(elsewhere)} other sheets carry its headings"
        if cell is None:
            return "missing", None, ""
        if len(hits) == 0 and _only_periods_differ(want, (tuple(cell.row_labels), tuple(cell.col_labels))):
            return "slot", cell, f"the period heading at {ref} in {file} changed from {' / '.join(want[0] + want[1])} to {' / '.join(cell.row_labels + cell.col_labels)}; the tie kept pointing at the same cell"
        why = "more than one cell has its old headings" if len(hits) > 1 else f"the headings at {ref} changed from {' / '.join(want[0] + want[1])} to {' / '.join(cell.row_labels + cell.col_labels)} and no other cell has them"
        return "needs_you", cell, why

    ties = project.ties()
    stored_here = {(t.src_file, t.sheet, tuple(clean_stored(json.loads(t.src_labels))[0]), tuple(clean_stored(json.loads(t.src_labels))[1])) for t in ties if t.src_labels and t.kind in ("text", "chart")}
    for t in ties:
        if t.kind == "scene":
            continue
        if t.intent_labels and getattr(project, "hold_carried", True):
            continue  # inherited from a model report: it follows its remembered headings only when a release is prepared or rolled
        if t.kind == "derived":
            try:
                f = json.loads(t.formula)
            except ValueError:
                continue
            stored_terms = f.get("labels")
            new_terms, new_labels, changed, problem = [], [], False, ""
            for k, term in enumerate(f["terms"]):
                stored = stored_terms[k] if stored_terms and k < len(stored_terms) else None
                outcome, cell, note = resolve(term[0], term[1], term[2], stored)
                if outcome == "missing":
                    new_terms.append(term)
                    new_labels.append(stored)
                    continue
                if outcome == "needs_you":
                    problem = note
                if outcome in ("moved", "slot", "learn", "ok") and cell is not None:
                    new_terms.append([cell.file, cell.sheet, cell.ref])
                    new_labels.append(labels_of(cell))
                    changed = changed or [cell.file, cell.sheet, cell.ref] != term or labels_of(cell) != stored
                    if outcome in ("moved", "slot"):
                        notes.append(note)
                else:
                    new_terms.append(term)
                    new_labels.append(stored or (labels_of(cell) if cell else None))
            if problem and t.state in ("accepted", "confirmed"):
                project.db.execute("UPDATE ties SET state='confirm', prior_state=?, held_note=? WHERE id=?", (t.state, problem, t.id))
                notes.append(f"'{t.raw}' needs you: {problem}")
            elif changed:
                f2 = {**f, "terms": new_terms, "labels": new_labels}
                project.db.execute("UPDATE ties SET formula=?, src_file=?, sheet=?, ref=? WHERE id=?", (json.dumps(f2), new_terms[0][0], new_terms[0][1], new_terms[0][2], t.id))
            continue
        stored = clean_stored(json.loads(t.src_labels)) if t.src_labels else None
        outcome, cell, note = resolve(t.src_file, t.sheet, t.ref, stored)
        if outcome == "learn":
            project.db.execute("UPDATE ties SET src_labels=? WHERE id=?", (json.dumps(labels_of(cell), ensure_ascii=False), t.id))
        elif outcome == "moved":
            project.db.execute("UPDATE ties SET ref=?, sheet=? WHERE id=?", (cell.ref, cell.sheet, t.id))
            notes.append(note)
        elif outcome == "slot":
            now_key = (t.src_file, t.sheet, tuple(cell.row_labels), tuple(cell.col_labels))
            if now_key in stored_here and now_key != (t.src_file, t.sheet, tuple(stored[0]), tuple(stored[1])):
                # another tie already follows the cell that now carries these headings, so this one's source has dropped out of the sheet
                project.db.execute("UPDATE ties SET state='skipped', prior_state=?, held_note=? WHERE id=?", (t.state, "its source is no longer in the workbook", t.id))
                notes.append(f"'{t.raw}' lost its source ({' / '.join(stored[0] + stored[1])} is no longer in {t.src_file}) and is left as written")
            else:
                project.db.execute("UPDATE ties SET src_labels=? WHERE id=?", (json.dumps(labels_of(cell), ensure_ascii=False), t.id))
                notes.append(note)
        elif outcome == "needs_you" and t.state in ("accepted", "confirmed"):
            project.db.execute("UPDATE ties SET state='confirm', prior_state=?, held_note=? WHERE id=?", (t.state, note, t.id))
            notes.append(f"'{t.raw}' needs you: {note}")
    return list(dict.fromkeys(notes))
