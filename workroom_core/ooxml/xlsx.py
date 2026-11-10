"""Minimal, safe SpreadsheetML reading and cell patching on top of the package layer.

Reading returns values, formulas, cached values and hidden state; patching changes one numeric cell in place
(refusing formula cells) and keeps every other part of the workbook byte-identical.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from lxml import etree

from .package import PackageError

from .package import Package, open_package, rewrite
from .runs import EditError

S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)

_CELL_RE = re.compile(r"^\$?([A-Z]{1,3})\$?([0-9]{1,7})$")


def parse_xml(data: bytes) -> etree._Element:
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise PackageError(f"an XML part cannot be read safely: {str(exc)[:80]}") from exc


_STRICT_TO_TRANSITIONAL = (
    (b"http://purl.oclc.org/ooxml/spreadsheetml/main", b"http://schemas.openxmlformats.org/spreadsheetml/2006/main"),
    (b"http://purl.oclc.org/ooxml/officeDocument/relationships", b"http://schemas.openxmlformats.org/officeDocument/2006/relationships"),
    (b"http://purl.oclc.org/ooxml/drawingml/main", b"http://schemas.openxmlformats.org/drawingml/2006/main"),
)


def is_strict(data: bytes) -> bool:
    return b"purl.oclc.org/ooxml" in data


def parse_xml_read(data: bytes) -> etree._Element:
    """For reading only: Strict Open XML (ISO 29500 strict namespaces) is read as if it used the usual names. Never serialise the result back."""
    if is_strict(data):
        for strict, usual in _STRICT_TO_TRANSITIONAL:
            data = data.replace(strict, usual)
    return parse_xml(data)


def serialize_xml(root: etree._Element) -> bytes:
    body = etree.tostring(root, encoding="UTF-8", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + body


def split_cell(ref: str) -> tuple[str, int]:
    m = _CELL_RE.match(ref.strip())
    if not m:
        raise EditError(f"bad cell reference {ref!r}")
    return m.group(1), int(m.group(2))


def rels_for(pkg: Package, part: str) -> dict[str, tuple[str, str]]:
    """Relationship id -> (relationship type tail, resolved part name)."""
    rp = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if rp not in pkg.by_name:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for r in parse_xml(pkg.read(rp)):
        target = r.get("Target") or ""
        if r.get("TargetMode") == "External":
            continue
        full = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        out[r.get("Id") or ""] = ((r.get("Type") or "").rsplit("/", 1)[-1], full)
    return out


@dataclass(frozen=True)
class Cell:
    ref: str
    value: str | None
    formula: str | None
    kind: str | None  # the t attribute: s, str, b, e, inlineStr, n or None


@dataclass
class Sheet:
    name: str
    part: str
    state: str  # visible, hidden, veryHidden


def sheets(pkg: Package) -> list[Sheet]:
    wb = parse_xml_read(pkg.read("xl/workbook.xml"))
    rels = rels_for(pkg, "xl/workbook.xml")
    out = []
    for s in wb.iter("{%s}sheet" % S_NS):
        rid = s.get("{%s}id" % R_NS)
        if rid in rels:
            out.append(Sheet(s.get("name") or "", rels[rid][1], s.get("state") or "visible"))
    return out


def shared_strings(pkg: Package) -> list[str]:
    if "xl/sharedStrings.xml" not in pkg.by_name:
        return []
    root = parse_xml_read(pkg.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter("{%s}t" % S_NS)) for si in root.iter("{%s}si" % S_NS)]


def read_cell(pkg: Package, sheet_name: str, ref: str) -> Cell:
    sh = next((s for s in sheets(pkg) if s.name == sheet_name), None)
    if sh is None:
        raise EditError(f"sheet {sheet_name!r} not found")
    root = parse_xml_read(pkg.read(sh.part))
    c = root.xpath("//x:c[@r=$r]", namespaces={"x": S_NS}, r=ref.replace("$", ""))
    if not c:
        return Cell(ref, None, None, None)
    c = c[0]
    v = c.find("{%s}v" % S_NS)
    f = c.find("{%s}f" % S_NS)
    kind = c.get("t")
    value = v.text if v is not None else None
    if kind == "s" and value is not None:
        value = shared_strings(pkg)[int(value)]
    elif kind == "inlineStr":
        value = "".join(t.text or "" for t in c.iter("{%s}t" % S_NS))
    return Cell(ref, value, f.text if f is not None and f.text else ("" if f is not None else None), kind)


def patch_numeric_cell(workbook: bytes, sheet_name: str, ref: str, value: float | int | str) -> bytes:
    """Return the workbook with one numeric cell changed. Formula, text and missing cells are refused."""
    pkg = open_package(workbook)
    sh = next((s for s in sheets(pkg) if s.name == sheet_name), None)
    if sh is None:
        raise EditError(f"sheet {sheet_name!r} not found")
    if is_strict(pkg.read(sh.part)):
        raise EditError("a Strict Open XML workbook is read but never edited")
    root = parse_xml(pkg.read(sh.part))
    found = root.xpath("//x:c[@r=$r]", namespaces={"x": S_NS}, r=ref.replace("$", ""))
    if not found:
        raise EditError(f"cell {ref} does not exist in {sheet_name!r}")
    c = found[0]
    if c.find("{%s}f" % S_NS) is not None:
        raise EditError(f"cell {ref} holds a formula; the formula is the source of truth and is not overwritten")
    if c.get("t") not in (None, "n"):
        raise EditError(f"cell {ref} is not numeric (type {c.get('t')!r})")
    v = c.find("{%s}v" % S_NS)
    if v is None:
        v = etree.SubElement(c, "{%s}v" % S_NS)
    v.text = _num(value)
    return rewrite(pkg, {sh.part: serialize_xml(root)})


def _num(value: float | int | str) -> str:
    if isinstance(value, bool):
        raise EditError("boolean is not a number")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    float(value)  # validates
    return str(value)


# ---- bulk reading with labels, for matching ----
@dataclass(frozen=True, slots=True)
class SourceCell:
    sheet: str
    ref: str
    row: int
    col: int
    value: float
    is_formula: bool
    is_date: bool
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    hidden: bool
    file: str = ""


def _col_to_int(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _date_style_ids(pkg: Package) -> set[int]:
    if "xl/styles.xml" not in pkg.by_name:
        return set()
    root = parse_xml_read(pkg.read("xl/styles.xml"))
    custom = {}
    for nf in root.iter("{%s}numFmt" % S_NS):
        code = (nf.get("formatCode") or "").lower()
        stripped = re.sub(r'"[^"]*"|\[[^\]]*\]|\.', "", code)
        custom[int(nf.get("numFmtId"))] = bool(re.search(r"[ymdhs]", stripped)) and "0" not in stripped.replace("0.0", "")
    builtin_dates = set(range(14, 23)) | set(range(45, 48))
    out = set()
    xfs = root.find("{%s}cellXfs" % S_NS)
    if xfs is not None:
        for i, xf in enumerate(xfs):
            nid = int(xf.get("numFmtId") or 0)
            if nid in builtin_dates or custom.get(nid):
                out.add(i)
    return out


def _hidden_columns(root: etree._Element) -> set[int]:
    out: set[int] = set()
    for col in root.iter("{%s}col" % S_NS):
        if col.get("hidden") in ("1", "true"):
            lo, hi = int(col.get("min") or 0), int(col.get("max") or 0)
            if lo and hi - lo < 20_000:
                out.update(range(lo, hi + 1))
    return out


def _col_letters(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def is_label_text(text: str) -> bool:
    """Whether a text cell can serve as a heading: it holds at least one letter or digit. The dashes that financial statements print for nil, and unit marks such as $,
    stood between a figure and its row heading and used to be read as the heading."""
    return any(ch.isalnum() for ch in text)


def _merged_ranges(root) -> list[tuple[int, int, int, int]]:
    """Merged areas of a sheet as (first row, first column, last row, last column)."""
    out = []
    for m in root.iter("{%s}mergeCell" % S_NS):
        ref = m.get("ref") or ""
        try:
            a, b = ref.split(":")
            (ca, ra), (cb, rb) = split_cell(a), split_cell(b)
            out.append((ra, _col_to_int(ca), rb, _col_to_int(cb)))
        except (ValueError, EditError):
            continue
    return out


_FOOTNOTED_NUMBER = re.compile(r"^(?P<open>\()?(?P<sign>[-–])?\$?(?P<num>\d[\d,]*(?:\.\d+)?)(?P<close>\))?(?:\s?\(\s?(?:[ivxlcdm]{1,5}|[a-z])\s?\))+$", re.IGNORECASE)


def footnoted_number(text: str) -> float | None:
    """The value of a cell that holds a figure typed as text with a footnote mark after it ("14,263(i)", "(2,345)(ii)"), else None.

    Statements often carry the mark inside the cell, so the cell reads as text and would otherwise be taken for a heading. A bare year with a
    mark ("2025(a)") stays a heading."""
    m = _FOOTNOTED_NUMBER.match(text.strip())
    if m is None:
        return None
    digits = m.group("num")
    if re.fullmatch(r"(?:19|20)\d\d", digits):
        return None
    value = float(digits.replace(",", ""))
    return -value if (m.group("sign") or (m.group("open") and m.group("close"))) else value


_YEARS = range(1950, 2101)


def _is_year(value: float) -> bool:
    return float(value).is_integer() and int(value) in _YEARS


def _year_headings(numbers: list, strings: dict[tuple[int, int], str]) -> tuple[dict, list[tuple[int, int]]]:
    """Years printed as numbers that act as headings. ``header_years`` maps a column to its (row, year) headings, taken from rows whose every number is a
    year (a heading row such as 2024 | 2023 above a column of figures); ``dividers`` lists (row, year) for a year alone on its row at the left edge, which opens a block of rows."""
    by_row: dict[int, list] = {}
    for n in numbers:
        by_row.setdefault(n[0], []).append(n)
    text_rows = {r for r, _ in strings}
    header_years: dict = {"cells": set()}
    dividers: list[tuple[int, int]] = []
    for r, cells in by_row.items():
        if not all(_is_year(n[3]) and not n[5] for n in cells):
            continue
        if len(cells) == 1 and cells[0][1] <= 2 and r not in text_rows:
            dividers.append((r, int(cells[0][3])))
            continue
        for n in cells:
            header_years.setdefault(n[1], []).append((r, int(n[3])))
            header_years["cells"].add((r, n[1]))
    for key, vals in header_years.items():
        if key != "cells":
            vals.sort()
    dividers.sort()
    return header_years, dividers


def _nearest_above(entries: list[tuple[int, int]] | None, row: int) -> int | None:
    if not entries:
        return None
    hit = None
    for r, y in entries:
        if r < row:
            hit = y
        else:
            break
    return hit


HEADING_GAP = 3  # rows between two headings of one block: a blank row or two may sit inside a heading, a data row never does


def _nearest_heading_block(above: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The headings of the block a cell belongs to. A sheet that stacks several tables repeats its column headings above each; the headings of an earlier
    block (their groups, their periods) are not this cell's, so only the run of headings closest above the cell is kept."""
    if len(above) < 2:
        return above
    start = len(above) - 1
    while start > 0 and above[start][0] - above[start - 1][0] <= HEADING_GAP:
        start -= 1
    return above[start:]


