"""Roll a report forward to the next reporting period: every tied figure moves to the same row's next column, period words follow.

The whole roll is one release for the owner to approve and to restore. It is refused, naming each figure, when any tied figure has no
value for the next period: a half-rolled document is worse than an unrolled one. Period words move only where a tied figure of that
period stands beside them (the same slide, or anywhere in a Word report; a slide with no figures at all follows the deck), and a
word that cannot be moved is listed, not left to be found later.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..match.numbers import consistent_with_source, format_like
from .calc import evaluate
from .periods import Period, describe_period, find_periods, period_label
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
    files: dict[str, bytes] = field(default_factory=dict)
    impacts: list["Impact"] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        return {"steps": self.steps, "kind": self.kind, "ties": self.items, "labels": self.labels, "turned": self.turned}


def plan_rollforward(project: "Project", steps: int = 1) -> RollPlan:
    from ..project import DECK_EXT, Impact, open_document

    plan = RollPlan(steps)
    plan.notes = project.relocate_sources()
    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    tl = Timeline(index.cells)
    values = {k: c.value for k, c in cells.items()}
    ties = [t for t in project.ties() if t.state in ("accepted", "confirmed", "held") and t.kind in ("text", "derived", "chart")]

    def placed_of(t):
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
    old_periods: dict[tuple[str, int], set[Period]] = {}
    deck_periods: dict[str, set[Period]] = {}
    unrolled_paras: set[tuple] = set()  # paragraphs whose figures could not be rolled
    rolled_paras: set[tuple] = set()  # paragraphs where at least one figure was rolled (their period words move with them)
    for t in ties:
        where = f"{t.deck} slide {t.slide}"
        if t.state == "held":
            plan.not_rolled.append(f"{where}: '{t.raw}' was changed by hand and stays as it is")
            unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
            continue
        if t.kind == "chart":
            plan.not_rolled.append(f"{where}: the chart point '{t.raw}' belongs to a chart with a fixed set of periods; change the chart's periods in PowerPoint")
            unrolled_paras.add((t.deck, t.slide, t.shape_id, t.para, t.cell_rc))
            continue
        if t.kind == "text":
            c, pl = placed_of(t)
            if pl is None or pl.period.kind != plan.kind:
                plan.kept.append(f"{where}: '{t.raw}' does not sit in a {plan.kind} period and is kept")
                continue
            tgt = tl.shifted(c, plan.steps)
            if tgt is None:
                plan.blocked.append(f"{where}: '{t.raw}' ({' '.join(dict.fromkeys(c.row_labels + c.col_labels))[:50]}) has no {describe_period(pl.period.shifted(plan.steps))} value in {c.file}")
                continue
            rolled[t.id] = {"id": t.id, "deck": t.deck, "slide": t.slide, "raw": t.raw, "from": [t.src_file, t.sheet, t.ref], "to": [tgt.file, tgt.sheet, tgt.ref],
                            "old_value": t.linked_value, "new_value": tgt.value, "old_formula": "", "new_formula": "", "period": [pl.period.kind, pl.period.index]}
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
            new_text = format_like(dm.number, shown, t.transform)
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
            for a, b, p in find_periods(text):
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
        for slide, shape_id, para, cell, old, new, occurrence, a in sorted(edits, key=lambda e: (e[0], e[1], e[2], str(e[3]), -e[7])):
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


def apply_rollforward(project: "Project", meta: dict[str, Any]) -> None:
    """After a rolled release is published: each tie now points at the next period's cell and, for a calculation, its new formula."""
    for it in meta["ties"]:
        f, s, r = it["to"]
        project.db.execute("UPDATE ties SET src_file=?, sheet=?, ref=?, linked_value=?, formula=CASE WHEN ?<>'' THEN ? ELSE formula END, src_labels=NULL WHERE id=?",
                           (f, s, r, it["new_value"], it["new_formula"], it["new_formula"], it["id"]))
    project.relocate_sources()  # the ties learn the headings of the cells they now follow


def revert_rollforward(project: "Project", meta: dict[str, Any]) -> dict[tuple[str, str, str], float]:
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
