"""Proof of figures: what the agent read in a session (evidence) and, for each figure in a text it wrote, where that figure came from.

Evidence is captured by hooks from tool results, so it records what the tools returned, not what the model says it read. A figure is **sourced** when the same
value (allowing the writer's rounding, scale words and percent or fraction) appears in one evidence item on a line that shares a meaningful word with the
figure's own sentence, as judged by the same matcher that links report figures to workbook cells (word weights, row headings, periods, the chance rule);
**candidate** when a source fits but the words do not single it out; **calculated** when it equals a difference, sum, ratio or percent change of two figures
from one evidence item whose lines share at least two telling words with the sentence; **stated** when it appears in a message from the owner; **value
only** when the number appears in what was read but nothing near it names the figure (in a large source almost any number appears somewhere, so this is
not proof); and **unsourced** otherwise. A match proves the figure appears in
what was read, not that the sentence around it is right.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .match.engine import tokens
from .match.numbers import consistent_with_source, parse_numbers

MAX_ITEM = 300_000
MAX_SESSION = 20_000_000
CALC_MAX_NUMBERS = 400
MAX_INDEX_NUMBERS = 8_000  # evidence figures read for one check, newest evidence first; older evidence beyond this is not used for that check
MAX_FIGURES = 4_000  # figures of one text that are matched; the rest are reported as not checked
MAX_LINE = 20_000  # a longer line is read in windows of this size
MAX_LISTED = 10_000  # figures of one text that are listed at all
CHECK_PART = 500  # a text with more figures than this is matched in parts, so the time limit can stop between parts
CHECK_SECONDS = 1.0  # once a large text has used this long, its remaining figures are reported as not checked
WEAK_MAX = 10
COMMON_SHARE = 0.05  # a word on more than this share of evidence lines (sheet names, units, "total") says nothing about which figure is meant  # 0..10 and round tens match by chance far too easily to count as strong proof on their own
TEXT_DELIVERABLES = {".md", ".markdown", ".html", ".htm", ".csv", ".tsv", ".txt"}
READING_TOOLS_PREFIX = ("read_file", "search_files", "web_", "browser_", "terminal", "process", "execute_code", "vision", "video_analyze", "mcp_", "delegate", "session_search", "skill_view")
_TAGS = re.compile(r"<script\b.*?(?:</script\s*>|\Z)|<style\b.*?(?:</style\s*>|\Z)|<[^<>]*(?:>|\Z)", re.S | re.I)
_DIGIT = re.compile(r"[0-9]")
_LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|#{1,6}\s*\d+(?:\.\d+)*[.)]?)\s")


@dataclass
class Evidence:
    id: int
    tool: str
    ref: str
    at: float
    text: str
    kind: str = "tool"  # tool | owner
    values: list[float] = field(default_factory=list)


@dataclass
class FigureProof:
    raw: str
    value: float
    start: int
    end: int
    state: str  # sourced | calculated | stated | unsourced
    weak: bool = False
    evidence: int | None = None
    ref: str = ""
    tool: str = ""
    how: str = ""
    excerpt: str = ""


class EvidenceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT, at REAL, tool TEXT, kind TEXT, ref TEXT, sha TEXT, text TEXT)")
            self.db.execute("CREATE INDEX IF NOT EXISTS ev_session ON evidence(session)")
            self.db.execute("CREATE TABLE IF NOT EXISTS proofs (path TEXT PRIMARY KEY, session TEXT, sha TEXT, at REAL, summary TEXT, figures TEXT)")

    def close(self) -> None:
        self.db.close()

    def add(self, session: str, tool: str, ref: str, text: str, kind: str = "tool") -> int | None:
        text = (text or "")[:MAX_ITEM]
        if not session or not text.strip() or not _DIGIT.search(text):
            return None  # nothing with a figure in it can prove a figure
        sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        with self.db:
            if self.db.execute("SELECT 1 FROM evidence WHERE session=? AND sha=? AND ref=?", (session, sha, ref)).fetchone():
                return None
            cur = self.db.execute("INSERT INTO evidence (session, at, tool, kind, ref, sha, text) VALUES (?,?,?,?,?,?,?)", (session, time.time(), tool, kind, ref[:500], sha, text))
            total = self.db.execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM evidence WHERE session=?", (session,)).fetchone()[0]
            while total > MAX_SESSION:
                oldest = self.db.execute("SELECT id, LENGTH(text) FROM evidence WHERE session=? ORDER BY id LIMIT 1", (session,)).fetchone()
                self.db.execute("DELETE FROM evidence WHERE id=?", (oldest[0],))
                total -= oldest[1]
        return int(cur.lastrowid)

    def items(self, session: str) -> list[Evidence]:
        return [Evidence(r["id"], r["tool"], r["ref"], r["at"], r["text"], r["kind"]) for r in self.db.execute("SELECT * FROM evidence WHERE session=? ORDER BY id", (session,))]

    def save_proof(self, path: str, session: str, sha: str, proofs: list[FigureProof]) -> dict[str, Any]:
        summ = summary(proofs)
        figs = [{"raw": f.raw, "start": f.start, "end": f.end, "state": f.state, "weak": f.weak, "ref": f.ref, "tool": f.tool, "how": f.how, "excerpt": f.excerpt} for f in proofs]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO proofs (path, session, sha, at, summary, figures) VALUES (?,?,?,?,?,?)",
                            (path, session, sha, time.time(), json.dumps(summ), json.dumps(figs, ensure_ascii=False)))
        return summ

    def proof(self, path: str) -> dict[str, Any] | None:
        r = self.db.execute("SELECT * FROM proofs WHERE path=?", (path,)).fetchone()
        if r is None:
            return None
        return {"session": r["session"], "sha": r["sha"], "at": r["at"], "summary": json.loads(r["summary"]), "figures": json.loads(r["figures"])}

    def forget(self, session: str) -> int:
        with self.db:
            return self.db.execute("DELETE FROM evidence WHERE session=?", (session,)).rowcount


def plain_text(data: str, suffix: str) -> str:
    """The visible text of a deliverable: tags removed from HTML (offsets are then those of this text)."""
    if suffix in (".html", ".htm"):
        return re.sub(r"[ \t]+", " ", _TAGS.sub(" ", data))
    return data


def _numbers_of_line(line: str) -> list:
    """The numbers of one line; a very long line is read window by window, cut at a space, with positions kept relative to the whole line."""
    if len(line) <= MAX_LINE:
        return parse_numbers(line)
    out = []
    start = 0
    while start < len(line) and len(out) < MAX_LISTED:
        end = min(len(line), start + MAX_LINE)
        if end < len(line):
            cut = line.rfind(" ", start + MAX_LINE // 2, end)
            end = cut + 1 if cut > 0 else end
        out += [replace(n, start=n.start + start, end=n.end + start) for n in parse_numbers(line[start:end])]
        start = end
    return out


def _figures(text: str) -> list:
    out = []
    lines = text.split("\n")
    pos = 0
    for line in lines:
        if len(out) >= MAX_LISTED:
            break
        mark = _LIST_MARK.match(line[:200])
        for m in _numbers_of_line(line):
            if mark and m.start < mark.end():
                continue  # a list marker or a numbered heading, not a figure
            if m.unit == "plain" and m.decimals == 0 and "," not in m.raw and len(m.raw.strip("()-+")) == 4 and 1900 <= abs(m.value) <= 2100:
                continue  # a year
            out.append((m, pos + m.start, pos + m.end))
        pos += len(line) + 1
    return out


def _words(text: str) -> set[str]:
    return {w for w in tokens(text) if not w[0].isdigit() and len(w) > 2}


SHEET_MARK = " » "  # "Sheet » headings: value", how a workbook read by the agent is kept as evidence (a markdown table uses "|" itself)
_CELL_SPLIT = re.compile(r"	|,(?=\S)|\s\|\s|\|")
CONTEXT_WORDS_BEFORE = 8
CONTEXT_WORDS_AFTER = 3


def _table_header(text: str) -> list[str] | None:
    """The column names of a CSV, TSV or pipe table: its first line, when that line has no figures and splits into as many fields as the next."""
    lines = [x for x in text.split("\n")[:3] if x.strip()]
    if len(lines) < 2 or parse_numbers(lines[0]):
        return None
    head, nxt = _CELL_SPLIT.split(lines[0].strip().strip("|")), _CELL_SPLIT.split(lines[1].strip().strip("|"))
    return [h.strip() for h in head] if len(head) >= 2 and len(head) == len(nxt) else None


def _labels_in_line(line: str, n, header: list[str] | None) -> tuple[str, ...]:
    """The words that name one figure on a line: in a table row, its row's first field and its column's name; in prose, the few words around it."""
    fields = _CELL_SPLIT.split(line.strip().strip("|"))
    if header and len(fields) == len(header):
        pos = 0
        for k, f in enumerate(fields):
            start = line.find(f, pos)
            if start <= n.start < start + len(f) + 1:
                labels = tuple(x for x in (fields[0].strip(), header[k]) if x and not parse_numbers(x))
                return labels or (line,)
            pos = start + len(f)
    before = line[: n.start].split()[-CONTEXT_WORDS_BEFORE:]
    after = line[n.end:].split()[:CONTEXT_WORDS_AFTER]
    return (" ".join(before + after),)


class _Index:
    """Every evidence value with the item and the words of the line it sits on, sorted by value; how common each word is across the evidence; and the
    same evidence as source cells for the matcher (one cell per figure, its line's words as the headings)."""

    def __init__(self, items: list[Evidence], budget: int | None = None) -> None:
        from .ooxml.xlsx import SourceCell
        from .match.engine import SourceIndex

        cells = []
        self.cell_item: dict[tuple[str, str], int] = {}
        pairs = []
        self.line_words: list[set[str]] = []
        self.by_id = {ev.id: ev for ev in items}
        df: dict[str, int] = {}
        budget = budget if budget is not None else 10 ** 12  # no limit when the caller builds the index itself (the benchmarks); the hooks pass MAX_INDEX_NUMBERS
        self.truncated = False
        parsed: dict[int, list] = {}
        for ev in reversed(items):
            rows = parsed.setdefault(ev.id, [])
            for line in ev.text.split("\n"):
                if budget <= 0:
                    self.truncated = True
                    break
                nums = parse_numbers(line[:MAX_LINE])
                if nums:
                    rows.append((line[:MAX_LINE], nums))
                    budget -= len(nums)
        owner_numbers = []
        for ev in items:
            ev.values = []
            header = _table_header(ev.text)
            for line, nums in parsed.get(ev.id, []):
                if ev.kind == "owner":
                    owner_numbers += [(n.scaled, len(owner_numbers) + i, ev) for i, n in enumerate(nums)]
                words = _words(line)
                k = len(self.line_words)
                self.line_words.append(words)
                for w in words:
                    df[w] = df.get(w, 0) + 1
                for j, n in enumerate(nums):
                    ev.values.append(n.scaled)
                    pairs.append((n.scaled, ev.id, k))
                    if ev.kind != "owner":
                        sheet, _, rest = line.partition(SHEET_MARK) if SHEET_MARK in line else ("", "", line)
                        if sheet:
                            label, _, _v = rest.rpartition(":")
                            row_labels = tuple(x.strip() for x in label.split(" / ") if x.strip())
                        else:
                            row_labels = _labels_in_line(line, n, header)
                        ref = f"E{ev.id}L{k}N{j}"  # a text source has no sheet; its words are only those that name the figure
                        cells.append(SourceCell(sheet, ref, k, j, n.scaled, False, False, row_labels, (), False, ev.ref))
                        self.cell_item[(sheet, ref)] = ev.id
        owner_numbers.sort(key=lambda t: (t[0], t[1]))
        self.owner_values = [t[0] for t in owner_numbers]
        self.owner_numbers = owner_numbers
        pairs.sort()
        self.values = [p[0] for p in pairs]
        self.owner = [p[1] for p in pairs]
        self.line = [p[2] for p in pairs]
        lines = max(1, len(self.line_words))
        self.common = {w for w, n in df.items() if n / lines > COMMON_SHARE and lines >= 20}
        self.word_lines: dict[str, list[int]] = {}
        for k, words in enumerate(self.line_words):
            for w in words:
                if w not in self.common:
                    self.word_lines.setdefault(w, []).append(k)
        self.line_values: dict[int, list[tuple[int, float]]] = {}
        for val, owner_id, k in pairs:
            if val != 0:
                self.line_values.setdefault(k, []).append((owner_id, val))
        self.sources = SourceIndex(cells)

    def near(self, target: float, tol: float) -> list[tuple[float, int, int]]:
        lo = bisect.bisect_left(self.values, target - tol)
        hi = bisect.bisect_right(self.values, target + tol)
        return [(self.values[i], self.owner[i], self.line[i]) for i in range(lo, min(hi, lo + 200))]

    def shared(self, line: int, words: set[str]) -> set[str]:
        return (self.line_words[line] & words) - self.common


def _candidates(m) -> list[float]:
    """Source values that would be written as this figure: the shown value under the usual scales."""
    base = m.value * (-1 if m.negative and m.value > 0 else 1)
    out = [base, m.scaled if not m.negative else -abs(m.scaled)]
    if m.unit == "percent":
        out.append(base / 100.0)
    for f in (1e3, 1e6, 1e9):
        out.append(base * f)
    return [x for x in dict.fromkeys(out)]


def _excerpt(text: str, value_text: str) -> str:
    i = text.find(value_text)
    if i < 0:
        return ""
    return text[max(0, i - 80): i + len(value_text) + 80].replace("\n", " ")


def _is_weak(m) -> bool:
    v = abs(m.value)
    return m.decimals == 0 and (v <= WEAK_MAX or (v < 1000 and v % 10 == 0 and m.unit == "plain"))


def _said_by_owner(m, idx: _Index):
    """The first owner message that states this figure, found by value instead of by reading every message again for every figure."""
    if not idx.owner_numbers:
        return None
    tol = (0.5 * 10 ** (-m.decimals)) * 1.0001 + 1e-12
    factors = [1.0, 1e3, 1e6, 1e9]
    if m.unit in ("percent", "pp"):
        factors.append(0.01)
    if m.scale != 1.0:
        factors.append(m.scale)
    best = None
    for f in factors:
        lo, hi = sorted(((m.value - tol) * f, (m.value + tol) * f))
        pad = abs(hi) * 1e-9 + 1e-12
        for a, b in ((lo, hi), (-hi, -lo)) if m.aside else ((lo, hi),):
            i = bisect.bisect_left(idx.owner_values, a - pad)
            while i < len(idx.owner_values) and idx.owner_values[i] <= b + pad:
                value, order, ev = idx.owner_numbers[i]
                if (best is None or order < best[0]) and consistent_with_source(m, value)[0]:
                    best = (order, ev)
                i += 1
    return best[1] if best else None


def build_index(items: list[Evidence]) -> _Index:
    """Read every figure out of the evidence once; pass the result to check_text when checking many texts against the same evidence."""
    return _Index(items)


_BOUNDARY = re.compile(r"[.;!?](?=\s|$)|\n")


SENTENCE_SPAN = 600
_STOPS = ".;!?"


class _Sentences:
    """The sentence (or table line) boundaries of one text, found once, so each figure is placed by a lookup."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts: list[int] = []
        self.ends: list[int] = []
        for b in _BOUNDARY.finditer(text):
            self.starts.append(b.start())
            self.ends.append(b.end())

    def around(self, start: int, end: int) -> tuple[str, int]:
        """The sentence around the figure at ``start:end`` and where it begins; a decimal point is not a boundary. Never more than SENTENCE_SPAN characters either side."""
        i = bisect.bisect_right(self.ends, start)
        left = self.ends[i - 1] if i else 0
        if start and self.text[start - 1] in _STOPS:
            left = start
        j = bisect.bisect_left(self.starts, end)
        right = self.starts[j] if j < len(self.starts) else len(self.text)
        left, right = max(left, start - SENTENCE_SPAN), min(right, end + SENTENCE_SPAN)
        return self.text[left:right], left


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence (or table line) around one figure."""
    return _Sentences(text).around(start, end)[0]


def check_text(text: str, items: list[Evidence] | _Index, context: str = "") -> list[FigureProof]:
    """Check every figure of ``text``. ``context`` adds words that belong to every figure (for a table cell: its row and column headings)."""
    from .match.engine import Mention, is_coincidence, match_mentions

    idx = items if isinstance(items, _Index) else _Index(items, MAX_INDEX_NUMBERS)
    figures = _figures(text)
    sentences = _Sentences(text)
    mentions = []
    unchecked = figures[MAX_FIGURES:]
    figures = figures[:MAX_FIGURES]
    for i, (m, start, end) in enumerate(figures):
        sent, offset = sentences.around(start, end)
        if not sent:
            offset = -1
        span = (start - offset, end - offset) if offset >= 0 and sent[start - offset: end - offset] == m.raw else None
        mentions.append(Mention(str(i), m, tuple(x for x in (sent, context) if x), span, "", context.split("  ")[0] if context else ""))
    out: list[FigureProof] = []
    step = len(figures) if len(figures) <= CHECK_PART else CHECK_PART
    deadline = time.monotonic() + CHECK_SECONDS
    done = 0
    while done < len(figures):
        if done and time.monotonic() > deadline:
            break
        results = match_mentions(mentions[done:done + step], idx.sources)
        for (m, start, end), r in zip(figures[done:done + step], results):
            proof = FigureProof(m.raw, m.scaled, start, end, "unsourced", weak=_is_weak(m))
            said = _said_by_owner(m, idx)
            if said is not None:
                proof.state, proof.evidence, proof.ref, proof.tool = "stated", said.id, said.ref, said.tool
            elif r.best is not None:
                cell = r.best.cell
                ev = idx.by_id.get(idx.cell_item.get((cell.sheet, cell.ref), -1))
                coincidence = r.decision == "confirm" and is_coincidence(r.best.label_score, m.raw, bool(context))
                proof.state = "sourced" if r.decision == "accept" else ("value only" if coincidence else "candidate")
                if ev is not None:
                    proof.evidence, proof.ref, proof.tool = ev.id, ev.ref, ev.tool
                    body = re.search(r"\d[\d,]*(?:\.\d+)?", m.raw)
                    proof.excerpt = (_excerpt(ev.text, body.group(0)) if body else "") or " / ".join(cell.row_labels)[:200]
                proof.how = r.reason
            if proof.state in ("candidate", "value only") and not proof.weak:
                hit = _stated_in_a_sentence(m, idx, _words(sentences.around(start, end)[0] + " " + context))
                if hit is not None:
                    ev, n = hit
                    proof.state, proof.evidence, proof.ref, proof.tool = "sourced", ev.id, ev.ref, ev.tool
                    proof.how = f"the same figure stands in a sentence the agent read that shares {n} telling words with this one"
                    body = re.search(r"\d[\d,]*(?:\.\d+)?", m.raw)
                    proof.excerpt = (_excerpt(ev.text, body.group(0)) if body else "") or proof.excerpt
            if proof.state in ("unsourced", "value only"):
                calc = _calculated(m, idx, _words(sentences.around(start, end)[0] + " " + context))
                if calc:
                    ev, how = calc
                    proof.state, proof.evidence, proof.ref, proof.tool, proof.how = "calculated", ev.id, ev.ref, ev.tool, how
                    proof.weak = False
            out.append(proof)
        done += step
    for m, start, end in figures[done:]:
        out.append(FigureProof(m.raw, m.scaled, start, end, "unsourced", weak=_is_weak(m), how="not checked: this text has too many figures to check in the time allowed"))
    for m, start, end in unchecked:
        out.append(FigureProof(m.raw, m.scaled, start, end, "unsourced", weak=_is_weak(m), how=f"not checked: this text has more than {MAX_FIGURES} figures"))
    return out


def _stated_in_a_sentence(m, idx: _Index, words: set[str]):
    """A figure that several of the agent's sources print in different places is ambiguous to the cell matcher, but when one printed occurrence sits in a
    sentence that shares at least three words with the figure's own sentence, the figure was read there. Tables are not touched: their headings decide."""
    tol = 0.5 * 10 ** (-m.decimals) + 1e-12
    best = None
    for target in _candidates(m):
        for _val, oid, line in idx.near(target, tol):
            ev = idx.by_id.get(oid)
            if ev is None or ev.kind == "owner" or SHEET_MARK in ev.text[:4000]:
                continue
            n = len(idx.line_words[line] & words)  # topic words count here: on one subject nearly every line says "sales" and "electric", and the figure must still stand in a line of its own kind
            if n >= 3 and (best is None or n > best[1]):
                best = (ev, n)
    return best


CALC_NEAR_LINES = 3
CALC_CUES = {w for t in ("increase increased decrease decreased grew growth rose fell drop dropped change changed difference total share compared higher lower up down",) for w in tokens(t)}


def _calculated(m, idx: _Index, words: set[str]):
    """A figure that is a difference, sum, ratio or percent change of two figures read close together (same evidence item, at most three lines apart), each
    on a line that shares a telling word with the figure's sentence. Without nearness and words, two numbers somewhere in a large source combine into almost
    anything (measured on a real annual report: 63 of 165 figures without a source came out "calculated" before this rule)."""
    shown = m.value * (-1 if m.negative and m.value > 0 else 1)
    tol = 0.5 * 10 ** (-m.decimals) + 1e-12
    if not (abs(shown) > WEAK_MAX or m.decimals > 0):
        return None
    digits = len(re.sub(r"\D", "", m.raw).lstrip("0"))
    if digits < (2 if words & CALC_CUES else 3):
        return None  # short figures equal some sum or ratio of nearby numbers by chance (17 of 165 sourceless figures on a real report)
    pool: list[tuple[int, int, float]] = []
    for line in sorted({k for w in words if w in idx.word_lines for k in idx.word_lines[w]}):
        pool += [(owner_id, line, val) for owner_id, val in idx.line_values.get(line, ())]
        if len(pool) > CALC_MAX_NUMBERS * 4:
            return None
    pool.sort()
    keys = [(o, k) for o, k, _ in pool]
    for oa, la, a in pool:
        for _, lb, b in pool[bisect.bisect_left(keys, (oa, la - CALC_NEAR_LINES)):bisect.bisect_right(keys, (oa, la + CALC_NEAR_LINES))]:
            if a == b:
                continue
            if not (words & CALC_CUES) and len(idx.shared(la, words) | idx.shared(lb, words)) < 2:
                continue  # without a word that says "change" or "total", one shared word is a coincidence waiting to happen
            tries = []
            if m.unit == "percent":
                tries += [((a - b) / b * 100.0, f"change from {b:g} to {a:g}"), (a / b * 100.0, f"{a:g} as a share of {b:g}")]
            else:
                for scale in (1.0, 1e3, 1e6, 1e9):
                    tries += [((a - b) / scale, f"{a:g} minus {b:g}"), ((a + b) / scale, f"{a:g} plus {b:g}")]
                tries.append((a / b, f"{a:g} divided by {b:g}"))
            for value, how in tries:
                if abs(value - shown) <= tol:
                    return idx.by_id[oa], how
    return None


def summary(proofs: list[FigureProof]) -> dict[str, Any]:
    counts = {s.replace(" ", "_"): sum(1 for p in proofs if p.state == s) for s in ("sourced", "candidate", "calculated", "stated", "value only", "unsourced")}
    return {"figures": len(proofs), **counts, "unsourced_figures": [p.raw for p in proofs if p.state == "unsourced"][:12]}


def _plain_number(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def evidence_text_of_file(path: Path) -> str:
    """Text and numbers of a file the agent read, including Office files that read_file returns as binary."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".xlsx":
            from .ooxml.package import open_package
            from .ooxml.xlsx import index_workbook

            cells = index_workbook(open_package(path.read_bytes()), file=path.name)
            return "\n".join(f"{c.sheet}{SHEET_MARK}{' / '.join(c.row_labels + c.col_labels)}: {_plain_number(c.value)}" for c in cells[:20000])
        if suffix in (".docx", ".pptx", ".pdf"):
            from .deliverables import kind_of, text_of

            return text_of(path.read_bytes(), kind_of(path.name)) or ""
        if path.stat().st_size <= MAX_ITEM:
            return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  unreadable evidence is simply not evidence
        return ""
    return ""


def _flatten(value: Any, out: list[str], key: str = "", depth: int = 0) -> None:
    """One line per string or number of a structured tool result, with its key in front, so a search result's snippets are read as lines of text the way they would be on a page."""
    if depth > 8 or len(out) > 20000:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("success", "status", "ok") and depth == 0:
                continue
            _flatten(v, out, str(k), depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _flatten(v, out, key, depth + 1)
    elif value is not None:
        text = str(value)
        for line in text.splitlines() or [""]:
            if line.strip():
                out.append(f"{key}: {line}" if key and not line.startswith(key) else line)


def _split_long(text: str, limit: int = 600) -> str:
    """Break very long lines at sentence ends so each figure keeps its own neighbourhood, and the line-by-line reader never meets a page-sized line."""
    out = []
    for line in text.split(chr(10)):
        while len(line) > limit:
            cut = max(line.rfind(". ", 0, limit), line.rfind("; ", 0, limit), line.rfind(", ", 0, limit))
            cut = cut + 1 if cut > limit // 3 else limit
            out.append(line[:cut])
            line = line[cut:].lstrip()
        out.append(line)
    return chr(10).join(out)


def result_text(result: Any) -> str:
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return _split_long(result)
        result = parsed
    if isinstance(result, (dict, list)):
        lines: list[str] = []
        _flatten(result, lines)
        return _split_long(chr(10).join(lines))
    return _split_long(json.dumps(result, ensure_ascii=False, default=str)) if result is not None else ""


_INDEXES: dict[tuple, _Index] = {}


def session_index(store: EvidenceStore, session: str) -> _Index:
    """The evidence of a session, read once and kept until the session's evidence changes, so several checks in a row do not each read it again."""
    newest, count = store.db.execute("SELECT COALESCE(MAX(id), 0), COUNT(*) FROM evidence WHERE session=?", (session,)).fetchone()
    key = (store.path, session, newest, count)
    idx = _INDEXES.get(key)
    if idx is None:
        idx = _Index(store.items(session), MAX_INDEX_NUMBERS)
        while len(_INDEXES) >= 4:
            _INDEXES.pop(next(iter(_INDEXES)))
        _INDEXES[key] = idx
    return idx


def check_file(store: EvidenceStore, session: str, path: Path) -> dict[str, Any] | None:
    """Check a text deliverable against the session's evidence and remember the result for the owner's view."""
    if path.suffix.lower() not in TEXT_DELIVERABLES or not path.is_file() or path.stat().st_size > MAX_ITEM:
        return None
    data = path.read_bytes()
    text = plain_text(data.decode("utf-8", "replace"), path.suffix.lower())
    proofs = check_text(text, session_index(store, session))
    return store.save_proof(str(path.resolve()), session, hashlib.sha256(data).hexdigest(), proofs)
