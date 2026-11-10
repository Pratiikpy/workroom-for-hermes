"""Roll a report forward to the next reporting period: every tied figure moves to the same row's next column, period words follow.

The whole roll is one release for the owner to approve and to restore. It is refused, naming each figure, when any tied figure has no
value for the next period: a half-rolled document is worse than an unrolled one. Period words move only where a tied figure of that
period stands beside them (the same slide, or anywhere in a Word report; a slide with no figures at all follows the deck), and a
word that cannot be moved is listed, not left to be found later.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..match.numbers import consistent_with_source, format_like, house_of, parse_numbers
from .nilcells import heading_key as _heading_key
from .nilcells import nil_notes, without_note_refs
from .calc import evaluate
from .periods import Period, describe_period, find_periods, parse_period, period_label
from .timeline import Timeline

if TYPE_CHECKING:
    from ..project import Impact, Project


@dataclass
class RollPlan:
    steps: int
    kind: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    labels: list[dict[str, Any]] = field(default_factory=list)
    turned: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    not_rolled: list[str] = field(default_factory=list)
    why: dict[int, tuple[str, str]] = field(default_factory=dict)  # tie id -> (code, sentence): what the roll did with each tied figure
    nil_cells: list[str] = field(default_factory=list)  # dashes that may now hold a figure
    restated: list[str] = field(default_factory=list)  # a figure for a period the report already showed, which the workbook now gives differently
    files: dict[str, bytes] = field(default_factory=dict)
    impacts: list[Impact] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        return {"steps": self.steps, "kind": self.kind, "ties": self.items, "labels": self.labels, "turned": self.turned, "restated": self.restated, "nil_cells": self.nil_cells}


def plan_rollforward(project: Project, steps: int = 1, window: bool = False) -> RollPlan:
    from ..project import Impact, open_document

    plan = RollPlan(steps)
    plan.notes = project.relocate_sources()
    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    tl = Timeline(index.cells)
    values = {k: c.value for k, c in cells.items()}
    ties = [t for t in project.ties() if t.state in ("accepted", "confirmed", "held") and t.kind in ("text", "derived", "chart")]
    ties = [t for t in ties if (project.root / t.deck).is_file()]  # a document that is put away keeps its links but is not part of the roll, and cannot block it

    # where each tied figure sits in its document (table and row), read once: pairs a row's year columns now and checks them afterwards
    row_of: dict[int, tuple] = {}
    docs_seen: dict[str, Any] = {}
    for rel in sorted({t.deck for t in ties}):
        if rel.lower().endswith(".scene.json"):
            continue
        docs_seen[rel] = open_document((project.root / rel).read_bytes(), rel)
        pre = {}
        for d in docs_seen[rel].mentions():
            pre[project._mkey(d)] = d
            pre.setdefault(project._mkey(d, f"#{d.slide}"), d)
        for t in ties:
            if t.deck == rel and t.kind == "text":
                d0 = pre.get(project._tkey(t))
                if d0 is not None and d0.cell is not None:
                    row_of[t.id] = (rel, project._table_id(d0), d0.cell[0])

    def group_of(t) -> tuple:
        """The headings of a figure's cell apart from the period one: two year columns of one group share it, the columns of another group do not."""
        try:
            labels = json.loads(t.intent_labels or t.src_labels or "[[], []]")
        except ValueError:
            return ()
        return tuple(x for axis in labels[:2] for x in axis if parse_period(x) is None)

    by_row_group: dict[tuple, list] = {}
    for t in ties:
        if t.id in row_of:
            by_row_group.setdefault(row_of[t.id] + (group_of(t),), []).append(t)

    def heading_key(labels) -> tuple:
        """Headings as a set: the order a sheet prints its header rows in differs between years."""
        return tuple(sorted(_heading_key(labels)))

    by_labels: dict[tuple, list] = {}
    by_labels_loose: dict[tuple, list] = {}
    for c in index.cells:
        by_labels.setdefault((c.file, c.sheet, heading_key(c.row_labels), heading_key(c.col_labels)), []).append(c)
        by_labels_loose.setdefault((c.file, c.sheet, heading_key(without_note_refs(c.row_labels)), heading_key(c.col_labels)), []).append(c)

    def intent(t):
        """(period, labels moved by ``steps``, the cell that now carries them) for a figure inherited from a model report, else None."""
        if not (window and t.intent_labels):
            return None
        try:
            rows, cols = json.loads(t.intent_labels)
        except ValueError:
            return None
        found = [(axis, i, p) for axis, labels in ((0, rows), (1, cols)) for i, x in enumerate(labels) if (p := parse_period(x)) is not None]
        if len(found) != 1:
            return None
        axis, i, p = found[0]
        groups = [list(rows), list(cols)]
        try:
            groups[axis][i] = period_label(p.shifted(steps), groups[axis][i])
        except ValueError:
            return None
        hits = by_labels.get((t.src_file, t.sheet, heading_key(groups[0]), heading_key(groups[1])), [])
        if len(hits) != 1:  # note numbers move between years ("3.1.4" one year, "3.1.5" the next): the wording of the row decides
            loose = by_labels_loose.get((t.src_file, t.sheet, heading_key(without_note_refs(groups[0])), heading_key(groups[1])), [])
            hits = loose if len(loose) == 1 else hits
        if len(hits) != 1 and steps == 1:
            pinned = anchored(t, p, rows)
            hits = [pinned] if pinned is not None else hits
        return p, groups, (hits[0] if len(hits) == 1 else None)

    def tie_period(t):
        if not t.intent_labels:
            return None
        try:
            rows_, cols_ = json.loads(t.intent_labels)
        except ValueError:
            return None
        found_ = [parse_period(x) for x in (*rows_, *cols_) if parse_period(x) is not None]
        return found_[0] if len(found_) == 1 else None

    anchor_memo: dict[int, Any] = {}

    def anchored(t, p, rows):
        """The next period's cell for a figure whose headings no longer match, found by value: the report already gave the next period's figure beside it (last year's
        current column is this year's comparative), so the cell of the new workbook that holds that very figure, under the same row wording, is the one; its partner
        column then follows by one period. Needs a unique match; otherwise nothing is guessed."""
        if t.id in anchor_memo:
            return anchor_memo[t.id]
        anchor_memo[t.id] = None
        key = row_of.get(t.id)
        if key is None:
            return None
        mates = [x for x in by_row_group.get(key + (group_of(t),), []) if x.id != t.id]
        row_key = heading_key(without_note_refs(rows))
        found = None
        newer = [x for x in mates if tie_period(x) == p.shifted(1) and x.linked_value is not None]
        older = [x for x in mates if tie_period(x) == p.shifted(-1)]
        if newer:
            want = newer[0].linked_value
            cands = [c for c in index.cells if c.file == t.src_file and c.sheet == t.sheet and not c.hidden and abs(c.value - want) <= 1e-9 * max(1.0, abs(want))
                     and (pl := tl.placed(c)) is not None and pl.period == p.shifted(1) and heading_key(without_note_refs(c.row_labels)) == row_key]
            found = cands[0] if len(cands) == 1 else None
        elif older:
            try:
                a_rows = json.loads(older[0].intent_labels)[0]
            except (ValueError, IndexError):
                a_rows = rows
            partner = anchored(older[0], p.shifted(-1), a_rows)
            found = tl.shifted(partner, 1) if partner is not None else None
        anchor_memo[t.id] = found
        return found

    def placed_of(t):
        if window and t.intent_labels and t.kind == "text":
            got = intent(t)
            if got is not None:
                p, _g, tgt = got
                return (tgt if tgt is not None else cells.get((t.src_file, t.sheet, t.ref))), type("Placed", (), {"period": p})()
        c = cells.get((t.src_file, t.sheet, t.ref))
        return (c, tl.placed(c)) if c is not None else (None, None)

    kinds: Counter[str] = Counter()
    for t in ties:
        if t.kind == "text" and t.state != "held":
            _, pl = placed_of(t)
            if pl is not None:
                kinds[pl.period.kind] += 1
    if not kinds:
        plan.blocked.append("none of the tied figures sits under a period heading or beside a period label, so there is no next period to roll to")
        return plan
    plan.kind = max(kinds, key=lambda k: (kinds[k], k == "q"))
    rolled: dict[int, dict[str, Any]] = {}
    period_of: dict[int, Period] = {}
    old_periods: dict[tuple[str, int], set[Period]] = {}
    deck_periods: dict[str, set[Period]] = {}
    unrolled_paras: set[tuple] = set()  # paragraphs whose figures could not be rolled
    rolled_paras: set[tuple] = set()  # paragraphs where at least one figure was rolled (their period words move with them)
    for t in ties:
        where = f"{t.deck} slide {t.slide}"
        if t.state == "held":
            plan.not_rolled.append(f"{where}: '{t.raw}' was changed by hand and stays as it is")
            plan.why[t.id] = ("held_by_hand", f"{where}: '{t.raw}' was changed by hand and stays as it is")
            unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
            continue
        if t.kind == "chart":
            plan.not_rolled.append(f"{where}: the chart point '{t.raw}' belongs to a chart with a fixed set of periods; change the chart's periods in PowerPoint")
            plan.why[t.id] = ("chart", f"{where}: the chart point '{t.raw}' belongs to a chart with a fixed set of periods; change the chart's periods in PowerPoint")
            unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
            continue
        if t.kind == "text" and window and t.intent_labels and intent(t) is None:
            plan.kept.append(f"{where}: '{t.raw}' has no single period in the headings it was linked under (or none), so a window refresh cannot move it and leaves it as written")
            plan.why[t.id] = ("no_single_period", f"{where}: '{t.raw}' has no single period in the headings it was linked under (or none), so a window refresh cannot move it and leaves it as written")
            continue
        if t.kind == "text" and window and not t.intent_labels:
            plan.kept.append(f"{where}: '{t.raw}' was linked here by its value, not inherited from the model report, so a window refresh leaves it as written")
            plan.why[t.id] = ("linked_by_value", f"{where}: '{t.raw}' was linked here by its value, not inherited from the model report, so a window refresh leaves it as written")
            continue
        if t.kind == "text":
            c, pl = placed_of(t)
            if pl is None or pl.period.kind != plan.kind:
                plan.kept.append(f"{where}: '{t.raw}' does not sit in a {plan.kind} period and is kept")
                plan.why[t.id] = ("not_a_period_figure", f"{where}: '{t.raw}' does not sit in a {plan.kind} period and is kept")
                continue
            got = intent(t)
            tgt = got[2] if got is not None else tl.shifted(c, plan.steps)
            if tgt is None:
                labels = " ".join(dict.fromkeys(c.row_labels + c.col_labels)) if c is not None else " ".join(json.loads(t.intent_labels)[0] + json.loads(t.intent_labels)[1])
                why = f"{where}: '{t.raw}' ({labels[:50]}) has no {describe_period(pl.period.shifted(plan.steps))} value in {t.src_file}"
                if window and got is not None:
                    # a copy of last period's report can quote periods the new workbook no longer holds; those figures keep their old numbers, and the release says so
                    plan.not_rolled.append(why + "; it keeps the figure as written")
                    plan.why[t.id] = ("new_period_missing", why + "; it keeps the figure as written")
                    unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
                    continue
                plan.blocked.append(why)
                continue
            rolled[t.id] = {"id": t.id, "deck": t.deck, "slide": t.slide, "raw": t.raw, "from": [t.src_file, t.sheet, t.ref], "to": [tgt.file, tgt.sheet, tgt.ref],
                            "old_value": t.linked_value, "new_value": tgt.value, "old_formula": "", "new_formula": "", "period": [pl.period.kind, pl.period.index]}
            period_of[t.id] = pl.period
            plan.why[t.id] = ("rolled", f"{where}: '{t.raw}' moves to {describe_period(pl.period.shifted(plan.steps))}")
            rolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
            old_periods.setdefault((t.deck, t.slide), set()).add(pl.period)
            deck_periods.setdefault(t.deck, set()).add(pl.period)
        else:
            f = json.loads(t.formula)
            terms, ok = [], True
            for term in f["terms"]:
                c = cells.get(tuple(term))
                pl = tl.placed(c) if c is not None else None
                if pl is None or pl.period.kind != plan.kind:
                    terms.append(term)
                    continue
                tgt = tl.shifted(c, plan.steps)
                if tgt is None:
                    plan.blocked.append(f"{where}: the calculated '{t.raw}' needs {' '.join(dict.fromkeys(c.row_labels + c.col_labels))[:50]} for {describe_period(pl.period.shifted(plan.steps))}, which {c.file} does not have")
                    ok = False
                    break
                terms.append([tgt.file, tgt.sheet, tgt.ref])
            if not ok:
                continue
            new_formula = json.dumps({**{k: v for k, v in f.items() if k != "labels"}, "terms": terms})
            nv = evaluate(new_formula, values)
            if nv is None:
                plan.blocked.append(f"{where}: the calculated '{t.raw}' cannot be made for the next period")
                continue
            if not project._sign_fits(t, nv):
                plan.not_rolled.append(f"{where}: the calculated '{t.raw}' would turn the other way next period, so the words beside it need your decision; it was not changed")
                plan.turned.append({"id": t.id, "old": t.linked_value, "new": nv})
                unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
                continue
            rolled[t.id] = {"id": t.id, "deck": t.deck, "slide": t.slide, "raw": t.raw, "from": [t.src_file, t.sheet, t.ref], "to": list(terms[0]),
                            "old_value": t.linked_value, "new_value": nv, "old_formula": t.formula, "new_formula": new_formula, "period": []}
    if plan.blocked:
        return plan
    # ---- write the new figures and period words into new copies of the documents ----
    by_tie = {t.id: t for t in ties}
    for rel in sorted({it["deck"] for it in rolled.values()} | {d for d in {t.deck for t in ties}}):
        path = project.root / rel
        if not path.is_file() or rel.lower().endswith(".scene.json"):
            continue
        doc = open_document(path.read_bytes(), rel)
        dms = {}
        for d in doc.mentions():
            dms[project._mkey(d)] = d
            dms.setdefault(project._mkey(d, f"#{d.slide}"), d)
        applied = 0
        mine = [by_tie[i] for i, it in rolled.items() if it["deck"] == rel]
        for t in sorted(mine, key=lambda t: (t.slide, t.shape_id, t.para, t.seg, -t.offset)):
            it = rolled[t.id]
            dm = dms.get(project._tkey(t))
            if dm is None or dm.number.raw != t.raw:
                plan.blocked.append(f"{rel} slide {t.slide}: '{t.raw}' is no longer where it was linked; discover again before rolling forward")
                continue
            shown = project._display_value(t, it["new_value"])
            new_text = format_like(dm.number, shown, t.transform, house_of(doc))
            ok, _ = consistent_with_source(_reparse(new_text), shown)
            if not ok:
                plan.blocked.append(f"{rel} slide {t.slide}: could not write {it['new_value']} as '{new_text}' faithfully")
                continue
            it["new_text"] = new_text
            if new_text != t.raw:
                project._edit_number(doc, dm, new_text)
                applied += 1
                plan.impacts.append(Impact(rel, t.slide, t.raw, new_text, f"{it['to'][0]}!{it['to'][1]}!{it['to'][2]}", t.linked_value, it["new_value"]))
        # period words
        slide_has_ties = {s for (d, s) in old_periods if d == rel}
        paragraphs = list(doc.paragraphs())
        edits: list[tuple[int, int, int, Any, str, str, int, int]] = []
        skipped_slides: set[tuple] = set()
        for slide, shape_id, para, cell, text in paragraphs:
            seen: Counter[str] = Counter()
            found_here = find_periods(text)
            bare = text.strip()
            if not found_here and re.fullmatch(r"(?:19|20)\d{2}", bare):  # a cell that holds only a year is a column heading in a table of years
                found_here = [(text.index(bare), text.index(bare) + len(bare), Period("y", int(bare)))]
            for a, b, p in found_here:
                word = text[a:b]
                occurrence = seen[word]
                seen[word] += 1
                if p.kind != plan.kind:
                    continue
                if rel.lower().endswith(".docx"):
                    allowed = deck_periods.get(rel, set())
                else:
                    allowed = old_periods.get((rel, slide), set()) if slide in slide_has_ties else deck_periods.get(rel, set())
                here = (rel, slide, shape_id, para, cell if not rel.lower().endswith(".docx") else None)
                if here in unrolled_paras and here not in rolled_paras:
                    if p in allowed and here not in skipped_slides:
                        skipped_slides.add(here)
                        plan.not_rolled.append(f"{rel} slide {slide}: a sentence's period words were not advanced because none of its figures could be rolled")
                    continue
                if p in allowed:
                    edits.append((slide, shape_id, para, cell, word, period_label(p.shifted(plan.steps), word), occurrence, a))
                elif p in deck_periods.get(rel, set()):
                    plan.not_rolled.append(f"{rel} slide {slide}: the period '{word}' stands on a slide whose figures show other periods, so it was not moved")
        for slide, shape_id, para, cell, old, new, occurrence, _ in sorted(edits, key=lambda e: (e[0], e[1], e[2], str(e[3]), -e[7])):
            try:
                doc.edit_label(slide, shape_id, para, cell, old, new, occurrence)
            except Exception as exc:  # noqa: BLE001  one label that cannot be moved is listed, not fatal
                plan.not_rolled.append(f"{rel} slide {slide}: '{old}' could not be moved ({exc})")
                continue
            applied += 1
            plan.labels.append({"deck": rel, "slide": slide, "old": old, "new": new})
            plan.impacts.append(Impact(rel, slide, old, new, "period label", 0.0, 0.0))
        if applied:
            data, _report = doc.serialize()
            plan.files[rel] = data
    # a figure for a period the report already showed (last year's column becoming this year's) must equal what the report said then, unless it was restated
    row_periods: dict[tuple, dict[Any, Any]] = {}
    for t in ties:
        if t.id in row_of:
            _c, pl = placed_of(t)
            if pl is not None:
                row_periods.setdefault(row_of[t.id] + (group_of(t),), {})[pl.period] = t
    for tid, it in rolled.items():
        if tid not in row_of or tid not in period_of:
            continue
        t0 = by_tie[tid]
        earlier = row_periods.get(row_of[tid] + (group_of(t0),), {}).get(period_of[tid].shifted(plan.steps))
        if earlier is None or earlier.id == tid:
            continue
        said, now = earlier.linked_value, it["new_value"]
        shown_before = parse_numbers(earlier.raw)
        resolution = 0.5 * 10 ** -(shown_before[0].decimals if shown_before else 0)
        if said is not None and now is not None and abs(project._display_value(earlier, said) - project._display_value(earlier, now)) >= resolution:
            plan.restated.append(f"{t0.deck} slide {t0.slide}: '{t0.raw}' becomes {describe_period(period_of[tid].shifted(plan.steps))}, which this report already gave as '{earlier.raw}'; the workbook now says {now:,.6g}. Restated, or a row that moved in the workbook: check before releasing")
    new_cell = {tid: next((c for c in index.cells if (c.file, c.sheet, c.ref) == tuple(it["to"])), None) for tid, it in rolled.items()}
    plan.nil_cells = nil_notes(project, docs_seen, ties, lambda t: new_cell.get(t.id) or cells.get((t.src_file, t.sheet, t.ref)), index.cells)
    if plan.blocked:
        plan.files.clear()
        plan.impacts.clear()
    plan.items = list(rolled.values())
    return plan


