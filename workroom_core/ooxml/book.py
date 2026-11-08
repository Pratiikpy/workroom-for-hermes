"""Excel workbooks as managed targets: constant numeric cells that are tied to a source, edited in place.

The interface mirrors Deck and Doc. A mention is a numeric constant cell with the labels on its row and column as
context. Formula cells are never mentioned or edited. After an edit the workbook is flagged to recalculate when it is
next opened, so every dependent formula shows a fresh value instead of a stale cached one.
"""

from __future__ import annotations

from typing import Iterator

from lxml import etree

from ..match.numbers import NumberMention
from .package import Package, open_package, rewrite
from .pptx import DocMention, EditReport
from .runs import EditError, Replacement
from .xlsx import S_NS, index_workbook, parse_xml, serialize_xml, sheets, split_cell, _col_to_int

WORKBOOK = "xl/workbook.xml"


def _decimals(text: str) -> int:
    return len(text.split(".")[1]) if "." in text else 0


class Book:
    def __init__(self, data: bytes) -> None:
        self.pkg: Package = open_package(data)
        if WORKBOOK not in self.pkg.by_name:
            raise EditError("not an Excel workbook (no xl/workbook.xml)")
        self._sheets = sheets(self.pkg)
        self._xml: dict[str, etree._Element] = {}
        self._dirty: set[str] = set()

    # ---- interface shared with Deck and Doc ----
    def slide_parts(self) -> list[str]:
        return [s.part for s in self._sheets]

    def shapes(self, slide: int = 1):
        for i, s in enumerate(self._sheets, 1):
            if i == slide:
                for c in index_workbook(self.pkg):
                    if c.sheet == s.name and not c.is_formula:
                        yield c.col, f"{s.name}!{c.ref}", repr(c.value)

    def _root(self, part: str) -> etree._Element:
        if part not in self._xml:
            self._xml[part] = parse_xml(self.pkg.read(part))
        return self._xml[part]

    def mentions(self) -> Iterator[DocMention]:
        sheet_no = {s.name: i for i, s in enumerate(self._sheets, 1)}
        for c in index_workbook(self.pkg):
            if c.is_formula or c.is_date or c.hidden:
                continue
            root = self._root(next(s.part for s in self._sheets if s.name == c.sheet))
            node = root.xpath("//x:c[@r=$r]", namespaces={"x": S_NS}, r=c.ref)
            raw = node[0].find("{%s}v" % S_NS).text if node and node[0].find("{%s}v" % S_NS) is not None else repr(c.value)
            nm = NumberMention(raw, c.value, c.value, _decimals(raw), "plain", 1.0, c.value < 0, 0, len(raw))
            ctx = (" ".join(c.row_labels + c.col_labels),) + tuple(c.row_labels) + tuple(c.col_labels)
            yield DocMention(sheet_no[c.sheet], 0, c.row, c.col, 0, nm, ctx, (c.row, c.col), None)

    def edit_mention(self, dm: DocMention, new_text: str) -> Replacement:
        sheet = self._sheets[dm.slide - 1]
        root = self._root(sheet.part)
        col_letters = ""
        n = dm.seg
        while n:
            n, r = divmod(n - 1, 26)
            col_letters = chr(65 + r) + col_letters
        ref = f"{col_letters}{dm.para}"
        found = root.xpath("//x:c[@r=$r]", namespaces={"x": S_NS}, r=ref)
        if not found:
            raise EditError(f"cell {ref} is no longer there; the workbook changed since discovery")
        c = found[0]
        if c.find("{%s}f" % S_NS) is not None:
            raise EditError(f"cell {ref} holds a formula; the formula is the source of truth and is not overwritten")
        if c.get("t") not in (None, "n"):
            raise EditError(f"cell {ref} is not numeric")
        v = c.find("{%s}v" % S_NS)
        if v is None or v.text != dm.number.raw:
            raise EditError(f"cell {ref} no longer holds {dm.number.raw}; it was changed since discovery")
        float(new_text)
        v.text = new_text
        self._dirty.add(sheet.part)
        return Replacement(1, False)

    def serialize(self) -> tuple[bytes, EditReport]:
        if not self._dirty:
            return rewrite(self.pkg, {}), EditReport((), False)
        replacements = {part: serialize_xml(self._xml[part]) for part in self._dirty}
        wb = self._root(WORKBOOK)
        calc = wb.find("{%s}calcPr" % S_NS)
        if calc is None:
            calc = etree.SubElement(wb, "{%s}calcPr" % S_NS)
        calc.set("fullCalcOnLoad", "1")
        replacements[WORKBOOK] = serialize_xml(wb)
        return rewrite(self.pkg, replacements), EditReport(tuple(sorted(replacements)), False)
