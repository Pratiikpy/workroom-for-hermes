"""Compare every changed sentence before and after an update and report the claims the update has made false."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .claims import Claim, figures_in, holds, rank_holds, read_claims
from .decisions import Decisions
from .findings import Finding, mask_digits, opposite_word, sort_findings
from .timeline import Timeline

if TYPE_CHECKING:
    from ..project import Plan, Project


@dataclass
class Coverage:
    sentences_checked: int = 0
    claims_read: int = 0
    not_checked: list[str] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        return {"sentences_checked": self.sentences_checked, "claims_read": self.claims_read, "not_checked": self.not_checked[:20], "not_checked_count": len(self.not_checked)}


def _group(mentions) -> dict[tuple, tuple[str, list]]:
    out: dict[tuple, tuple[str, list]] = {}
    for dm in mentions:
        key = (dm.slide_uid or f"#{dm.slide}", dm.shape_id, dm.para, dm.cell)
        text = dm.context[0] if dm.context else ""
        out.setdefault(key, (text, []))[1].append(dm)
    return out


def _num(v: float) -> str:
    return format(v, ",.10g")


def _tag(cell) -> str:
    return " ".join(dict.fromkeys(cell.col_labels + cell.row_labels))[:40]


def _fmt(values: list[float], claim: Claim) -> str:
    return " vs ".join(_num(values[i]) for i in (claim.a, claim.b) if i is not None)


def claim_findings(project: "Project", plan: "Plan") -> tuple[list[Finding], Coverage]:
    from ..project import is_scene, open_document

    index = project.source_index()
    cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
    tl = Timeline(index.cells)
    now = {k: c.value for k, c in cells.items()}
    then = {**now, **project.snapshot_values()}
    ties = project.ties()
    for t in ties:
        if t.kind != "derived" and (t.src_file, t.sheet, t.ref) in then:
            then[(t.src_file, t.sheet, t.ref)] = t.linked_value
    tied_at = {project._tkey(t): t for t in ties if t.kind in ("text", "derived") and t.state != "skipped"}
    decisions = Decisions(project.db)
    findings: list[Finding] = []
    cov = Coverage()

    def tie_for(dm):
        return tied_at.get(project._mkey(dm)) or tied_at.get(project._mkey(dm, f"#{dm.slide}"))

    def make(kind: str, severity: str, rel: str, slide: int, text_b: str, text_a: str, summary: str, evidence: list[str], claim: Claim | None = None, uid: str = "") -> Finding:
        sug = ""
        if claim and kind in ("claim_flip", "baseline_flip", "record_flip") and opposite_word(claim.cue):
            sug = f"The figures now say the opposite: consider \"{opposite_word(claim.cue)}\" in place of \"{claim.cue}\"."
        fid = Decisions.key(kind, rel, mask_digits(text_b), text_a)
        return Finding(fid, kind, severity, rel, slide, text_b, text_a, summary, tuple(evidence), sug)

    moved = {k for k in now if now[k] != then[k]}
    for rel in sorted({t.deck for t in ties if t.kind in ("text", "derived")}):
        if is_scene(rel) or not (project.root / rel).is_file():
            continue
        try:
            old = _group(open_document((project.root / rel).read_bytes(), rel).mentions())
            new = _group(open_document(plan.files[rel], rel).mentions()) if rel in plan.files else old
        except Exception:  # noqa: BLE001  the staged file is verified elsewhere
            continue
        for key, (text_b, mentions_b) in old.items():
            text_a, mentions_a = new.get(key, ("", []))
            if not text_a or len(mentions_a) != len(mentions_b) or not any(tie_for(d) for d in mentions_b):
                continue
            changed_text = text_a != text_b
            if not changed_text and not moved:
                continue
            figs_b, figs_a = figures_in(text_b), figures_in(text_a)
            if len(figs_b) != len(figs_a):
                cov.not_checked.append(f"{rel} slide {mentions_b[0].slide}: the number of figures changed in the sentence, so it was not compared")
                continue
            cov.sentences_checked += 1
            reading = read_claims(text_b, figs_b)
            cov.not_checked.extend(f"{rel} slide {mentions_b[0].slide}: {n}" for n in reading.not_checked)
            vb, va = [f.value for f in figs_b], [f.value for f in figs_a]
            by_start = {d.para_offset: d for d in mentions_b if d.para_offset is not None}
            slide = mentions_b[0].slide
            for claim in reading.claims:
                cov.claims_read += 1
                if claim.pattern in ("direction_from_to", "direction_to_from", "figure_direction_from", "figure_than", "figure_compared"):
                    if not changed_text:
                        continue
                    hb, ha = holds(claim, vb), holds(claim, va)
                    if hb and not ha:
                        findings.append(make("claim_flip", "high", rel, slide, text_b, text_a,
                                             f"\"{claim.text.strip()}\" was true and is not true after this update",
                                             [f"Before: {_fmt(vb, claim)} ({claim.cue})", f"After: {_fmt(va, claim)} (the words \"{claim.cue}\" no longer fit)"], claim))
                    elif not hb and not ha:
                        findings.append(make("claim_already_false", "info", rel, slide, text_b, text_a, f"\"{claim.text.strip()}\" did not hold before this update either", [f"Figures: {_fmt(vb, claim)}"], claim))
                    elif not hb and ha:
                        findings.append(make("claim_now_holds", "info", rel, slide, text_b, text_a, f"\"{claim.text.strip()}\" was false and now holds", [f"After: {_fmt(va, claim)}"], claim))
                    continue
                f = figs_b[claim.a]
                dm = by_start.get(f.start) or next((d for d in mentions_b if d.number.raw == f.raw), None)
                tie = tie_for(dm) if dm is not None else None
                cell = cells.get((tie.src_file, tie.sheet, tie.ref)) if tie is not None and tie.kind == "text" else None
                if cell is None:
                    cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" about {f.raw} was not checked because that figure is not tied to a source cell")
                    continue
                key = (cell.file, cell.sheet, cell.ref)
                if claim.pattern == "rank":
                    peers = tl.history(cell)
                    if len(peers) < 2:
                        cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" was not checked: the workbook holds too little history for {f.raw}")
                        continue
                    pb = rank_holds(then[key], [then[(c.file, c.sheet, c.ref)] for c in peers], claim.relation)
                    pa = rank_holds(now[key], [now[(c.file, c.sheet, c.ref)] for c in peers], claim.relation)
                    shown = [f"{_tag(cell)}: {_num(now[key])}; earlier: " + "; ".join(f"{_tag(c)} {_num(now[(c.file, c.sheet, c.ref)])}" for c in peers[-4:])]
                    if pb and not pa:
                        findings.append(make("record_flip", "high", rel, slide, text_b, text_a, f"\"{claim.cue}\" for {f.raw} is no longer true", shown, claim))
                    elif not pb and not pa:
                        findings.append(make("claim_already_false", "info", rel, slide, text_b, text_a, f"\"{claim.cue}\" for {f.raw} did not hold before this update either", shown, claim))
                    continue
                bases = [b for b in (tl.previous(cell), tl.year_ago(cell)) if b is not None]
                if not bases:
                    cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" about {f.raw} was not checked: no earlier period in the workbook to compare with")
                    continue
                cmp = (lambda a, b: a > b) if claim.relation == "gt" else (lambda a, b: a < b)
                hb = any(cmp(then[key], then[(b.file, b.sheet, b.ref)]) for b in bases)
                ha = any(cmp(now[key], now[(b.file, b.sheet, b.ref)]) for b in bases)
                if hb and not ha:
                    findings.append(make("baseline_flip", "medium", rel, slide, text_b, text_a, f"\"{claim.cue}\" about {f.raw} no longer holds against either earlier period",
                                         [f"{_tag(cell)}: {_num(now[key])}; " + "; ".join(f"{_tag(b)} {_num(now[(b.file, b.sheet, b.ref)])}" for b in bases)], claim))
    for t in ties:
        if t.kind == "derived" and t.state in ("accepted", "confirmed"):
            new_value = project._tie_value(t, now)
            if new_value is not None and new_value != t.linked_value and not project._sign_fits(t, new_value):
                findings.append(Finding(Decisions.key("calc_turned", t.deck, t.slide_uid, t.shape_id, t.para, t.raw), "calculated_turned_over", "high", t.deck, t.slide, t.context, t.context,
                                        f"\"{t.raw}\" is a calculated change that has turned the other way, so it was not rewritten",
                                        (f"It was {t.linked_value:+.4f} of its base and is now {new_value:+.4f}",), ""))
    return sort_findings(findings), cov
