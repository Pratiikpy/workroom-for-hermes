"""Deliverables: every file the agent produced or changed in a project, shown as it is, compared with earlier versions, and approved by the owner.

A file becomes a deliverable when a tool changed it (the snapshot store saw it) or when the agent registers it (for files made by shell commands or scripts).
Versions are the before-images the snapshot store kept plus the file as it is now. Preview and compare work per kind: text-like files as text, images as
images, PDF pages as images, Word and PowerPoint as their text (the Review Room draws them as Office does), Excel as a grid of the first sheet. Nothing here
writes to the user's folder.
"""

from __future__ import annotations

import base64
import difflib
import io
import re
from pathlib import Path

from lxml import etree

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".yaml", ".yml", ".toml", ".ini", ".log", ".py", ".js", ".ts", ".css", ".sql", ".rst"}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
MAX_TEXT = 200_000
MAX_IMAGE = 5 * 1024 * 1024
GRID_ROWS = 60
GRID_COLS = 15
S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXT:
        return "text"
    if ext in IMAGE_EXT:
        return "image"
    return {".pdf": "pdf", ".docx": "word", ".pptx": "powerpoint", ".xlsx": "excel"}.get(ext, "other")


def _word_text(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            lines.append(" | ".join(c.text for c in row.cells))
    return "\n".join(lines)


def _powerpoint_text(data: bytes) -> str:
    from pptx import Presentation

    out = []
    for i, slide in enumerate(Presentation(io.BytesIO(data)).slides, 1):
        out.append(f"--- slide {i}")
        for shape in slide.shapes:
            if shape.has_text_frame:
                out += [p.text for p in shape.text_frame.paragraphs if p.text]
            if getattr(shape, "has_table", False) and shape.has_table:
                out += [" | ".join(c.text for c in row.cells) for row in shape.table.rows]
    return "\n".join(out)


def excel_grid(data: bytes, sheet_index: int = 0) -> dict:
    """The first rows and columns of one sheet as text, values as saved by the program that wrote the file."""
    from .ooxml.package import open_package
    from .ooxml.xlsx import parse_xml_read, sheets, shared_strings, split_cell

    pkg = open_package(data)
    all_sheets = sheets(pkg)
    if not all_sheets:
        return {"sheets": [], "rows": []}
    sh = all_sheets[min(sheet_index, len(all_sheets) - 1)]
    sst = shared_strings(pkg)
    root = parse_xml_read(pkg.read(sh.part))
    grid: dict[int, dict[int, str]] = {}
    for c in root.iter("{%s}c" % S_NS):
        try:
            col_s, row = split_cell(c.get("r") or "")
        except Exception:  # noqa: BLE001  a cell without a position is skipped in the preview
            continue
        col = 0
        for ch in col_s:
            col = col * 26 + (ord(ch) - 64)
        if row > GRID_ROWS or col > GRID_COLS:
            continue
        v = c.find("{%s}v" % S_NS)
        kind = c.get("t")
        if kind == "s" and v is not None and v.text is not None:
            text = sst[int(v.text)] if int(v.text) < len(sst) else ""
        elif kind == "inlineStr":
            text = "".join(t.text or "" for t in c.iter("{%s}t" % S_NS))
        else:
            text = v.text if v is not None and v.text is not None else ""
        grid.setdefault(row, {})[col] = text
    width = max((max(r) for r in grid.values() if r), default=0)
    rows = [[grid.get(r, {}).get(c, "") for c in range(1, width + 1)] for r in range(1, (max(grid) if grid else 0) + 1)]
    return {"sheets": [s.name for s in all_sheets], "sheet": sh.name, "rows": rows}


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main", "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
       "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _xml(z, name: str):
    return etree.fromstring(z.read(name), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))


def _marked(text: str, figures: list[str]) -> str:
    """Escaped text with each linked figure wrapped in an underlined, green span (the first occurrence of each, left to right)."""
    spans: list[tuple[int, int]] = []
    for fig in sorted(set(f for f in figures if f), key=len, reverse=True):
        at = text.find(fig)
        if at >= 0 and not any(a < at + len(fig) and at < b for a, b in spans):
            spans.append((at, at + len(fig)))
    out, pos = [], 0
    for a, b in sorted(spans):
        out.append(_esc(text[pos:a]))
        out.append(f'<tspan fill="#047857" font-weight="700" text-decoration="underline">{_esc(text[a:b])}</tspan>')
        pos = b
    out.append(_esc(text[pos:]))
    return "".join(out)


