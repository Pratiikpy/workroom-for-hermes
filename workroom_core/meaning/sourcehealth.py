"""Source health: what the numbers a release is built from say about the workbook they came from, before anything is staged.

Two situations make a report wrong while every single edit looks fine, so each raises a high finding the owner must acknowledge:

  partial source   some figures tied to a workbook lost their cell while others are being updated from the same workbook: a region, a period
                   or a sheet is probably missing from the new file. The figures that lost their cell are left as they are, so the report
                   would mix new and old numbers.
  implausible move a source cell changed by two orders of magnitude or became zero: the usual signature of a unit or scale change, a paste
                   over the wrong range, or a cell that was cleared.

Nothing here rewrites or rejects a document; it states the evidence and names what was not checked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .decisions import Decisions
from .findings import Finding

if TYPE_CHECKING:
    from ..project import Plan, Project

RATIO_LIMIT = 100.0
EVIDENCE_LINES = 6


def _fmt(value: float) -> str:
    return format(value, ",.10g")


def partial_source(project: Project, plan: Plan) -> list[Finding]:
    cells = {(c.file, c.sheet, c.ref) for c in project.source_index().cells}
    uncalculated = getattr(project, "uncalculated_sources", {})
    ties = [t for t in project.ties(("accepted", "confirmed", "held")) if t.kind != "derived" and t.src_file]
    key_file = {f"{t.src_file}!{t.sheet}!{t.ref}": t.src_file for t in ties}
    updating: dict[str, int] = {}
    for i in plan.impacts:
        file = key_file.get(i.src)
        if file:
            updating[file] = updating.get(file, 0) + 1
    out: list[Finding] = []
    for file in sorted(updating):
        mine = [t for t in ties if t.src_file == file]
        gone = [t for t in mine if (t.src_file, t.sheet, t.ref) not in cells]
        if not gone or len(gone) == len(mine):
            continue  # nothing lost, or the whole workbook is gone (reported as missing sources)
        first = gone[0]
        evidence = [f"{t.deck} slide {t.slide}: \"{t.raw}\" was {t.sheet}!{t.ref}, which the workbook no longer has a number in" for t in gone[:EVIDENCE_LINES]]
        if len(gone) > EVIDENCE_LINES:
            evidence.append(f"and {len(gone) - EVIDENCE_LINES} more")
        if uncalculated.get(file):
            evidence.append(f"{file} holds {uncalculated[file]} formulas with no saved value: some of the missing cells may be formulas that were never calculated")
        out.append(Finding(
            Decisions.key("source_partial", file, *sorted(f"{t.sheet}!{t.ref}" for t in gone)), "source_incomplete", "high", first.deck, first.slide, first.context[:200], first.context[:200],
            f"{len(gone)} of {len(mine)} figures tied to {file} lost their source cell while {updating[file]} others are updated from it",
            tuple(evidence),
            "The new workbook may be missing a region, period or sheet. Those figures stay as they are, so the report would mix new and old numbers. Check the workbook before approving."))
    return out


def implausible_moves(project: Project, plan: Plan) -> list[Finding]:
    seen: dict[str, Finding] = {}
    for i in plan.impacts:
        old, new = i.old_value, i.new_value
        if i.src in seen or not old:
            continue
        ratio = abs(new / old)
        if new == 0:
            how = "became zero"
        elif ratio >= RATIO_LIMIT or ratio <= 1 / RATIO_LIMIT:
            how = f"changed by a factor of {ratio:,.4g}"
        else:
            continue
        seen[i.src] = Finding(
            Decisions.key("source_move", i.src, _fmt(old), _fmt(new)), "source_implausible", "high", i.deck, i.slide, i.old_text[:200], i.new_text[:200],
            f"The source cell {i.src.split('!', 1)[-1]} {how}: {_fmt(old)} to {_fmt(new)}",
            ("A move this large usually means a unit or scale change, a paste over the wrong range or a cleared cell, not a real result",),
            "Open the workbook and confirm the value before approving; the figures that follow it are listed in this release.")
    return list(seen.values())


def source_findings(project: Project, plan: Plan) -> list[Finding]:
    return partial_source(project, plan) + implausible_moves(project, plan)
