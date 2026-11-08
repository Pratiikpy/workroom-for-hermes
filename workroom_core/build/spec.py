"""A Spec is what the agent writes instead of an Office file: structure, text with fact slots, and the facts those slots read.

Validation happens before anything is built or staged. Every slot ends up with a receipt that says which source cell was chosen,
under which concept and period, in which unit and format, and on what label evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterator

from ..match.engine import periods, tokens
from ..ooxml.xlsx import SourceCell
from .formats import FormatError, format_class, format_value

KINDS = ("pptx", "docx", "scene", "xlsx")
UNITS = ("currency", "percent", "count", "ratio")
SLOT = re.compile(r"\{([A-Za-z0-9_]{1,40}):([^{}]{1,24})\}")
MAX_BLOCKS = 600
MAX_TEXT = 4000
MAX_FACTS = 400
MAX_SLIDES = 120
MAX_ROWS = 200
MAX_COLS = 20
MAX_ITEMS = 100
MAX_SPEC_CHARS = 1_000_000
BLOCK_TYPES = {
    "pptx": ("text", "bullets", "table", "chart", "kpis"),
    "docx": ("heading", "paragraph", "bullets", "table"),
}


@dataclass(frozen=True)
class SpecError:
    code: str
    where: str
    message: str


@dataclass(frozen=True)
class Slot:
    where: str  # path inside the spec, for example slides[0].blocks[1].text
    fact: str
    fmt: str
    rendered: str
    receipt: dict[str, Any]


@dataclass
class Validated:
    spec: dict[str, Any] | None = None
    slots: list[Slot] = field(default_factory=list)
    errors: list[SpecError] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    chart_points: list[dict[str, Any]] = field(default_factory=list)  # one per tied chart data point, in document order
    cell_facts: list[dict[str, Any]] = field(default_factory=list)  # one per tied workbook cell


RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def safe_relative_path(path: Any, ending: str) -> str | None:
    """Why a path is not acceptable for a new file, or None when it is. Strict on purpose: it must be safe on Windows, macOS and Linux."""
    if not isinstance(path, str) or not path:
        return "the path must be text"
    if any(ord(ch) < 32 or ch in '\\:*?"<>|' for ch in path) or path.startswith("/"):
        return "the path may not contain control characters, backslashes, colons or any of * ? \" < > |, and must be relative"
    if len(path) > 240:
        return "the path is longer than 240 characters"
    parts = path.split("/")
    for part in parts:
        if not part or part in (".", ".."):
            return "the path may not have empty, . or .. parts"
        if len(part) > 120:
            return "a name in the path is longer than 120 characters"
        if part != part.strip() or part.endswith("."):
            return "names may not start or end with a space or end with a dot"
        if part.startswith("."):
            return "hidden names are not allowed"
        if part.split(".")[0].lower() in RESERVED:
            return f"{part} is a reserved name on Windows"
    name = parts[-1]
    if not name.lower().endswith(ending) or name.lower() == ending or name.lower().startswith("workroom."):
        return f"the file name must end in {ending}, have a name before it, and not start with workroom."
    return None


def _err(v: Validated, code: str, where: str, message: str) -> None:
    v.errors.append(SpecError(code, where, message))


def iter_texts(spec: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Every piece of text in the spec that may carry slots, with its path. The renderer walks the same paths."""
    if spec["kind"] == "xlsx":
        return
    if spec["kind"] == "scene":
        for ni, node in enumerate(spec["scene"]["nodes"]):
            if node.get("type") == "text" and node.get("text"):
                yield f"scene.nodes[{ni}].text", node["text"]
    elif spec["kind"] == "pptx":
        for si, slide in enumerate(spec["slides"]):
            if slide.get("title"):
                yield f"slides[{si}].title", slide["title"]
            yield from _block_texts(slide.get("blocks", []), f"slides[{si}]")
    else:
        yield from _block_texts(spec["blocks"], "")


