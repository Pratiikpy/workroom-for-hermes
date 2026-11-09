"""Run-level text replacement for DrawingML (a:) and WordprocessingML (w:) paragraphs.

A replacement never touches text outside the matched span, keeps the first matched run's properties, and
refuses to match across fields, line breaks, tabs or deleted text. Ambiguity (several occurrences) is
reported, never resolved silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator

from lxml import etree

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
OWN_AUTHOR = "Workroom"


class EditError(ValueError):
    """An edit could not be applied exactly as requested."""


@dataclass(frozen=True)
class Flavor:
    ns: str
    para: str
    run: str
    text: str
    run_props: str
    # tags that may sit between two text runs without splitting a match
    transparent: frozenset[str]
    # tags of elements whose text must never be matched or changed
    opaque_containers: frozenset[str]

    @classmethod
    def drawing(cls) -> Flavor:
        q = lambda t: "{%s}%s" % (A_NS, t)
        return cls(A_NS, q("p"), q("r"), q("t"), q("rPr"), frozenset(), frozenset())

    @classmethod
    def word(cls) -> Flavor:
        q = lambda t: "{%s}%s" % (W_NS, t)
        return cls(
            W_NS, q("p"), q("r"), q("t"), q("rPr"),
            frozenset({q("bookmarkStart"), q("bookmarkEnd"), q("proofErr"), q("permStart"), q("permEnd")}),
            frozenset({q("del"), q("moveFrom")}),
        )


DRAWING = Flavor.drawing()
WORD = Flavor.word()


@dataclass(frozen=True)
class Replacement:
    count: int
    formats_merged: bool


def _text_runs(p: etree._Element, fl: Flavor) -> list[list[etree._Element]]:
    """Group a paragraph's text runs into segments that a match may span."""
    segments: list[list[etree._Element]] = [[]]
    in_field = 0  # Word: runs between a field's begin and end are its instruction and its result, which Word regenerates (page numbers, tables of contents)
    fld = "{%s}fldChar" % W_NS
    kind = "{%s}fldCharType" % W_NS
    for child in p:
        if child.tag == fl.run:
            marks = [c.get(kind) for c in child.iter(fld)] if fl is WORD else []
            if in_field and not marks:
                segments.append([])
                continue
            for m in marks:
                in_field = in_field + 1 if m == "begin" else max(0, in_field - 1) if m == "end" else in_field
            ts = [c for c in child if c.tag == fl.text]
            other = [c for c in child if c.tag not in (fl.text, fl.run_props)]
            if len(ts) == 1 and not other:
                segments[-1].append(child)
                continue
            if ts and not other:  # several w:t in one run: treat as a break to stay safe
                segments.append([])
                continue
            segments.append([])  # run holds a break, tab, field char or drawing
        elif child.tag in fl.transparent:
            continue
        elif child.tag in fl.opaque_containers:
            segments.append([])
        elif fl is WORD and child.tag == "{%s}ins" % W_NS and child.get("{%s}author" % W_NS) == OWN_AUTHOR:
            # Workroom's own tracked insertion stays addressable so a later release can update it in place
            inner = [r for r in child if r.tag == fl.run]
            ok = len(inner) == 1 and len(child) == 1 and len([c for c in inner[0] if c.tag == fl.text]) == 1                 and not [c for c in inner[0] if c.tag not in (fl.text, fl.run_props)]
            segments.append([])
            if ok:
                segments.append([inner[0]])
            segments.append([])
        else:
            segments.append([])
    return [s for s in segments if s]


def _text_of(run: etree._Element, fl: Flavor) -> str:
    return run.find(fl.text).text or ""


def _set_text(run: etree._Element, fl: Flavor, value: str) -> None:
    t = run.find(fl.text)
    t.text = value
    if fl is WORD and (value[:1].isspace() or value[-1:].isspace()):
        t.set(XML_SPACE, "preserve")


def _props_key(run: etree._Element, fl: Flavor) -> bytes:
    rp = run.find(fl.run_props)
    return etree.tostring(rp, method="c14n") if rp is not None else b""


def find_all(p: etree._Element, old: str, fl: Flavor) -> list[tuple[int, int]]:
    """Return (segment index, offset) for each occurrence of ``old`` that lies within one segment."""
    hits: list[tuple[int, int]] = []
    for si, seg in enumerate(_text_runs(p, fl)):
        joined = "".join(_text_of(r, fl) for r in seg)
        start = 0
        while old:
            i = joined.find(old, start)
            if i < 0:
                break
            hits.append((si, i))
            start = i + len(old)
    return hits