def slides_svg(data: bytes, limit: int = 60, marks: dict[int, list[str]] | None = None) -> list[dict]:
    """Each slide drawn from its shapes' own positions and sizes as an SVG: boxes, text at its font size, tables as grids. Read straight from the file's XML
    (no PowerPoint, no python-pptx), structural rather than typeset: line breaks and fonts are approximate, and the page says so. Text is escaped; nothing
    from the file is executed. ``marks`` maps a slide number to the figures on it that are linked to a source; each is drawn underlined in green."""
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(data))
    pres = _xml(z, "ppt/presentation.xml")
    size = pres.find(".//p:sldSz", _NS)
    W, H = int(size.get("cx")), int(size.get("cy"))
    rels = {r.get("Id"): r.get("Target") for r in _xml(z, "ppt/_rels/presentation.xml.rels").findall("rel:Relationship", _NS)}
    order = [rels[sid.get(f"{{{_NS['r']}}}id")] for sid in pres.findall(".//p:sldId", _NS) if sid.get(f"{{{_NS['r']}}}id") in rels]
    px = 960.0 / W
    out = []
    for si, target in enumerate(order[:limit], 1):
        root = _xml(z, "ppt/" + target.lstrip("/").removeprefix("ppt/") if not target.startswith("/") else target.lstrip("/"))
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 {H * px:.0f}" width="100%" role="img" aria-label="Slide {si}"><rect width="960" height="{H * px:.0f}" fill="#fff" stroke="#d1d5db"/>']
        for node in root.find(".//p:spTree", _NS):
            xfrm = node.find(".//a:xfrm", _NS) if node.tag.endswith("}sp") else node.find("p:xfrm", _NS)
            if xfrm is None or xfrm.find("a:off", _NS) is None or xfrm.find("a:ext", _NS) is None:
                continue
            off, ext = xfrm.find("a:off", _NS), xfrm.find("a:ext", _NS)
            x, y, w, h = int(off.get("x")) * px, int(off.get("y")) * px, int(ext.get("cx")) * px, int(ext.get("cy")) * px
            if node.find(".//a:tbl", _NS) is not None:
                rows = node.findall(".//a:tr", _NS)
                rh = h / max(1, len(rows))
                for ri, tr in enumerate(rows):
                    cells = tr.findall("a:tc", _NS)
                    cw = w / max(1, len(cells))
                    for ci, tc in enumerate(cells):
                        txt = "".join(t.text or "" for t in tc.iter(f"{{{_NS['a']}}}t"))
                        parts.append(f'<rect x="{x + ci * cw:.1f}" y="{y + ri * rh:.1f}" width="{cw:.1f}" height="{rh:.1f}" fill="{"#f3f4f6" if ri == 0 else "#fff"}" stroke="#d1d5db"/>')
                        parts.append(f'<text x="{x + ci * cw + 4:.1f}" y="{y + ri * rh + rh * 0.65:.1f}" font-size="{min(14, rh * 0.5):.0f}" fill="#111827">{_esc(txt[:40])}</text>')
                continue
            if node.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}chart") is not None:
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#f9fafb" stroke="#9ca3af" stroke-dasharray="4"/><text x="{x + 8:.1f}" y="{y + 20:.1f}" font-size="13" fill="#6b7280">chart</text>')
                continue
            fill = node.find("p:spPr/a:solidFill/a:srgbClr", _NS)
            if fill is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", fill.get("val") or ""):
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#{fill.get("val")}" stroke="#e5e7eb"/>')
            ty = y
            for para in node.findall(".//a:p", _NS):
                runs = para.findall("a:r", _NS)
                txt = "".join((r.find("a:t", _NS).text or "") if r.find("a:t", _NS) is not None else "" for r in runs)
                if not txt:
                    continue
                szs = [int(r.find("a:rPr", _NS).get("sz")) for r in runs if r.find("a:rPr", _NS) is not None and (r.find("a:rPr", _NS).get("sz") or "").isdigit()]
                pt = (max(szs) / 100.0) if szs else 18.0
                size = max(8.0, min(pt * 12700 * px, 60.0))
                ty += size * 1.25
                col = None
                for r in runs:
                    c = r.find("a:rPr/a:solidFill/a:srgbClr", _NS)
                    if c is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", c.get("val") or ""):
                        col = "#" + c.get("val")
                        break
                parts.append(f'<text x="{x + 6:.1f}" y="{ty:.1f}" font-size="{size:.0f}" fill="{col or "#111827"}">{_marked(txt[:160], (marks or {}).get(si, []))}</text>')
        parts.append("</svg>")
        out.append({"slide": si, "svg": "".join(parts)})
    return out