def _block_texts(blocks: list[dict[str, Any]], prefix: str) -> Iterator[tuple[str, str]]:
    base = f"{prefix}." if prefix else ""
    for bi, b in enumerate(blocks):
        at = f"{base}blocks[{bi}]"
        t = b.get("type")
        if t in ("text", "paragraph", "heading"):
            yield f"{at}.text", b.get("text", "")
        elif t == "bullets":
            for ii, item in enumerate(b.get("items", [])):
                yield f"{at}.items[{ii}]", item
        elif t == "table":
            for ci, c in enumerate(b.get("header", [])):
                yield f"{at}.header[{ci}]", c
            for ri, row in enumerate(b.get("rows", [])):
                for ci, c in enumerate(row):
                    yield f"{at}.rows[{ri}][{ci}]", c
        elif t == "chart":
            yield f"{at}.title", b.get("title", "")
        elif t == "kpis":
            for ii, item in enumerate(b.get("items", [])):
                for key in ("label", "value", "note"):
                    if item.get(key):
                        yield f"{at}.items[{ii}].{key}", item[key]


def _blocks_ok(v: Validated, blocks: Any, kind: str, where: str) -> int:
    prefix = f"{where}." if where else ""
    if not isinstance(blocks, list):
        _err(v, "bad_spec", where, "blocks must be a list")
        return 0
    for bi, b in enumerate(blocks):
        at = f"{prefix}blocks[{bi}]"
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES[kind]:
            _err(v, "bad_spec", at, f"block type must be one of {', '.join(BLOCK_TYPES[kind])}")
            continue
        t = b["type"]
        for key in ("text", "title"):
            if key in b and not isinstance(b[key], str):
                _err(v, "bad_spec", at, f"{key} must be text")
        if t == "bullets" and not (isinstance(b.get("items"), list) and all(isinstance(i, str) for i in b["items"])):
            _err(v, "bad_spec", at, "bullets need a list of text items")
        elif t == "bullets" and len(b["items"]) > MAX_ITEMS:
            _err(v, "too_large", at, f"at most {MAX_ITEMS} bullets in one block")
        if t == "kpis":
            items = b.get("items")
            if not (isinstance(items, list) and 1 <= len(items) <= 4 and all(isinstance(i, dict) and isinstance(i.get("value"), str) and isinstance(i.get("label"), str)
                                                                          and isinstance(i.get("note", ""), str) for i in items)):
                _err(v, "bad_spec", at, "kpis need 1 to 4 items, each with a label and a value (and an optional note)")
        if t == "table":
            ok = isinstance(b.get("header"), list) and isinstance(b.get("rows"), list) and all(isinstance(r, list) for r in b["rows"])
            ok = ok and all(isinstance(c, str) for c in b["header"]) and all(isinstance(c, str) for r in b["rows"] for c in r)
            if not ok:
                _err(v, "bad_spec", at, "tables need a header list and rows of text cells")
            elif len(b["rows"]) > MAX_ROWS or max([len(b["header"])] + [len(r) for r in b["rows"]]) > MAX_COLS:
                _err(v, "too_large", at, f"tables may have at most {MAX_ROWS} rows and {MAX_COLS} columns")
        if t == "chart":
            cats = b.get("categories")
            series = b.get("series")
            if b.get("kind") not in ("bar", "line") or not isinstance(cats, list) or not isinstance(series, list) or not series:
                _err(v, "bad_spec", at, "charts need kind bar or line, categories and series")
            elif not all(isinstance(c, str) and c for c in cats) or len(set(cats)) != len(cats):
                _err(v, "bad_spec", at, "chart categories must be distinct, non-empty text")
            elif not all(isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("facts"), list)
                         and len(x["facts"]) == len(cats) and all(isinstance(f, str) for f in x["facts"]) for x in series):
                _err(v, "bad_spec", at, "each series needs a name and one fact per category")
    return len(blocks)