def _reparse(text: str):
    from ..match.numbers import parse_numbers

    found = parse_numbers(text)
    if len(found) != 1:
        raise ValueError(f"expected one number in {text!r}")
    return found[0]


def apply_rollforward(project: Project, meta: dict[str, Any]) -> None:
    """After a rolled release is published: each tie now points at the next period's cell and, for a calculation, its new formula."""
    for it in meta["ties"]:
        f, s, r = it["to"]
        project.db.execute("UPDATE ties SET src_file=?, sheet=?, ref=?, linked_value=?, formula=CASE WHEN ?<>'' THEN ? ELSE formula END, src_labels=NULL, intent_labels=NULL WHERE id=?",
                           (f, s, r, it["new_value"], it["new_formula"], it["new_formula"], it["id"]))
    project.relocate_sources()  # the ties learn the headings of the cells they now follow


def revert_rollforward(project: Project, meta: dict[str, Any]) -> dict[tuple[str, str, str], float]:
    """Point the ties back at the cells they had before the roll; returns the baseline values the restored documents show."""
    base: dict[tuple[str, str, str], float] = {}
    for it in meta["ties"]:
        f, s, r = it["from"]
        project.db.execute("UPDATE ties SET src_file=?, sheet=?, ref=?, linked_value=?, formula=CASE WHEN ?<>'' THEN ? ELSE formula END, src_labels=NULL WHERE id=?",
                           (f, s, r, it["old_value"], it["old_formula"], it["old_formula"], it["id"]))
        if not it["old_formula"]:
            base[(f, s, r)] = it["old_value"]
    project.relocate_sources()
    return base
