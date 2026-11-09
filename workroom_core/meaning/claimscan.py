"""Compare every changed sentence before and after an update and report the claims the update has made false."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .claims import Claim, figures_in, holds, rank_holds, read_claims
from .decisions import Decisions
from .findings import Finding, mask_digits, opposite_word, sort_findings
from ..match.numbers import display_round
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


def _calc_shown(t, value: float) -> str:
    return f"{value * 100:+.1f}%" if t.transform == "fraction_to_percent" else format(value, "+,.10g")


_YEAR_WORDS = re.compile(r"year[- ]over[- ]year|\byoy\b|\by/y\b|a year (?:ago|earlier)|annual|last year|prior year|same (?:month|quarter) (?:a year |last year)", re.I)


def _same_shown(a: float, b: float, raw: str, transform: str) -> bool:
    """Do two source values read as the same figure once written the way the sentence writes it (same unit, same rounding)?"""
    from ..match.numbers import _TRANSFORMS, parse_numbers

    found = parse_numbers(raw)
    if not found:
        return a == b
    m = found[0]
    f = _TRANSFORMS.get(transform) or _TRANSFORMS["exact"]
    return display_round(f(a, m.scale), m.decimals) == display_round(f(b, m.scale), m.decimals)


def _num(v: float) -> str:
    return format(v, ",.10g")


def _tag(cell) -> str:
    return " ".join(dict.fromkeys(cell.col_labels + cell.row_labels))[:40]


def _phrase(text: str, figs, claim: Claim) -> str:
    """The words of the sentence the claim was read from, as the owner wrote them (never the internal token form)."""
    idx = [i for i in (claim.a, claim.b) if i is not None]
    start, end = min(figs[i].start for i in idx), max(figs[i].end for i in idx)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _fmt(values: list[float], claim: Claim) -> str:
    return " vs ".join(_num(values[i]) for i in (claim.a, claim.b) if i is not None)


def claim_findings(project: "Project", plan: "Plan", roll: dict | None = None) -> tuple[list[Finding], Coverage]:
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
    para_text: dict[tuple, tuple[str, str]] = {}  # (file, paragraph key) -> the sentence before and after this release

    def tie_for(dm):
        return tied_at.get(project._mkey(dm)) or tied_at.get(project._mkey(dm, f"#{dm.slide}"))

    def make(kind: str, severity: str, rel: str, slide: int, text_b: str, text_a: str, summary: str, evidence: list[str], claim: Claim | None = None, uid: str = "", fid: str = "") -> Finding:
        sug = ""
        if claim and kind in ("claim_flip", "baseline_flip", "record_flip") and opposite_word(claim.cue):
            sug = f"The figures now say the opposite: consider \"{opposite_word(claim.cue)}\" in place of \"{claim.cue}\"."
        fid = fid or Decisions.key(kind, rel, mask_digits(text_b), text_a)
        return Finding(fid, kind, severity, rel, slide, text_b, text_a, summary, tuple(evidence), sug)

    moved = {k for k in now if now[k] != then[k]} or ({"roll"} if roll else set())
    roll_to = {it["id"]: tuple(it["to"]) for it in (roll or {}).get("ties", [])}
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
            para_text[(rel, key)] = (text_b, text_a or text_b)
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
            if changed_text:
                for f in figs_b:
                    dm0 = next((d for d in mentions_b if d.para_offset == f.start), None) or next((d for d in mentions_b if d.number.raw == f.raw), None)
                    if dm0 is None or tie_for(dm0) is not None or (f.unit == "plain" and f.raw.replace(",", "").replace(".", "").isdigit() and abs(f.value) < 10):
                        continue
                    findings.append(make("untied_figure", "medium", rel, mentions_b[0].slide, text_b, text_a,
                                         f"\"{f.raw}\" in a sentence this release changes is not tied to any source, so nothing updates it",
                                         ["Check whether it still holds; if a calculation over the tied figures reproduces it, accept that calculation so it follows"],
                                         fid=Decisions.key("untied", rel, mask_digits(text_b), f.raw)))
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
                    vb2, va2 = list(vb), list(va)
                    both = []
                    for idx in (claim.a, claim.b):
                        fi = figs_b[idx]
                        dmi = by_start.get(fi.start) or next((d for d in mentions_b if d.number.raw == fi.raw), None)
                        ti = tie_for(dmi) if dmi is not None else None
                        ci = cells.get((ti.src_file, ti.sheet, ti.ref)) if ti is not None and ti.kind == "text" else None
                        if ci is None:
                            both.append(None)
                            continue
                        ca = cells.get(roll_to[ti.id]) if ti.id in roll_to else ci
                        both.append((ti.linked_value if ti.id in roll_to else then[(ci.file, ci.sheet, ci.ref)], now[(ca.file, ca.sheet, ca.ref)]))
                    if all(both):
                        # both figures are tied: judge the comparison on the source values, not on the rounded numbers the sentence shows
                        vb2[claim.a], va2[claim.a] = both[0]
                        vb2[claim.b], va2[claim.b] = both[1]
                    hb, ha = holds(claim, vb2), holds(claim, va2)
                    if hb and not ha:
                        findings.append(make("claim_flip", "high", rel, slide, text_b, text_a,
                                             f"\"{_phrase(text_b, figs_b, claim)}\" was true and is not true after this update",
                                             [f"Before: {_fmt(vb, claim)} ({claim.cue})", f"After: {_fmt(va, claim)} (the words \"{claim.cue}\" no longer fit)"], claim))
                    elif not hb and not ha:
                        findings.append(make("claim_already_false", "info", rel, slide, text_b, text_a, f"\"{_phrase(text_b, figs_b, claim)}\" did not hold before this update either", [f"Figures: {_fmt(vb, claim)}"], claim))
                    elif not hb and ha:
                        findings.append(make("claim_now_holds", "info", rel, slide, text_b, text_a, f"\"{_phrase(text_b, figs_b, claim)}\" was false and now holds", [f"After: {_fmt(va, claim)}"], claim))
                    continue
                f = figs_b[claim.a]
                dm = by_start.get(f.start) or next((d for d in mentions_b if d.number.raw == f.raw), None)
                tie = tie_for(dm) if dm is not None else None
                cell_b = cells.get((tie.src_file, tie.sheet, tie.ref)) if tie is not None and tie.kind == "text" else None
                if cell_b is None:
                    cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" about {f.raw} was not checked because that figure is not tied to a source cell")
                    continue
                cell_a = cells.get(roll_to[tie.id]) if tie.id in roll_to else cell_b
                kb, ka = (cell_b.file, cell_b.sheet, cell_b.ref), (cell_a.file, cell_a.sheet, cell_a.ref)
                val_b = tie.linked_value if tie.id in roll_to else then[kb]
                val_a = now[ka]
                if claim.pattern == "rank":
                    peers_b, peers_a = tl.history(cell_b), tl.history(cell_a)
                    if len(peers_a) < 2:
                        cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" was not checked: the workbook holds too little history for {f.raw}")
                        continue
                    pb = rank_holds(val_b, [then[(c.file, c.sheet, c.ref)] for c in peers_b], claim.relation)
                    pa = rank_holds(val_a, [now[(c.file, c.sheet, c.ref)] for c in peers_a], claim.relation)
                    shown = [f"{_tag(cell_a)}: {_num(val_a)}; earlier: " + "; ".join(f"{_tag(c)} {_num(now[(c.file, c.sheet, c.ref)])}" for c in peers_a[-4:])]
                    if pb and not pa:
                        findings.append(make("record_flip", "high", rel, slide, text_b, text_a, f"\"{claim.cue}\" for {f.raw} is no longer true", shown, claim))
                    elif not pb and not pa:
                        findings.append(make("claim_already_false", "info", rel, slide, text_b, text_a, f"\"{claim.cue}\" for {f.raw} did not hold before this update either", shown, claim))
                    continue
                yoy = bool(_YEAR_WORDS.search(text_b))
                pick = tl.year_ago if yoy else tl.previous
                bases_b = [b for b in (pick(cell_b),) if b is not None]
                bases_a = [b for b in (pick(cell_a),) if b is not None]
                which = "the year earlier" if yoy else "the previous period"
                if not bases_a:
                    cov.not_checked.append(f"{rel} slide {slide}: \"{claim.cue}\" about {f.raw} was not checked: no {'year-earlier' if yoy else 'earlier'} period in the workbook to compare with")
                    continue
                cmp = {"gt": lambda a, b: a > b, "lt": lambda a, b: a < b, "eq": lambda a, b: _same_shown(a, b, f.raw, tie.transform)}[claim.relation]
                hb = any(cmp(val_b, then[(b.file, b.sheet, b.ref)]) for b in bases_b)
                ha = any(cmp(val_a, now[(b.file, b.sheet, b.ref)]) for b in bases_a)
                if hb and not ha:
                    findings.append(make("baseline_flip", "medium", rel, slide, text_b, text_a, f"\"{claim.cue}\" about {f.raw} no longer holds against {which}",
                                         [f"{_tag(cell_a)}: {_num(val_a)}; " + "; ".join(f"{_tag(b)} {_num(now[(b.file, b.sheet, b.ref)])}" for b in bases_a)], claim))
    for item in (roll or {}).get("turned", []):
        t = next((x for x in ties if x.id == item["id"]), None)
        if t is None:
            continue
        key = (t.slide_uid or f"#{t.slide}", t.shape_id, t.para, t.cell_rc)
        before, after = para_text.get((t.deck, key), (t.context, t.context))
        findings.append(Finding(Decisions.key("calc_turned", t.deck, t.slide_uid, t.shape_id, t.para, t.raw), "calculated_turned_over", "high", t.deck, t.slide, before, after,
                                f"\"{t.raw}\" is a calculated change that would turn the other way next period, so it was not rolled",
                                (f"It was {_calc_shown(t, item['old'])} and would now be {_calc_shown(t, item['new'])}",), ""))
    for t in ties:
        if t.kind == "derived" and not roll and t.state in ("accepted", "confirmed"):
            new_value = project._tie_value(t, now)
            if new_value is not None and new_value != t.linked_value and not project._sign_fits(t, new_value):
                findings.append(Finding(Decisions.key("calc_turned", t.deck, t.slide_uid, t.shape_id, t.para, t.raw), "calculated_turned_over", "high", t.deck, t.slide, t.context, t.context,
                                        f"\"{t.raw}\" is a calculated change that has turned the other way, so it was not rewritten",
                                        (f"It was {_calc_shown(t, t.linked_value)} and would now be {_calc_shown(t, new_value)}",), ""))
    return sort_findings(findings), cov