def index_workbook(pkg: Package, max_cells: int = 500_000, file: str = "", stats: dict | None = None) -> list[SourceCell]:
    """Every numeric cell with the text labels on its row and column. Dates are flagged; cells in hidden rows, hidden columns and hidden
    sheets are flagged hidden. Rows and cells that omit their position (legal in the format) are placed in reading order. When ``stats`` is
    given, ``stats["uncalculated"]`` counts formula cells that carry no saved value (a file written by a program that does not calculate): they
    cannot be read until Excel opens and saves the file."""
    sst = shared_strings(pkg)
    date_styles = _date_style_ids(pkg)
    out: list[SourceCell] = []
    for sh in sheets(pkg):
        root = parse_xml_read(pkg.read(sh.part))
        sheet_hidden = sh.state != "visible"
        hidden_cols = _hidden_columns(root)
        strings: dict[tuple[int, int], str] = {}
        numbers: list[tuple[int, int, str, float, bool, bool, bool]] = []
        row_n = 0
        for row in root.iter("{%s}row" % S_NS):
            row_n = int(row.get("r")) if (row.get("r") or "").isdigit() else row_n + 1
            hidden = row.get("hidden") in ("1", "true")
            col_n = 0
            for c in row.iter("{%s}c" % S_NS):
                ref = c.get("r") or ""
                try:
                    col_s, at_row = split_cell(ref)
                    col_n = _col_to_int(col_s)
                    cell_row = at_row
                except EditError:
                    col_n += 1
                    cell_row = row_n
                    ref = f"{_col_letters(col_n)}{cell_row}"
                kind = c.get("t")
                v = c.find("{%s}v" % S_NS)
                f = c.find("{%s}f" % S_NS)
                if stats is not None and f is not None and (v is None or v.text in (None, "")) and kind != "inlineStr":
                    stats["uncalculated"] = stats.get("uncalculated", 0) + 1
                if kind == "s" and v is not None and v.text is not None:
                    strings[(cell_row, col_n)] = sst[int(v.text)].strip()
                elif kind == "inlineStr":
                    strings[(cell_row, col_n)] = "".join(t.text or "" for t in c.iter("{%s}t" % S_NS)).strip()
                elif kind == "str" and v is not None and v.text:
                    strings[(cell_row, col_n)] = v.text.strip()
                elif kind in (None, "n") and v is not None and v.text not in (None, ""):
                    try:
                        val = float(v.text)
                    except ValueError:
                        continue
                    style = int(c.get("s") or 0)
                    numbers.append((cell_row, col_n, ref, val, f is not None, style in date_styles, hidden or sheet_hidden or col_n in hidden_cols))
        dividers_at: set[tuple[int, int]] = set()  # cells a section title (a row-wide merge from the first column) was spread over
        for lo_r, lo_c, hi_r, hi_c in _merged_ranges(root):
            text = strings.get((lo_r, lo_c))
            if text is None or (hi_r - lo_r + 1) * (hi_c - lo_c + 1) > 4096:
                continue
            title = lo_c == 1 and hi_c - lo_c >= 2
            for rr in range(lo_r, hi_r + 1):
                for cc in range(lo_c, hi_c + 1):
                    if strings.setdefault((rr, cc), text) is text and title and cc != lo_c:
                        dividers_at.add((rr, cc))  # a merged heading heads every column (or row) it spans, not only the corner that holds its text
        rows_by: dict[int, list[tuple[int, str]]] = {}
        cols_by: dict[int, list[tuple[int, str]]] = {}
        for (r, c), s in strings.items():
            typed = footnoted_number(s)
            if typed is not None:
                numbers.append((r, c, f"{_col_letters(c)}{r}", typed, False, False, sheet_hidden or c in hidden_cols))
                continue
            if is_label_text(s):  # a dash, a dollar sign or a bracket in a cell is a placeholder, not a heading
                rows_by.setdefault(r, []).append((c, s))
                cols_by.setdefault(c, []).append((r, s))
        share: dict[tuple[str, ...], tuple[str, ...]] = {}  # cells of one row or column hold the same label tuples; keep one copy of each
        header_years, dividers = _year_headings(numbers, strings)
        for r_, c_, ref, val, isf, isd, hid in numbers:
            row_labels = tuple(s for cc, s in sorted(rows_by.get(r_, []), key=lambda t: -t[0]) if cc < c_)[:3]
            above = sorted((rr, s) for rr, s in cols_by.get(c_, []) if rr < r_)
            block = _nearest_heading_block([(rr, s) for rr, s in above if (rr, c_) not in dividers_at])
            col_labels = tuple(dict.fromkeys([s for _, s in reversed(above)][:2] + ([block[0][1]] if block else [])))
            year = _nearest_above(header_years.get(c_), r_)
            if year is not None and (r_, c_) not in header_years.get("cells", ()):
                col_labels = tuple(dict.fromkeys(col_labels + (str(year),)))  # a year printed as a number heads its column like a year printed as text
            elif year is None:
                block = _nearest_above(dividers, r_)
                if block is not None:
                    row_labels = tuple(dict.fromkeys(row_labels + (str(block),)))  # a year alone on its row opens a block of rows
            row_labels = share.setdefault(row_labels, row_labels)
            col_labels = share.setdefault(col_labels, col_labels)
            out.append(SourceCell(sh.name, ref, r_, c_, val, isf, isd, row_labels, col_labels, hid, file))
            if len(out) >= max_cells:
                return out
    return out
