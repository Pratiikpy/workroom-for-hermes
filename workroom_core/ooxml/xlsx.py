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
    wb = parse_xml(pkg.read("xl/workbook.xml"))
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
    root = parse_xml(pkg.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter("{%s}t" % S_NS)) for si in root.iter("{%s}si" % S_NS)]


def read_cell(pkg: Package, sheet_name: str, ref: str) -> Cell:
    sh = next((s for s in sheets(pkg) if s.name == sheet_name), None)
    if sh is None:
        raise EditError(f"sheet {sheet_name!r} not found")
    root = parse_xml(pkg.read(sh.part))
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
@dataclass(frozen=True)
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
    root = parse_xml(pkg.read("xl/styles.xml"))
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


def index_workbook(pkg: Package, max_cells: int = 500_000, file: str = "") -> list[SourceCell]:
    """Every numeric cell with the text labels on its row and column. Dates are flagged, hidden rows noted."""
    sst = shared_strings(pkg)
    date_styles = _date_style_ids(pkg)
    out: list[SourceCell] = []
    for sh in sheets(pkg):
        root = parse_xml(pkg.read(sh.part))
        strings: dict[tuple[int, int], str] = {}
        numbers: list[tuple[int, int, str, float, bool, bool, bool]] = []
        for row in root.iter("{%s}row" % S_NS):
            hidden = row.get("hidden") in ("1", "true")
            for c in row.iter("{%s}c" % S_NS):
                ref = c.get("r") or ""
                try:
                    col_s, row_n = split_cell(ref)
                except EditError:
                    continue
                col_n = _col_to_int(col_s)
                kind = c.get("t")
                v = c.find("{%s}v" % S_NS)
                f = c.find("{%s}f" % S_NS)
                if kind == "s" and v is not None and v.text is not None:
                    strings[(row_n, col_n)] = sst[int(v.text)].strip()
                elif kind == "inlineStr":
                    strings[(row_n, col_n)] = "".join(t.text or "" for t in c.iter("{%s}t" % S_NS)).strip()
                elif kind == "str" and v is not None and v.text:
                    strings[(row_n, col_n)] = v.text.strip()
                elif kind in (None, "n") and v is not None and v.text not in (None, ""):
                    try:
                        val = float(v.text)
                    except ValueError:
                        continue
                    style = int(c.get("s") or 0)
                    numbers.append((row_n, col_n, ref, val, f is not None, style in date_styles, hidden))
        rows_by: dict[int, list[tuple[int, str]]] = {}
        cols_by: dict[int, list[tuple[int, str]]] = {}
        for (r, c), s in strings.items():
            if s:
                rows_by.setdefault(r, []).append((c, s))
                cols_by.setdefault(c, []).append((r, s))
        for r_, c_, ref, val, isf, isd, hid in numbers:
            row_labels = tuple(s for cc, s in sorted(rows_by.get(r_, []), key=lambda t: -t[0]) if cc < c_)[:3]
            above = sorted((rr, s) for rr, s in cols_by.get(c_, []) if rr < r_)
            col_labels = tuple(dict.fromkeys([s for _, s in reversed(above)][:2] + ([above[0][1]] if above else [])))
            out.append(SourceCell(sh.name, ref, r_, c_, val, isf, isd, row_labels, col_labels, hid, file))
            if len(out) >= max_cells:
                return out
    return out
