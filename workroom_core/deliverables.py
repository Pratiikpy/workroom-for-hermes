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


def preview(data: bytes, kind: str, path: str, page: int = 1) -> dict:
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
    if kind in ("word", "powerpoint"):
        text = text_of(data, kind)
        return {"kind": "text", "text": text or "", "truncated": False, "review_room": True} if text is not None else {"kind": "none", "why": "the file could not be read"}
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