def _structure(v: Validated, spec: Any) -> bool:
    if not isinstance(spec, dict) or spec.get("version") != 1:
        _err(v, "bad_spec", "", "the spec must be an object with version 1")
        return False
    try:
        import json as _json

        if len(_json.dumps(spec, default=str)) > MAX_SPEC_CHARS:
            _err(v, "too_large", "", "the spec is larger than 1 MB")
            return False
    except (TypeError, ValueError):
        _err(v, "bad_spec", "", "the spec must be plain JSON data")
        return False
    kind = spec.get("kind")
    if kind not in KINDS:
        _err(v, "bad_spec", "kind", f"kind must be one of {', '.join(KINDS)}")
        return False
    path = spec.get("path")
    ending = ".scene.json" if kind == "scene" else f".{kind}"
    why = safe_relative_path(path, ending)
    if why:
        _err(v, "bad_spec", "path", why)
        return False
    theme = spec.get("theme", {})
    if not isinstance(theme, dict) or any(k not in ("accent", "ink", "muted", "font") for k in theme) or any(
        k != "font" and not (isinstance(x, str) and re.fullmatch(r"[0-9A-Fa-f]{6}", x)) for k, x in theme.items()
    ) or ("font" in theme and not (isinstance(theme["font"], str) and re.fullmatch(r"[A-Za-z0-9 \-]{1,40}", theme["font"]))):
        _err(v, "bad_spec", "theme", "theme may set accent, ink, muted as six-digit hex colours and font as a font name")
        return False
    if not isinstance(spec.get("facts"), dict):
        _err(v, "bad_spec", "facts", "facts must be an object")
        return False
    if len(spec["facts"]) > MAX_FACTS:
        _err(v, "too_large", "facts", f"at most {MAX_FACTS} facts")
        return False
    total = 0
    if kind == "xlsx":
        sheets = spec.get("sheets")
        if not isinstance(sheets, list) or not 1 <= len(sheets) <= 20:
            _err(v, "bad_spec", "sheets", "sheets must be a list of 1 to 20 sheets")
            return False
        names = set()
        for si, sh in enumerate(sheets):
            at = f"sheets[{si}]"
            name = sh.get("name") if isinstance(sh, dict) else None
            if not (isinstance(name, str) and 1 <= len(name) <= 31 and not re.search(r"[\[\]:*?/\\]", name)) or name.lower() in names:
                _err(v, "bad_spec", at, "each sheet needs a distinct name of at most 31 characters without [ ] : * ? / \\")
                continue
            names.add(name.lower())
            rows = sh.get("rows")
            if not isinstance(rows, list) or len(rows) > 500 or any(not isinstance(r, list) or len(r) > 50 for r in rows):
                _err(v, "bad_spec", at, "rows must be a list of at most 500 rows of at most 50 cells")
                continue
            for ri, row in enumerate(rows):
                for ci, c in enumerate(row):
                    cat = f"{at}.rows[{ri}][{ci}]"
                    if isinstance(c, bool) or c is None:
                        _err(v, "bad_spec", cat, "a cell is text, a number, {fact, format} or {formula}")
                    elif isinstance(c, str):
                        if SLOT.search(c):
                            _err(v, "bad_spec", cat, "put a figure in its own cell as {fact, format}, not inside text")
                        elif len(c) > 2000:
                            _err(v, "too_large", cat, "text longer than 2000 characters")
                    elif isinstance(c, (int, float)):
                        pass
                    elif isinstance(c, dict) and set(c) <= {"fact", "format"} and isinstance(c.get("fact"), str) and isinstance(c.get("format"), str):
                        pass
                    elif isinstance(c, dict) and set(c) == {"formula"} and isinstance(c["formula"], str) and c["formula"].startswith("=") and len(c["formula"]) <= 500:
                        pass
                    else:
                        _err(v, "bad_spec", cat, "a cell is text, a number, {fact, format} or {formula: '=B2*2'}")
        return not v.errors
    if kind == "scene":
        from ..scene.model import validate_scene

        for issue in validate_scene(spec.get("scene")):
            _err(v, issue.code, issue.where, issue.message)
        return not v.errors
    if kind == "pptx":
        slides = spec.get("slides")
        if not isinstance(slides, list):
            _err(v, "bad_spec", "slides", "slides must be a list")
            return False
        if len(slides) > MAX_SLIDES:
            _err(v, "too_large", "slides", f"at most {MAX_SLIDES} slides")
            return False
        for si, s in enumerate(slides):
            if not isinstance(s, dict):
                _err(v, "bad_spec", f"slides[{si}]", "a slide is an object")
                return False
            total += _blocks_ok(v, s.get("blocks", []), kind, f"slides[{si}]")
    else:
        total += _blocks_ok(v, spec.get("blocks"), kind, "")
    if total > MAX_BLOCKS:
        _err(v, "too_large", "", f"at most {MAX_BLOCKS} blocks")
    return not v.errors