def docx_blocks(data: bytes, limit: int = 400) -> list[dict]:
    """A Word document as plain blocks (headings, paragraphs, tables) for the structural view, read straight from the file's XML; the page draws them as text,
    never as markup from the file."""
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(data))
    body = _xml(z, "word/document.xml").find("w:body", _NS)
    w = _NS["w"]

    def text(el) -> str:
        return "".join(t.text or "" for t in el.iter(f"{{{w}}}t"))

    out: list[dict] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = text(child)
            if t.strip():
                st = child.find("w:pPr/w:pStyle", _NS)
                style = (st.get(f"{{{w}}}val") if st is not None else "") or ""
                out.append({"type": "heading" if style.lower().startswith("heading") or style.lower() == "title" else "paragraph", "text": t})
        elif tag == "tbl":
            out.append({"type": "table", "rows": [[text(tc) for tc in tr.findall("w:tc", _NS)] for tr in child.findall("w:tr", _NS)][:60]})
        if len(out) >= limit:
            break
    return out


def text_of(data: bytes, kind: str) -> str | None:
    """Text used to compare two versions; None where the kind has no meaningful text (images, unknown files)."""
    try:
        if kind == "text":
            return data[:MAX_TEXT].decode("utf-8", "replace")
        if kind == "word":
            return _word_text(data)
        if kind == "powerpoint":
            return _powerpoint_text(data)
        if kind == "excel":
            g = excel_grid(data)
            return "\n".join(" | ".join(r) for r in g["rows"])
        if kind == "pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            return "\n".join(f"--- page {i + 1}\n" + pdf[i].get_textpage().get_text_range() for i in range(min(len(pdf), 50)))
    except Exception:  # noqa: BLE001  a damaged file has no text to compare, not an error
        return None
    return None


def preview(data: bytes, kind: str, path: str, page: int = 1, marks: dict[int, list[str]] | None = None) -> dict:
    if kind == "text":
        text = data[:MAX_TEXT].decode("utf-8", "replace")
        return {"kind": "text", "text": text, "truncated": len(data) > MAX_TEXT}
    if kind == "image":
        if len(data) > MAX_IMAGE:
            return {"kind": "none", "why": "the image is larger than 5 MB"}
        return {"kind": "image", "mime": IMAGE_EXT[Path(path).suffix.lower()], "data": base64.b64encode(data).decode("ascii")}
    if kind == "pdf":
        from .render import page_count, page_png

        try:
            count = page_count(data)
            png, w, h = page_png(data, max(1, min(page, count)))
        except Exception as exc:  # noqa: BLE001
            return {"kind": "none", "why": f"the PDF could not be drawn ({type(exc).__name__})"}
        return {"kind": "image", "mime": "image/png", "data": base64.b64encode(png).decode("ascii"), "page": page, "pages": count}
    if kind == "excel":
        try:
            return {"kind": "grid", **excel_grid(data)}
        except Exception as exc:  # noqa: BLE001
            return {"kind": "none", "why": f"the workbook could not be read ({type(exc).__name__})"}
    why = ""
    if kind == "powerpoint":
        try:
            return {"kind": "slides", "slides": slides_svg(data, marks=marks), "structural": True, "marked": sum(len(v) for v in (marks or {}).values())}
        except Exception as exc:  # noqa: BLE001  a deck the reader cannot draw still has its text
            why = f" ({type(exc).__name__}: {str(exc)[:80]})"
    if kind == "word":
        try:
            return {"kind": "blocks", "blocks": docx_blocks(data), "structural": True}
        except Exception as exc:  # noqa: BLE001
            why = f" ({type(exc).__name__}: {str(exc)[:80]})"
    if kind in ("word", "powerpoint"):
        text = text_of(data, kind)
        return {"kind": "text", "text": text or "", "truncated": False, "review_room": True} if text is not None else {"kind": "none", "why": "the file could not be read" + why}
    return {"kind": "none", "why": "no preview for this kind of file"}


def diff(old: bytes | None, new: bytes | None, kind: str, old_name: str, new_name: str) -> dict:
    a = text_of(old, kind) if old is not None else ""
    b = text_of(new, kind) if new is not None else ""
    if a is None or b is None:
        return {"kind": "none", "why": "this kind of file has no text to compare", "same": old == new}
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), old_name, new_name, lineterm="", n=2))
    added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
    return {"kind": "text", "diff": "\n".join(lines[:4000]), "added": added, "removed": removed, "same": a == b}


_ = etree  # lxml is imported so a missing dependency fails at import, not halfway through a preview
