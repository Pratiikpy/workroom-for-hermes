"""The review room: a document as it is drawn, with every linked figure marked on its page, before and after a release.

Pages come from the Office installed on the machine (see `render.py`); the marks come from the project's links, placed by lining the figures of the
document up with the figures in the page text. A figure that cannot be placed is listed without a mark, never given a guessed one. Where Office
is missing, `structural` gives the figures in their sentences and says, in its own label, that it is not a drawing of the document.

Nothing here edits a document or writes outside the project's own state folder.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import render
from .match.numbers import parse_numbers

if TYPE_CHECKING:
    from .project import Plan, Project

KINDS = ("changes", "linked", "protected", "asked", "blocked")


@dataclass(frozen=True)
class Mark:
    page: int
    x: float
    y: float
    w: float
    h: float
    kind: str
    tie_id: int
    text: str
    new_text: str = ""
    label: str = ""
    old_text: str = ""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pdf_numbers(pdf: bytes) -> list[tuple[int, str, list[render.Box]]]:
    """The figures of a PDF in reading order, each with the boxes it occupies: (page, text as written, boxes)."""
    import pypdfium2 as pdfium

    out: list[tuple[int, str, list[render.Box]]] = []
    doc = pdfium.PdfDocument(pdf)
    try:
        for index in range(min(len(doc), render.MAX_PAGES)):
            page = doc[index]
            width, height = page.get_size()
            text = page.get_textpage()
            try:
                body = text.get_text_range()
                for nm in parse_numbers(body):
                    boxes = []
                    for k in range(text.count_rects(nm.start, nm.end - nm.start)):
                        left, bottom, right, top = text.get_rect(k)
                        boxes.append(render.Box(index + 1, left / width, 1 - top / height, (right - left) / width, (top - bottom) / height))
                    out.append((index + 1, nm.raw, boxes))
            finally:
                text.close()
                page.close()
    finally:
        doc.close()
    return out


def align(doc_raws: list[str], pdf_raws: list[str]) -> dict[int, int]:
    """Which figure of the PDF is which figure of the document: a position in the document to a position in the PDF, for the figures both hold in
    the same order. Figures that only one side has (a page number, a heading's number) are left out."""
    matcher = difflib.SequenceMatcher(None, doc_raws, pdf_raws, autojunk=False)
    found: dict[int, int] = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            found[a + k] = b + k
    return found


class Reviewer:
    def __init__(self, project: Project, folder: Path) -> None:
        self.project = project
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    # ---- pages ----
    def _pdf(self, data: bytes, suffix: str) -> bytes | None:
        cached = self.folder / f"{_sha(data)}.pdf"
        if cached.is_file():
            return cached.read_bytes()
        tmp = self.folder / f"{_sha(data)}{suffix}"
        tmp.write_bytes(data)
        try:
            pdf = render.office_to_pdf(tmp)
        finally:
            tmp.unlink(missing_ok=True)
        if pdf is not None:
            cached.write_bytes(pdf)
        return pdf

    def _marks(self, deck_rel: str, data: bytes, pdf: bytes, plan: Plan, after: bool) -> list[Mark]:
        from .project import open_document

        deck = open_document(data, deck_rel)
        mentions = list(deck.mentions())
        placed = _pdf_numbers(pdf)
        mapping = align([m.number.raw for m in mentions], [raw for _p, raw, _b in placed])
        ties = {self.project._tkey(t): t for t in self.project.ties() if t.deck == deck_rel}
        changed = {(i.deck, i.slide, i.old_text, i.src): i for i in plan.impacts}
        blocked_text = " ".join(plan.blocked)
        marks: list[Mark] = []
        for i, dm in enumerate(mentions):
            t = ties.get(self.project._mkey(dm)) or ties.get(self.project._mkey(dm, f"#{dm.slide}"))
            if t is None or i not in mapping:
                continue
            src = f"{t.src_file}!{t.sheet}!{t.ref}"
            hit = changed.get((deck_rel, t.slide, t.raw, src)) if t.state in ("accepted", "confirmed") else None
            if t.state == "held":
                kind = "protected"
            elif t.state == "confirm":
                kind = "asked"
            elif hit is not None:
                kind = "changes"
            elif f"'{t.raw}' was not rewritten" in blocked_text:
                kind = "blocked"
            else:
                kind = "linked"
            shown = dm.number.raw
            for box in placed[mapping[i]][2]:
                marks.append(Mark(box.page, box.x, box.y, box.w, box.h, kind, t.id, shown, hit.new_text if hit else "", t.context[:140], hit.old_text if hit else ""))
        return marks

    def overview(self, plan: Plan | None = None) -> dict[str, Any]:
        """The documents of the project, whether they can be drawn, and how many marks of each kind each holds."""
        from .project import DECK_EXT

        plan = plan or self.project.plan_refresh()
        docs = []
        for p in self.project._files(DECK_EXT):
            rel = self.project._rel(p)
            mine = [t for t in self.project.ties() if t.deck == rel and t.kind != "scene"]
            if not mine:
                continue
            counts = {k: 0 for k in KINDS}
            for t in mine:
                counts["protected" if t.state == "held" else "asked" if t.state == "confirm" else "linked"] += 1
            counts["changes"] = sum(1 for i in plan.impacts if i.deck == rel)
            docs.append({"deck": rel, "can_draw": render.available(p.suffix), "links": len(mine), "counts": counts, "changes_in_plan": rel in plan.files})
        return {"documents": docs, "blocked": plan.blocked, "renderer": "office" if any(d["can_draw"] for d in docs) else "none"}

    def page(self, deck_rel: str, side: str, page: int, plan: Plan | None = None) -> dict[str, Any]:
        """One page of one document, before the release or after it, drawn by Office, with its marks."""
        plan = plan or self.project.plan_refresh()
        path = self.project.root / deck_rel
        if not path.is_file():
            raise ValueError("that document is not in the project")
        data = (plan.files.get(deck_rel) if side == "after" else None) or path.read_bytes()
        if side == "after" and deck_rel not in plan.files:
            side = "before"  # nothing changes in this document, so after is the same page
        if not render.available(path.suffix):
            return {"drawn": False, "why": "Office or the page drawing library is not available on this machine; the figures are listed without a drawing."}
        pdf = self._pdf(data, path.suffix)
        if pdf is None:
            return {"drawn": False, "why": "Office could not open this document to draw it."}
        total = render.page_count(pdf)
        page = max(1, min(int(page), total))
        png, w, h = render.page_png(pdf, page)
        marks = [m for m in self._marks(deck_rel, data, pdf, plan, side == "after") if m.page == page]
        return {"drawn": True, "side": side, "page": page, "pages": total, "width": w, "height": h, "png": base64.b64encode(png).decode("ascii"), "marks": [asdict(m) for m in marks],
                "drawn_by": f"{render.engine(path.suffix)} on this machine"}

    def pages_with_marks(self, deck_rel: str, plan: Plan | None = None) -> dict[str, Any]:
        """Which pages of the document hold changes, and how many marks of each kind are on every page that holds any."""
        plan = plan or self.project.plan_refresh()
        path = self.project.root / deck_rel
        if not render.available(path.suffix):
            return {"drawn": False, "pages": []}
        data = plan.files.get(deck_rel) or path.read_bytes()
        pdf = self._pdf(data, path.suffix)
        if pdf is None:
            return {"drawn": False, "pages": []}
        by_page: dict[int, dict[str, int]] = {}
        for m in self._marks(deck_rel, data, pdf, plan, deck_rel in plan.files):
            by_page.setdefault(m.page, {})
            by_page[m.page][m.kind] = by_page[m.page].get(m.kind, 0) + 1
        return {"drawn": True, "total": render.page_count(pdf), "pages": [{"page": p, "marks": c} for p, c in sorted(by_page.items())]}

    def structural(self, deck_rel: str, plan: Plan | None = None, limit: int = 400) -> dict[str, Any]:
        """The linked figures in their sentences, for a machine that cannot draw the document. It says so."""
        plan = plan or self.project.plan_refresh()
        changed = {(i.deck, i.slide, i.old_text, i.src): i for i in plan.impacts}
        rows = []
        for t in self.project.ties():
            if t.deck != deck_rel or t.kind == "scene":
                continue
            hit = changed.get((deck_rel, t.slide, t.raw, f"{t.src_file}!{t.sheet}!{t.ref}")) if t.state in ("accepted", "confirmed") else None
            rows.append({"tie_id": t.id, "sentence": t.context[:220], "text": t.raw, "new_text": hit.new_text if hit else "", "state": t.state,
                         "kind": "changes" if hit else "protected" if t.state == "held" else "asked" if t.state == "confirm" else "linked"})
            if len(rows) >= limit:
                break
        return {"label": "Structural view: the figures in their sentences. This is not a drawing of the document.", "rows": rows}


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