def _fact_receipts(v: Validated, spec: dict[str, Any], cells: list[SourceCell]) -> dict[str, tuple[SourceCell, dict[str, Any]]]:
    index = {f"{c.file}!{c.sheet}!{c.ref}": c for c in cells}
    out: dict[str, tuple[SourceCell, dict[str, Any]]] = {}
    for fid, f in spec["facts"].items():
        at = f"facts.{fid}"
        if not isinstance(f, dict) or not isinstance(f.get("ref"), str):
            _err(v, "bad_spec", at, "a fact needs a ref such as results.xlsx!Results!C2")
            continue
        if f.get("unit") not in UNITS:
            _err(v, "bad_spec", at, f"a fact must say its unit: one of {', '.join(UNITS)}")
            continue
        cell = index.get(f["ref"])
        if cell is None:
            _err(v, "source_missing", at, f"{f['ref']} is not a numeric cell in the project's sources")
            continue
        concept = f.get("concept")
        labels = " ".join(cell.row_labels + cell.col_labels)
        evidence = sorted(set(tokens(concept or "")) & set(tokens(labels)))
        if concept is not None and not evidence:
            _err(v, "label_evidence", at, f"'{concept}' does not appear in the labels of {f['ref']} ({labels or 'no labels'})")
            continue
        cell_periods = periods(labels)
        declared = periods(str(f["period"])) if f.get("period") else frozenset()
        if declared and cell_periods and not (declared & cell_periods):
            _err(v, "period_mismatch", at, f"the fact says {f['period']} but {f['ref']} is labelled {labels}")
            continue
        out[fid] = (cell, {
            "source_ref": f["ref"], "concept": concept or "", "unit": f["unit"],
            "period": f.get("period") or " ".join(sorted(cell_periods)),
            "label_evidence": evidence, "selected_by": "model" if concept is not None else "cell", "value": cell.value,
            "cell_labels": labels,
        })
    return out


