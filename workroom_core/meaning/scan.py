"""Find the calculated numbers in a project's documents and turn an accepted one into a tie that follows its sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..match.numbers import format_like
from .calc import Calc, Operand, direction_cue, explain
from .decisions import Decisions
from .timeline import Timeline

if TYPE_CHECKING:
    from ..project import Project

KIND = "calc"


@dataclass(frozen=True)
class Candidate:
    id: str
    deck: str
    slide: int
    where_slide_uid: str
    raw: str
    sentence: str
    scope: str
    certainty: str  # certain | ask
    reason: str
    options: tuple[Calc, ...]
    position: tuple = field(default=())  # (slide_uid, shape_id, para, seg, offset, cell)


@dataclass(frozen=True)
class Scan:
    candidates: list[Candidate]
    explained_by_tie: int
    unexplained: list[dict[str, Any]]  # percent figures beside no tied number that no calculation reproduces: not checked
    dismissed: int


def _operands(project: "Project", ties: list, cells: dict, tl: Timeline) -> list[Operand]:
    out: list[Operand] = []
    for t in ties:
        c = cells.get((t.src_file, t.sheet, t.ref))
        if c is None:
            continue
        label = " ".join(dict.fromkeys(c.row_labels + c.col_labels))[:70]
        out.append(Operand(t.src_file, t.sheet, t.ref, c.value, label, t.transform))
        for role, other in (("previous", tl.previous(c)), ("year_ago", tl.year_ago(c))):
            if other is not None:
                out.append(Operand(other.file, other.sheet, other.ref, other.value, " ".join(dict.fromkeys(other.row_labels + other.col_labels))[:70], t.transform, role))
    return out


def _worth_explaining(number) -> bool:
    if number.unit == "plain" and number.decimals == 0 and (abs(number.value) < 10 or 1900 <= abs(number.value) <= 2100):
        return False  # a bare small integer is a count, a page or a year
    return True


def find_calculations(project: "Project") -> Scan:
    from ..project import DECK_EXT, open_document

    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    tl = Timeline(index.cells)
    decisions = Decisions(project.db)
    ties = [t for t in project.ties() if t.kind in ("text", "derived", "chart")]
    tied_at: dict[tuple, Any] = {}
    for t in ties:
        if t.kind in ("text", "derived"):
            tied_at[project._tkey(t)] = t
    out: list[Candidate] = []
    unexplained: list[dict[str, Any]] = []
    dismissed = explained = 0
    for path in project._files(DECK_EXT):
        rel = project._rel(path)
        try:
            doc = open_document(path.read_bytes(), path.name)
            mentions = list(doc.mentions())
        except Exception:  # noqa: BLE001  an unreadable file is reported by discovery, not here
            continue
        by_slide: dict[str, list] = {}
        by_para: dict[tuple, list] = {}
        for dm in mentions:
            uid = dm.slide_uid or f"#{dm.slide}"
            by_slide.setdefault(uid, []).append(dm)
            by_para.setdefault((uid, dm.shape_id, dm.para, dm.cell), []).append(dm)

        def tie_of(dm):
            return tied_at.get(project._mkey(dm)) or tied_at.get(project._mkey(dm, f"#{dm.slide}"))

        for dm in mentions:
            if tie_of(dm) is not None or not _worth_explaining(dm.number):
                continue
            uid = dm.slide_uid or f"#{dm.slide}"
            para_ties = [tie_of(d) for d in by_para[(uid, dm.shape_id, dm.para, dm.cell)] if tie_of(d) is not None]
            slide_ties = [tie_of(d) for d in by_slide[uid] if tie_of(d) is not None and tie_of(d) not in para_ties]
            if not para_ties and not slide_ties:
                continue
            text = dm.context[0] if dm.context else ""
            pos = dm.para_offset if dm.para_offset is not None else max(text.find(dm.number.raw), 0)
            cue = direction_cue(text, pos, pos + len(dm.number.raw))
            scope, found = explain(dm.number, _operands(project, para_ties, cells, tl), _operands(project, slide_ties, cells, tl), cue)
            if not found:
                if dm.number.unit == "percent":
                    unexplained.append({"deck": rel, "slide": dm.slide, "figure": dm.number.raw, "sentence": text[:160]})
                continue
            cid = Decisions.key(KIND, rel, uid, dm.shape_id, dm.para, dm.cell, dm.number.raw, sorted(c.formula for c in found))
            if decisions.get(cid) == "dismissed":
                dismissed += 1
                continue
            weak = dm.number.decimals == 0 and abs(dm.number.value) < 100 and not cue
            if len(found) > 1:
                certainty, reason = "ask", f"{len(found)} calculations give this figure; choose the one you meant"
            elif scope != "paragraph":
                certainty, reason = "ask", "the figures it uses are on the same slide but not in the same sentence"
            elif weak:
                certainty, reason = "ask", "a whole-number percentage can match by chance; check the formula"
            else:
                certainty, reason = "certain", "this one calculation reproduces the figure at the precision written"
            out.append(Candidate(cid, rel, dm.slide, uid, dm.number.raw, text[:200], scope, certainty, reason, tuple(found), (uid, dm.shape_id, dm.para, dm.seg, dm.offset, dm.cell)))
    return Scan(out, explained, unexplained, dismissed)


def accept_calculation(project: "Project", candidate_id: str, option: int = 0) -> int:
    scan = find_calculations(project)
    cand = next((c for c in scan.candidates if c.id == candidate_id), None)
    if cand is None:
        raise KeyError("that calculation is no longer offered; find calculations again")
    calc = cand.options[option]
    from ..project import open_document

    doc = open_document((project.root / cand.deck).read_bytes(), cand.deck)
    dm = next((d for d in doc.mentions() if (d.slide_uid or f"#{d.slide}", d.shape_id, d.para, d.seg, d.offset, d.cell) == cand.position), None)
    if dm is None:
        raise KeyError("the figure is no longer where it was found")
    first = calc.terms[0]
    project.db.execute(
        "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis, kind, formula)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cand.deck, dm.slide, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), dm.number.raw, "accepted", first.file, first.sheet, first.ref,
         calc.transform, calc.value, 1.0, dm.context[0] if dm.context else "", dm.slide_uid, project._fp_near(dm), "exact", "calculated", "derived", calc.formula))
    return int(project.db.execute("SELECT last_insert_rowid()").fetchone()[0])


def dismiss_calculation(project: "Project", candidate_id: str) -> None:
    Decisions(project.db).set(candidate_id, KIND, "dismissed")


def preview_text(calc: Calc, number, new_value: float) -> str:
    return format_like(number, new_value, calc.transform)
