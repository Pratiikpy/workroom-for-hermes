"""PowerPoint editing on the byte-preserving package layer.

Every edit names its target (slide, shape id) and its exact text; nothing is replaced deck-wide. Charts are
updated in the series cache and the embedded workbook together, or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator

from lxml import etree

from .package import Package, open_package, rewrite
from ..match.numbers import NumberMention, parse_numbers
from .runs import DRAWING, EditError, Replacement, _text_runs, _text_of, find_all, replace_once
from .xlsx import patch_numeric_cell, read_cell, rels_for, parse_xml, serialize_xml, split_cell

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "c": C_NS, "r": R_NS}


@dataclass(frozen=True)
class EditReport:
    parts_changed: tuple[str, ...]
    formats_merged: bool


@dataclass(frozen=True)
class DocMention:
    slide: int
    shape_id: int
    para: int
    seg: int
    offset: int
    number: NumberMention
    context: tuple[str, ...]
    cell: tuple[int, int] | None  # (row, column) when the number sits in a table cell
    para_offset: int | None = None  # where the number starts inside the paragraph's visible text, when that can be told
    slide_uid: str = ""  # the slide's own stable id (survives inserting, deleting and reordering slides); the part or sheet name for Word and Excel


@dataclass(frozen=True)
class ChartSeries:
    name: str | None
    categories: tuple[str, ...]
    values: tuple[float | None, ...]
    cat_formula: str | None
    val_formula: str | None


def _a(tag: str) -> str:
    return "{%s}%s" % (A_NS, tag)


class Deck:
    def __init__(self, data: bytes) -> None:
        self.pkg: Package = open_package(data)
        self._xml: dict[str, etree._Element] = {}
        self._blobs: dict[str, bytes] = {}  # replaced non-XML parts such as embedded workbooks
        self._merged = False
        self._dirty: set[str] = set()

    # ---- structure ----
    def slide_uids(self) -> list[str]:
        """PowerPoint's own slide ids (p:sldId/@id), in slide order. They stay with a slide when others are inserted, deleted or reordered."""
        pres = self._root("ppt/presentation.xml")
        rels = rels_for(self.pkg, "ppt/presentation.xml")
        return [sid.get("id") or "" for sid in pres.iter("{%s}sldId" % P_NS) if sid.get("{%s}id" % R_NS) in rels]

    def slide_parts(self) -> list[str]:
        pres = self._root("ppt/presentation.xml")
        rels = rels_for(self.pkg, "ppt/presentation.xml")
        out = []
        for sid in pres.iter("{%s}sldId" % P_NS):
            rid = sid.get("{%s}id" % R_NS)
            if rid in rels:
                out.append(rels[rid][1])
        return out

    def _root(self, part: str) -> etree._Element:
        if part not in self._xml:
            self._xml[part] = parse_xml(self.pkg.read(part))
        return self._xml[part]

    def _slide(self, number: int) -> tuple[str, etree._Element]:
        parts = self.slide_parts()
        if not 1 <= number <= len(parts):
            raise EditError(f"slide {number} does not exist (deck has {len(parts)})")
        return parts[number - 1], self._root(parts[number - 1])

    _EDITABLE = ("{%s}sp" % P_NS, "{%s}graphicFrame" % P_NS, "{%s}pic" % P_NS, "{%s}cxnSp" % P_NS)

    @staticmethod
    def shape(root: etree._Element, shape_id: int) -> etree._Element:
        hits = []
        for nv in root.iter("{%s}cNvPr" % P_NS):
            sh = nv.getparent().getparent()
            if sh.tag in Deck._EDITABLE and nv.get("id") == str(shape_id):
                hits.append(sh)
        if not hits:
            raise EditError(f"shape id {shape_id} not found (groups and the slide root cannot be targeted; target a shape inside)")
        if len(hits) > 1:
            raise EditError(f"shape id {shape_id} is not unique on the slide; refusing to guess")
        return hits[0]

    def shapes(self, slide: int) -> Iterator[tuple[int, str, str]]:
        """(shape id, name, text) for each text shape and table; groups are walked, never returned as one."""
        _, root = self._slide(slide)
        for nv in root.iter("{%s}cNvPr" % P_NS):
            sh = nv.getparent().getparent()
            if sh.tag not in (("{%s}sp" % P_NS), ("{%s}graphicFrame" % P_NS)):
                continue
            text = " ".join("".join(t.text or "" for t in p.iter(_a("t"))) for p in sh.iter(_a("p")))
            if text.strip():
                yield int(nv.get("id")), nv.get("name") or "", text

    # ---- finding numbers in text and tables ----
    @staticmethod
    def _is_year(nm: NumberMention) -> bool:
        return nm.unit == "plain" and nm.decimals == 0 and "," not in nm.raw and len(nm.raw.strip()) == 4 and 1900 <= nm.value <= 2100

    def _slide_title(self, root: etree._Element) -> str:
        for sp in root.iter("{%s}sp" % P_NS):
            ph = sp.find(".//{%s}ph" % P_NS)
            if ph is not None and ph.get("type") in ("title", "ctrTitle"):
                return " ".join("".join(t.text or "" for t in p.iter(_a("t"))) for p in sp.iter(_a("p")))
        return ""

    def mentions(self) -> Iterator[DocMention]:
        """Every number written in a text shape or table cell, with the words around it. Years are skipped."""
        uids = self.slide_uids()
        for si in range(1, len(self.slide_parts()) + 1):
            _, root = self._slide(si)
            self._uid = uids[si - 1] if si - 1 < len(uids) else ""
            title = self._slide_title(root)
            for nv in root.iter("{%s}cNvPr" % P_NS):
                sh = nv.getparent().getparent()
                sid = int(nv.get("id"))
                name = nv.get("name") or ""
                if sh.tag == "{%s}sp" % P_NS:
                    tx = sh.find("{%s}txBody" % P_NS)
                    if tx is not None:
                        yield from self._para_mentions(si, sid, tx, None, (title, name), None)
                elif sh.tag == "{%s}graphicFrame" % P_NS:
                    tbl = sh.find(".//{%s}tbl" % A_NS)
                    if tbl is None:
                        continue
                    rows = tbl.findall(_a("tr"))
                    grid = [[tc for tc in tr.findall(_a("tc"))] for tr in rows]

                    def cell_text(tc: etree._Element) -> str:
                        return " ".join("".join(t.text or "" for t in p.iter(_a("t"))) for p in tc.iter(_a("p"))).strip()

                    for r, tcs in enumerate(grid):
                        for c, tc in enumerate(tcs):
                            tb = tc.find(_a("txBody"))
                            if tb is None:
                                continue
                            row_head = cell_text(tcs[0]) if c > 0 else ""
                            col_head = cell_text(grid[0][c]) if r > 0 and c < len(grid[0]) else ""
                            yield from self._para_mentions(si, sid, tb, (r, c), (title, name, row_head, col_head), (r, c))

    def _para_mentions(self, si: int, sid: int, body: etree._Element, cell, extra: tuple[str, ...], cell_rc) -> Iterator[DocMention]:
        for pi, p in enumerate(body.findall(_a("p"))):
            para_text = "".join(t.text or "" for t in p.iter(_a("t")))
            consumed = 0
            for seg_i, seg in enumerate(_text_runs(p, DRAWING)):
                text = "".join(_text_of(r, DRAWING) for r in seg)
                for nm in parse_numbers(text):
                    if self._is_year(nm):
                        continue
                    po = consumed + nm.start
                    po = po if para_text[po : po + len(nm.raw)] == nm.raw else None
                    yield DocMention(si, sid, pi, seg_i, nm.start, nm, (para_text,) + tuple(x for x in extra if x), cell_rc, po, getattr(self, "_uid", ""))
                consumed += len(text)

    def _target_paragraph(self, dm: DocMention) -> etree._Element:
        _, root = self._slide(dm.slide)
        sh = self.shape(root, dm.shape_id)
        if dm.cell is not None:
            tbl = sh.find(".//{%s}tbl" % A_NS)
            tc = tbl.findall(_a("tr"))[dm.cell[0]].findall(_a("tc"))[dm.cell[1]]
            body = tc.find(_a("txBody"))
        else:
            body = sh.find("{%s}txBody" % P_NS)
        return body.findall(_a("p"))[dm.para]

    def paragraphs(self) -> Iterator[tuple[int, int, int, tuple[int, int] | None, str]]:
        """Every paragraph of every text shape and table cell as (slide, shape id, paragraph index, table cell, text), whether or not it holds a number."""
        for si in range(1, len(self.slide_parts()) + 1):
            _, root = self._slide(si)
            for nv in root.iter("{%s}cNvPr" % P_NS):
                sh = nv.getparent().getparent()
                sid = int(nv.get("id"))
                if sh.tag == "{%s}sp" % P_NS:
                    tx = sh.find("{%s}txBody" % P_NS)
                    if tx is not None:
                        for pi, p in enumerate(tx.findall(_a("p"))):
                            yield si, sid, pi, None, "".join(t.text or "" for t in p.iter(_a("t")))
                elif sh.tag == "{%s}graphicFrame" % P_NS:
                    tbl = sh.find(".//{%s}tbl" % A_NS)
                    if tbl is None:
                        continue
                    for r, tr in enumerate(tbl.findall(_a("tr"))):
                        for c, tc in enumerate(tr.findall(_a("tc"))):
                            tb = tc.find(_a("txBody"))
                            if tb is not None:
                                for pi, p in enumerate(tb.findall(_a("p"))):
                                    yield si, sid, pi, (r, c), "".join(t.text or "" for t in p.iter(_a("t")))

    def edit_label(self, slide: int, shape_id: int, para: int, cell: tuple[int, int] | None, old: str, new: str, occurrence: int = 0) -> Replacement:
        """Replace one named occurrence of a word or phrase inside one paragraph (a period label, never a number)."""
        probe = DocMention(slide, shape_id, para, 0, 0, NumberMention("", 0.0, 0.0, 0, "plain", 1.0, False, 0, 0), (), cell)
        p = self._target_paragraph(probe)
        hits = find_all(p, old, DRAWING)
        if occurrence >= len(hits):
            raise EditError(f"{old!r} is split across formatting or no longer in this paragraph; not changed")
        result = replace_once(p, old, new, DRAWING, occurrence=occurrence if len(hits) > 1 else None)
        self._merged = self._merged or result.formats_merged
        self._dirty.add(self.slide_parts()[slide - 1])
        return result

    def edit_mention(self, dm: DocMention, new_text: str) -> Replacement:
        """Replace exactly the number the mention points at, wherever else the same digits appear."""
        p = self._target_paragraph(dm)
        hits = find_all(p, dm.number.raw, DRAWING)
        key = (dm.seg, dm.offset)
        if key not in hits:
            raise EditError("the number is no longer where it was found; the document changed since discovery")
        part = self.slide_parts()[dm.slide - 1]
        result = replace_once(p, dm.number.raw, new_text, DRAWING, occurrence=hits.index(key) if len(hits) > 1 else None)
        self._merged = self._merged or result.formats_merged
        self._dirty.add(part)
        return result

    # ---- text edits ----
    def edit_text(self, slide: int, shape_id: int, old: str, new: str, occurrence: int | None = None) -> Replacement:
        part, root = self._slide(slide)
        sh = self.shape(root, shape_id)
        candidates = [(p, h) for p in sh.iter(_a("p")) for h in find_all(p, old, DRAWING)]
        if not candidates:
            raise EditError(f"text {old!r} not found in shape {shape_id} on slide {slide}")
        if len(candidates) > 1 and occurrence is None:
            raise EditError(f"text {old!r} occurs {len(candidates)} times in shape {shape_id}; choose one")
        p, _ = candidates[occurrence or 0]
        k = sum(1 for q, _ in candidates[: (occurrence or 0)] if q is p)
        result = replace_once(p, old, new, DRAWING, occurrence=k if len(find_all(p, old, DRAWING)) > 1 else None)
        self._merged = self._merged or result.formats_merged
        self._dirty.add(part)
        return result

    def edit_notes(self, slide: int, old: str, new: str, occurrence: int | None = None) -> Replacement:
        part, _ = self._slide(slide)
        notes = [v[1] for v in rels_for(self.pkg, part).values() if v[0] == "notesSlide"]
        if not notes:
            raise EditError(f"slide {slide} has no notes")
        root = self._root(notes[0])
        candidates = [(p, h) for p in root.iter(_a("p")) for h in find_all(p, old, DRAWING)]
        if not candidates:
            raise EditError(f"text {old!r} not found in the notes of slide {slide}")
        if len(candidates) > 1 and occurrence is None:
            raise EditError(f"text {old!r} occurs {len(candidates)} times in the notes; choose one")
        p, _ = candidates[occurrence or 0]
        k = sum(1 for q, _ in candidates[: (occurrence or 0)] if q is p)
        result = replace_once(p, old, new, DRAWING, occurrence=k if len(find_all(p, old, DRAWING)) > 1 else None)
        self._merged = self._merged or result.formats_merged
        self._dirty.add(notes[0])
        return result

    # ---- charts ----
    def _chart_part(self, slide: int, shape_id: int) -> tuple[str, etree._Element]:
        part, root = self._slide(slide)
        gf = self.shape(root, shape_id)
        ref = gf.find(".//{%s}chart" % C_NS)
        if ref is None:
            raise EditError(f"shape {shape_id} on slide {slide} is not a chart")
        rid = ref.get("{%s}id" % R_NS)
        rels = rels_for(self.pkg, part)
        if rid not in rels:
            raise EditError("chart relationship not found")
        cpart = rels[rid][1]
        return cpart, self._root(cpart)

    def chart_shapes(self) -> list[tuple[int, str, int, str]]:
        """Every chart in the deck as (slide number, slide stable id, shape id, shape name), in slide and document order."""
        uids = self.slide_uids()
        out = []
        for si in range(1, len(self.slide_parts()) + 1):
            _, root = self._slide(si)
            for gf in root.iter("{%s}graphicFrame" % P_NS):
                if gf.find(".//{%s}chart" % C_NS) is None:
                    continue
                nv = gf.find("./{%s}nvGraphicFramePr/{%s}cNvPr" % (P_NS, P_NS))
                out.append((si, uids[si - 1] if si - 1 < len(uids) else "", int(nv.get("id")), nv.get("name") or ""))
        return out

    def chart_writable(self, slide: int, shape_id: int) -> bool:
        """Can this chart's values be written back? Only when exactly one workbook is embedded in it; a chart whose data lives in an external file, or only in the chart itself, is not."""
        try:
            cpart, _ = self._chart_part(slide, shape_id)
        except EditError:
            return False
        return len([v for v in rels_for(self.pkg, cpart).values() if v[0] == "package"]) == 1

    def chart_series(self, slide: int, shape_id: int) -> list[ChartSeries]:
        _, croot = self._chart_part(slide, shape_id)
        out = []
        for ser in croot.iter("{%s}ser" % C_NS):
            cats = [pt.findtext("{%s}v" % C_NS) or "" for pt in ser.xpath("./c:cat//c:pt", namespaces=NS)]
            vals_el = ser.xpath("./c:val//c:pt", namespaces=NS)
            count = max([int(p.get("idx")) for p in vals_el] + [-1]) + 1
            vals: list[float | None] = [None] * count
            for pt in vals_el:
                vals[int(pt.get("idx"))] = float(pt.findtext("{%s}v" % C_NS))
            name = ser.xpath("string(./c:tx//c:v)", namespaces=NS) or None
            cf = ser.xpath("string(./c:cat//c:f)", namespaces=NS) or None
            vf = ser.xpath("string(./c:val//c:f)", namespaces=NS) or None
            out.append(ChartSeries(name, tuple(cats), tuple(vals), cf, vf))
        return out

    def set_chart_value(self, slide: int, shape_id: int, series: int, category: str, new: float) -> None:
        """Change one data point in the cache and in the embedded workbook. All or nothing."""
        cpart, croot = self._chart_part(slide, shape_id)
        sers = list(croot.iter("{%s}ser" % C_NS))
        if not 0 <= series < len(sers):
            raise EditError(f"series {series} does not exist")
        ser = sers[series]
        cats = [pt.findtext("{%s}v" % C_NS) or "" for pt in ser.xpath("./c:cat//c:pt", namespaces=NS)]
        if cats.count(category) != 1:
            raise EditError(f"category {category!r} matches {cats.count(category)} points; refusing")
        idx = cats.index(category)
        pts = ser.xpath("./c:val//c:numCache/c:pt[@idx=$i]", namespaces=NS, i=str(idx))
        if len(pts) != 1:
            raise EditError("the series has no cached point for this category")
        formula = ser.xpath("string(./c:val//c:f)", namespaces=NS)
        sheet, cell = _cell_for(formula, idx)
        xparts = [v[1] for v in rels_for(self.pkg, cpart).values() if v[0] == "package"]
        if len(xparts) != 1:
            raise EditError("chart has no single embedded workbook (external or missing); refusing")
        xpart = xparts[0]
        wb_bytes = self._blobs.get(xpart) or self.pkg.read(xpart)
        current = read_cell(open_package(wb_bytes), sheet, cell)
        old_cached = pts[0].findtext("{%s}v" % C_NS)
        if current.formula is not None:
            raise EditError(f"workbook cell {sheet}!{cell} holds a formula; not overwritten")
        if current.value is None or abs(float(current.value) - float(old_cached)) > 1e-9 * max(1.0, abs(float(old_cached))):
            raise EditError(f"workbook cell {sheet}!{cell} ({current.value}) is out of step with the chart cache ({old_cached}); refusing")
        new_wb = patch_numeric_cell(wb_bytes, sheet, cell, new)
        pts[0].find("{%s}v" % C_NS).text = repr(float(new)) if not float(new).is_integer() else str(int(new))
        self._blobs[xpart] = new_wb
        self._dirty.add(cpart)

    # ---- output ----
    def serialize(self) -> tuple[bytes, EditReport]:
        replacements: dict[str, bytes] = {}
        for part in sorted(self._dirty):
            replacements[part] = serialize_xml(self._xml[part])
        replacements.update(self._blobs)
        out = rewrite(self.pkg, replacements)
        return out, EditReport(tuple(sorted(replacements)), self._merged)


def _cell_for(formula: str, idx: int) -> tuple[str, str]:
    if "!" not in formula:
        raise EditError(f"series formula {formula!r} does not point into a sheet")
    sheet, rng = formula.rsplit("!", 1)
    sheet = sheet.strip("'").replace("''", "'")
    start = rng.split(":")[0]
    col, row = split_cell(start)
    end = rng.split(":")[-1]
    ecol, erow = split_cell(end)
    if col == ecol:  # a column vector
        return sheet, f"{col}{row + idx}"
    if row == erow:  # a row vector
        return sheet, f"{_col_name(_col_index(col) + idx)}{row}"
    raise EditError(f"series range {rng!r} is not a single row or column")


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _col_name(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