_PERIOD_WORD = re.compile(
    r"(?<![A-Za-z0-9])(?:Q[1-4]|H[12]|FY\s?\d{2,4}|(?:19|20)\d\d|(?-i:(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)))(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _nearest_period(text: str, at: int, end: int, cell_periods: frozenset[str] = frozenset()) -> tuple[frozenset[str], str] | None:
    """The period phrase (such as 'Q3 2026') closest to position ``at`` in a template whose slots are masked out."""
    masked = SLOT.sub(lambda m: " " * len(m.group(0)), text)
    words = [(m.start(), m.end()) for m in _PERIOD_WORD.finditer(masked)]
    if not words:
        return None
    phrases: list[list[tuple[int, int]]] = []
    for w in words:
        if phrases and w[0] - phrases[-1][-1][1] <= 2:
            phrases[-1].append(w)
        else:
            phrases.append([w])

    def gap(ph: list[tuple[int, int]]) -> int:
        lo, hi = ph[0][0], ph[-1][1]
        if hi <= at:
            return at - hi
        if lo >= end:
            return lo - end
        return 0

    cell_has_year = any(re.fullmatch(r"(19|20)\d\d", t) for t in cell_periods)
    if not cell_has_year:  # a bare year in the sentence says nothing against a quarter or month label
        phrases = [ph for ph in phrases if not all(re.fullmatch(r"(19|20)\d\d", masked[a:b].strip()) for a, b in ph)] or []
        if not phrases:
            return None
    best = min(phrases, key=gap)
    label = masked[best[0][0] : best[-1][1]]
    return periods(label), label


def _check_slot(v: Validated, where: str, fid: str, fmt: str, text: str, fact: tuple[SourceCell, dict[str, Any]], at: int = 0, end: int = 0) -> Slot | None:
    cell, base = fact
    try:
        cls = format_class(fmt)
        rendered = format_value(fmt, cell.value)
    except FormatError as exc:
        _err(v, "bad_format", where, str(exc))
        return None
    unit = base["unit"]
    if (cls == "percent") != (unit == "percent") or (cls == "currency" and unit != "currency"):
        _err(v, "unit_mismatch", where, f"{fid} is a {unit} but the format {fmt} shows a {cls}")
        return None
    if unit == "percent" and abs(cell.value) > 5:
        _err(v, "unit_scale", where, f"{fid} is {cell.value}; a percent fact holds a fraction such as 0.25, not 25")
        return None
    if cell.value != 0 and float(re.sub(r"[^0-9.]", "", rendered) or 0) == 0:
        _err(v, "format_loses_value", where, f"{fmt} would show {rendered} for {cell.value}")
        return None
    cell_periods = periods(base["cell_labels"])
    near = _nearest_period(text, at, end or at, cell_periods)
    if near and cell_periods and not (near[0] & cell_periods):
        _err(v, "period_mismatch", where, f"the words next to {fid} say {near[1].strip()} but {base['source_ref']} is {base['cell_labels']}")
        return None
    return Slot(where, fid, fmt, rendered, {**base, "format": fmt, "rendered": rendered})


def _charts(spec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    if spec["kind"] in ("scene", "xlsx"):
        return
    if spec["kind"] == "pptx":
        groups = [(f"slides[{i}]", s.get("blocks", [])) for i, s in enumerate(spec["slides"])]
    else:
        groups = [("", spec["blocks"])]
    for prefix, blocks in groups:
        for bi, b in enumerate(blocks):
            if b.get("type") == "chart":
                yield (f"{prefix}." if prefix else "") + f"blocks[{bi}]", b


def _typed_figures(text: str) -> list[str]:
    """Numbers written into text outside slots. Years (1900 to 2100) are allowed; letters glued to digits (Q3, FY26) are labels, not figures."""
    from ..match.numbers import parse_numbers

    masked = SLOT.sub(" ", text)
    out = []
    for nm in parse_numbers(masked):
        is_year = nm.unit == "plain" and nm.decimals == 0 and "," not in nm.raw and len(nm.raw.strip()) == 4 and 1900 <= nm.value <= 2100
        if not is_year:
            out.append(nm.raw.strip())
    return out


def validate_spec(spec: Any, cells: list[SourceCell]) -> Validated:
    v = Validated()
    if not _structure(v, spec):
        return v
    v.spec = spec
    facts = _fact_receipts(v, spec, cells)
    for where, text in iter_texts(spec):
        if len(text) > MAX_TEXT:
            _err(v, "too_large", where, f"text longer than {MAX_TEXT} characters")
            continue
        if spec["kind"] != "scene":
            leftover = _typed_figures(text)
            if leftover:
                _err(v, "untied_figure", where, f"the text contains {leftover[0]} typed by hand; every figure must be a {{fact:format}} slot tied to a source cell, or be removed")
                continue
        for m in SLOT.finditer(text):
            fid, fmt = m.group(1), m.group(2)
            if fid not in spec["facts"]:
                _err(v, "unknown_fact", where, f"{{{fid}}} is not defined under facts")
            elif fid in facts:
                slot = _check_slot(v, where, fid, fmt, text, facts[fid], m.start(), m.end())
                if slot:
                    v.slots.append(slot)
    if spec["kind"] == "xlsx":
        from .formats import FormatError, excel_format

        for si, sh in enumerate(spec["sheets"]):
            for ri, row in enumerate(sh["rows"]):
                for ci, c in enumerate(row):
                    if not (isinstance(c, dict) and "fact" in c):
                        continue
                    where = f"sheets[{si}].rows[{ri}][{ci}]"
                    if c["fact"] not in spec["facts"]:
                        _err(v, "unknown_fact", where, f"{{{c['fact']}}} is not defined under facts")
                        continue
                    if c["fact"] not in facts:
                        continue
                    try:
                        excel_format(c["format"])
                    except FormatError as exc:
                        _err(v, "bad_format", where, str(exc))
                        continue
                    slot = _check_slot(v, where, c["fact"], c["format"], "", facts[c["fact"]])
                    if slot:
                        v.cell_facts.append({"where": where, "sheet": si, "row": ri + 1, "col": ci + 1, "fact": c["fact"], "format": c["format"], "receipt": slot.receipt})
    for where, block in _charts(spec):
        for si, series in enumerate(block.get("series", [])):
            for pi, fid in enumerate(series.get("facts", [])):
                if fid not in spec["facts"]:
                    _err(v, "unknown_fact", where, f"chart series use {fid}, which is not defined under facts")
                elif fid in facts:
                    v.chart_points.append({"where": f"{where}.series[{si}].points[{pi}]", "chart": where, "series": si, "point": pi,
                                           "category": block["categories"][pi], "fact": fid, "receipt": dict(facts[fid][1])})
    return v


def resolve(spec: dict[str, Any], values: dict[str, float]) -> tuple[dict[str, Any], list[tuple[str, str, str, str]]]:
    """The spec with every slot replaced by its rendered text, and the slots in document order as (path, fact, rendered, text).

    The builder never sees fact ids or formats: it lays out plain text. Ties are found afterwards by reading the finished file."""
    import copy

    out = copy.deepcopy(spec)
    occurrences: list[tuple[str, str, str, str]] = []

    def sub(path: str, text: str) -> str:
        def one(m: re.Match) -> str:
            rendered = format_value(m.group(2), values[m.group(1)])
            occurrences.append((path, m.group(1), rendered, ""))
            return rendered

        return SLOT.sub(one, text)

    def setpath(root: Any, path: str, text: str) -> None:
        parts = re.findall(r"[A-Za-z_]+|\[\d+\]", path)
        node = root
        for p in parts[:-1]:
            node = node[int(p[1:-1])] if p.startswith("[") else node[p]
        last = parts[-1]
        if last.startswith("["):
            node[int(last[1:-1])] = text
        else:
            node[last] = text

    for path, text in iter_texts(spec):
        new = sub(path, text)
        if new != text:
            setpath(out, path, new)
    if out["kind"] == "xlsx":
        from .formats import excel_format

        used = set()
        for sh in out["sheets"]:
            for row in sh["rows"]:
                for ci, c in enumerate(row):
                    if isinstance(c, dict) and "fact" in c:
                        used.add(c["fact"])
                        row[ci] = {"value": values[c["fact"]], "number_format": excel_format(c["format"])}
        groups = []
    elif out["kind"] == "scene":
        groups = []
        used = {f for _, f, _, _ in occurrences}
        out["scene"]["facts"] = {f: d for f, d in out["facts"].items() if f in used}
        out["scene"]["cache"] = {f: values[f] for f in used}
        for ni, node in enumerate(spec["scene"]["nodes"]):
            if node.get("type") == "text" and SLOT.search(node.get("text", "")):
                out["scene"]["nodes"][ni]["template"] = node["text"]
    else:
        groups = [b for s_ in out["slides"] for b in s_.get("blocks", [])] if out["kind"] == "pptx" else out["blocks"]
    for b in groups:
        if b.get("type") == "chart":
            for series in b["series"]:
                series["values"] = [values[f] for f in series.get("facts", [])]
    final = {p: t for p, t in iter_texts(out)}
    occurrences = [(p, f, r, final[p]) for p, f, r, _ in occurrences]
    return out, occurrences
