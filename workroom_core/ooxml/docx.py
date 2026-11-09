"""Word editing on the byte-preserving package layer: numbers in body paragraphs and table cells.

The interface mirrors the PowerPoint Deck so projects can treat both the same way: a document has one "slide"
(the main body) and shape id 0; mentions carry the paragraph index counted over the whole body, tables included.
Tracked changes are respected: deleted text is never matched, and edits never accept or reject a revision.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator

from lxml import etree

from ..match.numbers import parse_numbers
from .package import Package, open_package, rewrite
from .pptx import DocMention, EditReport
from .runs import OWN_AUTHOR, WORD, EditError, Replacement, _text_of, _text_runs, find_all, replace_once, replace_tracked
from .xlsx import parse_xml, serialize_xml

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MAIN = "word/document.xml"


_EXTRA = re.compile(r"word/(header\d*|footer\d*|footnotes|endnotes)\.xml")


_NUMBERED_HEADING = re.compile(r"\d{1,2}(?:\.\d{1,2})+\s+(?!(?i:million|billion|thousand|trillion|percent|per)\b)[A-Z]")
_REFERENCE_NUMBER = re.compile(r"\d+(?:\.\d+)*")
_SECTION_HEADING = re.compile(r"\s*\d{1,2}(?:\.\d{1,2})+\s*(?!(?i:million|billion|thousand|trillion|percent|per)\b)[A-Za-z]")


def _cell_text(tr: etree._Element, index: int) -> str:
    cells = [x for x in tr.iter(_w("tc")) if next(x.iterancestors(_w("tr"))) is tr]
    return "".join(_text_of(r, WORD) for q in cells[index].iter(_w("p")) for seg in _text_runs(q, WORD) for r in seg) if index < len(cells) else ""


_DOTTED_REFERENCE = re.compile(r"\d{1,2}\.\d{1,2}(?:\.\d{1,2})?")


def _reference_column(rows: list[etree._Element], index: int) -> bool:
    """A column whose every filled cell is a dotted number such as 5.2 or 3.2.2, in at least three rows, holds note references, whatever its heading says (a long table is
    often split across pages and the part that carries the Notes heading is somewhere else)."""
    texts = [_cell_text(r, index).strip() for r in rows]
    filled = [t for t in texts if t]
    return len(filled) >= 3 and all(_DOTTED_REFERENCE.fullmatch(t) for t in filled)


def _w(tag: str) -> str:
    return "{%s}%s" % (W_NS, tag)


class Doc:
    def __init__(self, data: bytes) -> None:
        self.pkg: Package = open_package(data)
        if MAIN not in self.pkg.by_name:
            raise EditError("not a Word document (no word/document.xml)")
        self._parts = [MAIN] + sorted(n for n in self.pkg.by_name if _EXTRA.fullmatch(n))
        self._roots: dict[str, etree._Element] = {}
        self._dirty: set[str] = set()
        self.tracked = False  # edit as tracked changes (struck old number, inserted new one) instead of directly
        self._rev = None
        self._merged = False
        bodies = len(self._root(MAIN).findall(_w("body")))
        if bodies != 1:
            raise EditError(f"the document holds {bodies} body elements; Word shows only the first, so an edit to another would not appear and the document is not edited")

    # ---- interface shared with Deck ----
    def slide_parts(self) -> list[str]:
        return list(self._parts)

    def _root(self, part: str) -> etree._Element:
        if part not in self._roots:
            self._roots[part] = parse_xml(self.pkg.read(part))
        return self._roots[part]

    def _paragraphs(self, part: str = MAIN) -> list[etree._Element]:
        return list(self._root(part).iter(_w("p")))

    def shapes(self, slide: int = 1) -> Iterator[tuple[int, str, str]]:
        for i, p in enumerate(self._paragraphs(self._parts[slide - 1])):
            text = "".join(_text_of(r, WORD) for seg in _text_runs(p, WORD) for r in seg)
            if text.strip():
                yield 0, f"paragraph {i}", text

    # ---- context ----
    @staticmethod
    def _style(p: etree._Element) -> str:
        st = p.find("./{%s}pPr/{%s}pStyle" % (W_NS, W_NS))
        return (st.get(_w("val")) or "") if st is not None else ""

    @staticmethod
    def _plain(p: etree._Element) -> str:
        return "".join(_text_of(r, WORD) for seg in _text_runs(p, WORD) for r in seg)

    def mentions(self) -> Iterator[DocMention]:
        for part_no, part in enumerate(self._parts, 1):
            yield from self._mentions_in(part_no, part)

    def _mentions_in(self, part_no: int, part: str) -> Iterator[DocMention]:
        paras = self._paragraphs(part)
        heading = ""
        tables: list[etree._Element] = []
        for pi, p in enumerate(paras):
            style = self._style(p).lower()
            plain = self._plain(p)
            tc = next((a for a in p.iterancestors() if a.tag == _w("tc")), None)
            if style.startswith("heading") or style == "title" or (tc is None and len(plain) <= 120 and _SECTION_HEADING.match(plain)):
                heading = plain  # also a paragraph that only reads as a heading ("5.1.1Reconciliation of movements"), whatever its style is called
            if tc is not None:
                tr = next(a for a in tc.iterancestors() if a.tag == _w("tr"))
                tbl = next(a for a in tr.iterancestors() if a.tag == _w("tbl"))
                rows = [x for x in tbl.iter(_w("tr")) if next(x.iterancestors(_w("tbl"))) is tbl]
                cells = [x for x in tr.iter(_w("tc")) if next(x.iterancestors(_w("tr"))) is tr]
                ri, ci = rows.index(tr), cells.index(tc)
                cell_rc = (ri, ci)
                if not any(t is tbl for t in tables):
                    tables.append(tbl)
                table_no = next(k for k, t in enumerate(tables) if t is tbl)
                first_row = [x for x in rows[0].iter(_w("tc")) if next(x.iterancestors(_w("tr"))) is rows[0]]
                col_head = "".join(self._plain(q) for q in first_row[ci].iter(_w("p"))) if ri > 0 and ci < len(first_row) else ""
                row_head = "".join(self._plain(q) for q in cells[0].iter(_w("p"))) if ci > 0 else ""
                note_col = any(_cell_text(rows[k], ci).strip().lower() in ("note", "notes") for k in range(min(4, len(rows)))) or _reference_column(rows, ci)
            else:
                cell_rc = None
                row_head = col_head = ""
                note_col = False
                table_no = -1
            consumed = 0
            for seg_i, seg in enumerate(_text_runs(p, WORD)):
                text = "".join(_text_of(r, WORD) for r in seg)
                seg_start = consumed
                consumed += len(text)
                for nm in parse_numbers(text):
                    if nm.unit == "plain" and nm.decimals == 0 and "," not in nm.raw and len(nm.raw) == 4 and 1900 <= nm.value <= 2100:
                        continue
                    if (style.startswith("heading") or style == "title") and nm.unit == "plain" and seg_start + nm.start == 0:
                        continue  # the section number that opens a heading ("4.1 Property, plant and equipment") numbers the section, it is not a quantity
                    if nm.unit == "plain" and seg_start + nm.start == 0 and _NUMBERED_HEADING.match(plain) and len(plain) <= 100:
                        continue  # the same, in a heading that is only formatted as one
                    if note_col and nm.unit == "plain" and _REFERENCE_NUMBER.fullmatch(nm.raw):
                        continue  # a "Notes" column holds note numbers, not amounts
                    ctx = (plain,) + tuple(x for x in (heading, row_head, col_head) if x)
                    po = seg_start + nm.start
                    po = po if plain[po : po + len(nm.raw)] == nm.raw else None
                    yield DocMention(part_no, 0, pi, seg_i, nm.start, nm, ctx, cell_rc, po, part, table_no, row_head, col_head, heading)

    def _next_revision_id(self) -> int:
        if self._rev is None:
            used = [0]
            for part in self._parts:
                for el in self._root(part).iter():
                    v = el.get("{%s}id" % W_NS)
                    if v and v.isdigit():
                        used.append(int(v))
            self._rev = max(used)
        self._rev += 1
        return self._rev

    def paragraphs(self):
        """Every paragraph of every part as (part number, 0, paragraph index, table cell, text)."""
        for part_no, part in enumerate(self._parts, 1):
            for pi, p in enumerate(self._paragraphs(part)):
                tc = next((a for a in p.iterancestors() if a.tag == _w("tc")), None)
                yield part_no, 0, pi, (0, 0) if tc is not None else None, self._plain(p)

    def edit_label(self, slide: int, shape_id: int, para: int, cell, old: str, new: str, occurrence: int = 0) -> Replacement:
        part = self._parts[slide - 1]
        paras = self._paragraphs(part)
        if para >= len(paras):
            raise EditError("the paragraph is no longer there; the document changed since discovery")
        p = paras[para]
        hits = find_all(p, old, WORD)
        if occurrence >= len(hits):
            raise EditError(f"{old!r} is split across formatting or no longer in this paragraph; not changed")
        res = replace_once(p, old, new, WORD, occurrence=occurrence if len(hits) > 1 else None)
        self._merged = self._merged or res.formats_merged
        self._dirty.add(part)
        return res

    def edit_mention(self, dm: DocMention, new_text: str) -> Replacement:
        part = self._parts[dm.slide - 1]
        paras = self._paragraphs(part)
        if dm.para >= len(paras):
            raise EditError("the paragraph is no longer there; the document changed since discovery")
        p = paras[dm.para]
        hits = find_all(p, dm.number.raw, WORD)
        key = (dm.seg, dm.offset)
        if key not in hits:
            raise EditError("the number is no longer where it was found; the document changed since discovery")
        occ = hits.index(key) if len(hits) > 1 else None
        if self.tracked:
            res = replace_tracked(p, dm.number.raw, new_text, WORD, occ, author=OWN_AUTHOR, date=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), next_id=self._next_revision_id)
        else:
            res = replace_once(p, dm.number.raw, new_text, WORD, occurrence=occ)
        self._merged = self._merged or res.formats_merged
        self._dirty.add(part)
        return res

    def serialize(self) -> tuple[bytes, EditReport]:
        if not self._dirty:
            return rewrite(self.pkg, {}), EditReport((), self._merged)
        changed = {part: serialize_xml(self._roots[part]) for part in sorted(self._dirty)}
        return rewrite(self.pkg, changed), EditReport(tuple(changed), self._merged)