def _locate(p: etree._Element, old: str, fl: Flavor, hit: tuple[int, int]):
    si, offset = hit
    seg = _text_runs(p, fl)[si]
    texts = [_text_of(r, fl) for r in seg]
    end = offset + len(old)
    pos = 0
    first = last = None
    for i, t in enumerate(texts):
        s, e = pos, pos + len(t)
        if first is None and s <= offset < e:
            first = (i, offset - s)
        if s < end <= e:
            last = (i, end - s)
            break
        pos = e
    if first is None or last is None:
        raise EditError("match boundaries could not be located")
    return seg, texts, first[0], first[1], last[0], last[1]


def _run_with_text(run: etree._Element, fl: Flavor, value: str, deleted: bool = False) -> etree._Element:
    from copy import deepcopy

    r = deepcopy(run)
    t = r.find(fl.text)
    if deleted:
        t.tag = "{%s}delText" % W_NS
    t.text = value
    if value[:1].isspace() or value[-1:].isspace():
        t.set(XML_SPACE, "preserve")
    return r


def replace_tracked(p: etree._Element, old: str, new: str, fl: Flavor, occurrence: int | None, *, author: str, date: str, next_id) -> Replacement:
    """Word only: replace as a tracked change (the old digits struck through, the new ones inserted), never touching other text.
    When the match already sits in Workroom's own insertion, the proposal is simply updated in place."""
    if fl is not WORD:
        raise EditError("tracked changes exist only in Word documents")
    hits = find_all(p, old, fl)
    if not hits:
        raise EditError(f"text {old!r} not found in this paragraph")
    if len(hits) > 1 and occurrence is None:
        raise EditError(f"text {old!r} occurs {len(hits)} times in this paragraph; choose one")
    seg, texts, fi, fo, li, lo = _locate(p, old, fl, hits[occurrence or 0])
    if fi == li and seg[fi].getparent() is not p:
        _set_text(seg[fi], fl, texts[fi][:fo] + new + texts[fi][lo:])
        return Replacement(1, False)
    if any(r.getparent() is not p for r in seg[fi : li + 1]):
        raise EditError("this number sits in text another reviewer inserted; not changed")
    q = lambda t: "{%s}%s" % (W_NS, t)

    def wrap(tag: str, child: etree._Element) -> etree._Element:
        el = etree.Element(q(tag))
        el.set(q("id"), str(next_id()))
        el.set(q("author"), author)
        el.set(q("date"), date)
        el.append(child)
        return el

    first_run = seg[fi]
    for k in range(fi, li + 1):
        run = seg[k]
        t = texts[k]
        s = fo if k == fi else 0
        e = lo if k == li else len(t)
        pieces: list[etree._Element] = []
        if t[:s]:
            pieces.append(_run_with_text(run, fl, t[:s]))
        pieces.append(wrap("del", _run_with_text(run, fl, t[s:e], deleted=True)))
        if k == li:
            pieces.append(wrap("ins", _run_with_text(first_run, fl, new)))
            if t[e:]:
                pieces.append(_run_with_text(run, fl, t[e:]))
        idx = p.index(run)
        p.remove(run)
        for off, el in enumerate(pieces):
            p.insert(idx + off, el)
    return Replacement(1, len({_props_key(seg[k], fl) for k in range(fi, li + 1)}) > 1)


def replace_once(p: etree._Element, old: str, new: str, fl: Flavor, occurrence: int | None = None) -> Replacement:
    """Replace exactly one occurrence in paragraph ``p``. With several occurrences, ``occurrence`` must choose."""
    if not old:
        raise EditError("empty search text")
    hits = find_all(p, old, fl)
    if not hits:
        raise EditError(f"text {old!r} not found in this paragraph")
    if len(hits) > 1 and occurrence is None:
        raise EditError(f"text {old!r} occurs {len(hits)} times in this paragraph; choose one")
    seg, texts, fi, fo, li, lo = _locate(p, old, fl, hits[occurrence or 0])
    merged = len({_props_key(seg[k], fl) for k in range(fi, li + 1)}) > 1
    if fi == li:
        _set_text(seg[fi], fl, texts[fi][:fo] + new + texts[fi][lo:])
    else:
        _set_text(seg[fi], fl, texts[fi][:fo] + new)
        for k in range(fi + 1, li):
            p.remove(seg[k])
        tail = texts[li][lo:]
        if tail:
            _set_text(seg[li], fl, tail)
        else:
            p.remove(seg[li])
    return Replacement(1, merged)


def paragraphs(root: etree._Element, fl: Flavor) -> Iterator[etree._Element]:
    return root.iter(fl.para)


def paragraph_text(p: etree._Element, fl: Flavor) -> str:
    """Visible text of a paragraph: text runs joined, with deleted text excluded."""
    parts = []
    for r in p.iter(fl.run):
        if any(a.tag in fl.opaque_containers for a in r.iterancestors()):
            continue
        for t in r.findall(fl.text):
            parts.append(t.text or "")
    return "".join(parts)
