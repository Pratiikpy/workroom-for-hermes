"""Every figure of a Word report keyed by (section number, row heading, column heading chain, nth), read with python-docx and independent of the product's reader.

The column heading chain is the text of the table's header rows above that column, with years and unit marks removed and merged cells repeated, so a table
whose columns were regrouped between two years (a group dropped, a group added) still lines up by the group's name. Used only to score a refreshed copy
against the department's own report for the next year.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

_SECTION = re.compile(r"^\s*(\d+(?:\.\d+)+)")
_FIGURE = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
_YEAR = re.compile(r"\b(?:19|20)\d{2}(?:-\d{2})?\b")


def _norm(text: str) -> str:
    text = _YEAR.sub(" ", text.lower())
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\$|’000|'000|’000|�000|000", " ", text)
    return re.sub(r"[^a-z]+", " ", text).strip()


def _is_figure(text: str) -> bool:
    t = text.strip().replace("\xa0", "")
    return bool(t) and bool(_FIGURE.match(t)) and not _YEAR.fullmatch(t) and any(ch.isdigit() for ch in t)


def figures_grouped(path: Path) -> dict[tuple, str]:
    d = docx.Document(str(path))
    out: dict[tuple, str] = {}
    seen: collections.Counter = collections.Counter()
    section = ""
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            m = _SECTION.match(Paragraph(child, d).text)
            if m:
                section = m.group(1)
            continue
        if tag != "tbl":
            continue
        t = Table(child, d)
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        first_data = next((i for i, r in enumerate(rows) if sum(_is_figure(x) for x in r[1:]) >= 2), None)
        if first_data is None or not section:
            continue
        headers = []
        for j in range(len(rows[0])):
            parts = [_norm(rows[i][j]) for i in range(min(first_data, 4)) if j < len(rows[i])]
            headers.append(" | ".join(p for p in dict.fromkeys(parts) if p))
        for r in rows[first_data:]:
            head = _norm(r[0])
            if not head:
                continue
            for j, cell in enumerate(r):
                if j == 0 or not _is_figure(cell):
                    continue
                key = (section, head, headers[j] if j < len(headers) else "")
                n = seen[key]
                seen[key] += 1
                out[key + (n,)] = cell.strip()
    return out
