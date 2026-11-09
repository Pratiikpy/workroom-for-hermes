"""A Workroom project: discover ties between documents and sources, plan a refresh, stage it for release.

Discovery writes nothing to the user's files. Ties live in the project database. A refresh edits only numbers
that are tied to a source cell whose value changed since the last release.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from .build.formats import plain
from .match.engine import Mention, MatchResult, SourceIndex, match_mentions, tokens
from .match.tables import REASON as TABLE_ALIGNMENT
from .match.tables import align_tables
from .match.numbers import _TRANSFORMS, consistent_with_source, format_like, parse_numbers
from .ooxml.package import PackageError, open_package
from .ooxml.runs import EditError
from .ooxml.book import Book
from .ooxml.docx import Doc
from .ooxml.pptx import Deck, DocMention


def is_scene(rel: str) -> bool:
    return rel.lower().endswith(".scene.json")


def open_document(data: bytes, name: str):
    """A PowerPoint deck or a Word document; both expose mentions(), edit_mention() and serialize()."""
    low = name.lower()
    return Doc(data) if low.endswith(".docx") else Book(data) if low.endswith(".xlsx") else Deck(data)
from .ooxml.xlsx import SourceCell, index_workbook

SOURCE_EXT = (".xlsx",)
DECK_EXT = (".pptx", ".docx", ".xlsx")
CONFIG_NAME = "workroom.json"


@dataclass(frozen=True)
class Tie:
    id: int
    deck: str
    slide: int
    shape_id: int
    para: int
    seg: int
    offset: int
    cell_rc: tuple[int, int] | None
    raw: str
    state: str  # accepted | confirm | confirmed | skipped | held (the number was changed by hand; Workroom leaves it alone)
    src_file: str
    sheet: str
    ref: str
    transform: str
    linked_value: float
    label_score: float
    context: str = ""
    slide_uid: str = ""  # the slide's stable id (part or sheet name for Word and Excel); empty on links made before stable anchors
    fp_near: str = ""  # fingerprint of the number and the words around it, used to re-attach the link after a structural edit
    anchor: str = "exact"  # exact | reanchored (found again by fingerprint after the document changed)
    prior_state: str = ""  # the state to return to when a held number is put back
    held_note: str = ""
    basis: str = "matched"  # born (written by a Workroom builder from this very cell) | matched | confirmed
    receipt: str = ""  # JSON: the fact selection receipt of a born tie
    kind: str = "text"  # text (a number in a text shape or table) | chart (one data point of a native chart) | derived (a number calculated from source cells)
    chart: str = ""  # JSON for a chart tie: {"series": index, "category": label}
    formula: str = ""  # JSON for a derived tie: {"op": "pct_change"|"ratio"|"diff"|"sum", "terms": [[file, sheet, ref], ...], "cue": "up"|"down"|"", "labels": [...]}
    src_labels: str = ""  # JSON [row headings, column headings] of the source cell when the tie was made, so the tie can follow the cell if the sheet is edited


@dataclass(frozen=True)
class Impact:
    deck: str
    slide: int
    old_text: str
    new_text: str
    src: str
    old_value: float
    new_value: float


@dataclass
class Plan:
    impacts: list[Impact] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # sources that moved and were followed, headings that changed


@dataclass(frozen=True)
class Element:
    """One place in a document that depends on a changed source cell, and what Workroom will do about it."""
    tie_id: int
    deck: str
    slide: int
    text_before: str
    text_after: str
    decision: str  # auto | hold | blocked
    reason: str
    sentence: str = ""  # the words around the number, so two numbers on one slide can be told apart


@dataclass(frozen=True)
class SourceChange:
    src: str  # file!sheet!ref
    label: str  # the row and column headings of the source cell
    old_value: float
    new_value: float
    delta_pct: float
    elements: tuple[Element, ...]
    kind: str = "source"  # source (a cell changed) | calculation (a number calculated from cells follows them)
    unit: str = ""  # "%" when the old and new values are shown as percentages


@dataclass(frozen=True)
class Inbox:
    changes: list[SourceChange]
    blocked: list[Element]


@dataclass(frozen=True)
class Discovery:
    found: int
    no_source: int
    kept: int
    unreadable: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    uncalculated: tuple[tuple[str, int], ...] = ()
    reanchored: int = 0
    held: int = 0


_INDEX_CACHE: OrderedDict[tuple, tuple[SourceIndex, list[str], dict[str, int]]] = OrderedDict()  # the two most recently read source sets, shared by every Project in this process
_INDEX_LOCK = threading.Lock()


class Project:
    def __init__(self, root: Path, state: Path) -> None:
        self.root = Path(root).resolve()
        self.state = Path(state).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.state / "project.db"), isolation_level=None)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS ties (id INTEGER PRIMARY KEY AUTOINCREMENT, deck TEXT, slide INT, shape_id INT, para INT,"
            " seg INT, offset INT, cell_rc TEXT, raw TEXT, state TEXT, src_file TEXT, sheet TEXT, ref TEXT, transform TEXT,"
            " linked_value REAL, label_score REAL, context TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS snapshot2 (file TEXT, sheet TEXT, key TEXT, value REAL, PRIMARY KEY (file, sheet, key))")
        for column in ("context TEXT", "slide_uid TEXT", "fp_near TEXT", "anchor TEXT", "prior_state TEXT", "held_note TEXT", "basis TEXT", "receipt TEXT", "kind TEXT", "chart TEXT", "formula TEXT", "src_labels TEXT"):
            try:
                self.db.execute(f"ALTER TABLE ties ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass  # column already exists

    # ---- files ----
    def _config(self) -> dict:
        p = self.root / CONFIG_NAME
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def set_config(self, **values) -> dict:
        """Write settings to workroom.json next to the documents, keeping every other key the owner put there."""
        cfg = {**self._config(), **values}
        path = self.root / CONFIG_NAME
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return cfg

    def _matching(self, patterns: list[str]) -> set[Path]:
        out: set[Path] = set()
        for pat in patterns:
            out.update(x for x in self.root.glob(pat) if x.is_file())
        return out

    def _derived_path(self) -> Path:
        return self.state / "derived.json"

    def derived(self) -> list[str]:
        """Workbooks Workroom created from the sources. They are targets (edited like documents), never sources."""
        try:
            return list(json.loads(self._derived_path().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return []

    def set_derived(self, rel: str, present: bool) -> None:
        items = [x for x in self.derived() if x != rel]
        if present:
            items.append(rel)
        self._derived_path().write_text(json.dumps(sorted(items)), encoding="utf-8")

    def _files(self, exts: tuple[str, ...]) -> list[Path]:
        """Source workbooks are every .xlsx unless workroom.json lists `targets`; target workbooks are edited like documents."""
        cfg = self._config()
        targets = self._matching(cfg.get("targets", [])) | {self.root / d for d in self.derived()}
        files = [p for p in self.root.rglob("*") if p.suffix.lower() in exts and not p.name.startswith("~$")]
        if exts == SOURCE_EXT:
            return sorted(p for p in files if p not in targets)
        return sorted(p for p in files if p.suffix.lower() != ".xlsx" or p in targets)

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def source_index(self) -> SourceIndex:
        """Every numeric source cell with its labels. Parsing and indexing a large workbook is the slow part of reading a project, so the
        result is kept while the workbooks' bytes (compared by digest, never by timestamp) are unchanged."""
        files = [(p, p.read_bytes()) for p in self._files(SOURCE_EXT)]
        key = (str(self.root), tuple((self._rel(p), hashlib.sha256(b).digest()) for p, b in files))
        with _INDEX_LOCK:
            cached = _INDEX_CACHE.get(key)
            if cached is not None:
                _INDEX_CACHE.move_to_end(key)
        if cached is not None:
            self.unreadable_sources = list(cached[1])
            self.uncalculated_sources = dict(cached[2])
            return cached[0]
        cells: list[SourceCell] = []
        self.unreadable_sources = []
        self.uncalculated_sources = {}
        for p, data in files:
            stats: dict = {}
            try:
                cells.extend(index_workbook(open_package(data), file=self._rel(p), stats=stats))
            except (PackageError, EditError, KeyError, ValueError):
                self.unreadable_sources.append(self._rel(p))
            if stats.get("uncalculated"):
                self.uncalculated_sources[self._rel(p)] = stats["uncalculated"]
        index = SourceIndex(cells)
        with _INDEX_LOCK:
            _INDEX_CACHE[key] = (index, list(self.unreadable_sources), dict(self.uncalculated_sources))
            while len(_INDEX_CACHE) > 2:
                _INDEX_CACHE.popitem(last=False)
        return index

    # ---- born ties ----
    def locate_born(self, rel: str, data: bytes, occurrences: list[tuple[str, str, str, str]], values: dict[str, float]) -> list[tuple[DocMention, str, str]]:
        """Find, in a file a builder just made, the number each slot rendered. Returns (mention, fact id, transform) in slot order.

        Raises ValueError when a slot cannot be found exactly once where it should be, or when the shown number could not be rewritten
        faithfully from its source later. Nothing is staged on that error."""
        dms = list(open_document(data, rel).mentions())
        used: set[int] = set()
        found: list[tuple[DocMention, str, str]] = []
        cursor: dict[str, int] = {}
        for path, fact, rendered, text in occurrences:
            start = text.find(rendered, cursor.get(path, 0))
            if start < 0:
                raise ValueError(f"{path}: the rendered number {rendered!r} is not in its text")
            cursor[path] = start + len(rendered)
            hit = next((i for i, d in enumerate(dms) if i not in used and d.number.raw == rendered and d.para_offset == start
                        and d.context and d.context[0] == text), None)
            if hit is None:
                raise ValueError(f"{path}: {rendered!r} was not found in the built file where it was written")
            ok, transform = consistent_with_source(dms[hit].number, values[fact])
            if not ok:
                raise ValueError(f"{path}: {rendered!r} cannot be rewritten faithfully from {values[fact]}")
            used.add(hit)
            found.append((dms[hit], fact, transform))
        return found

    def register_born_ties(self, rel: str, found: list[tuple[DocMention, str, str]], receipts: list[dict], values: dict[str, float]) -> int:
        for (dm, fact, transform), receipt in zip(found, receipts):
            file, sheet, ref = receipt["source_ref"].split("!", 2)
            self.db.execute(
                "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis, receipt)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rel, dm.slide, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), dm.number.raw, "confirmed", file, sheet, ref, transform,
                 values[fact], 1.0, dm.context[0] if dm.context else "", dm.slide_uid, self._fp_near(dm), "exact", "born", json.dumps(receipt)),
            )
        return len(found)

    def locate_cells(self, rel: str, data: bytes, cells: list[dict], values: dict[str, float]) -> list[tuple[DocMention, str, str]]:
        """Find the numeric cells a workbook builder wrote and check each can be rewritten faithfully from its source later."""
        dms = {(d.slide, d.cell): d for d in open_document(data, rel).mentions()}
        out = []
        for c in cells:
            dm = dms.get((c["sheet"] + 1, (c["row"], c["col"])))
            if dm is None:
                raise ValueError(f"{c['where']}: the cell was not found in the built workbook")
            ok, transform = consistent_with_source(dm.number, values[c["fact"]])
            if not ok:
                raise ValueError(f"{c['where']}: the cell holds {dm.number.raw}, which cannot be rewritten faithfully from {values[c['fact']]}")
            out.append((dm, c["fact"], transform))
        return out

    def register_scene_ties(self, rel: str, scene: dict, occurrences: list[tuple[str, str, str, str]], receipts: list[dict], values: dict[str, float]) -> int:
        """Born ties for the tied text of a visual page: one per slot, addressed by node id and slot number."""
        import re as _re

        count: dict[str, int] = {}
        n = 0
        for (path, fact, rendered, text), receipt in zip(occurrences, receipts):
            m = _re.match(r"scene\.nodes\[(\d+)\]\.text$", path)
            if not m:
                raise ValueError(f"{path}: not a text node of the scene")
            node = scene["nodes"][int(m.group(1))]
            if node.get("text") != text:
                raise ValueError(f"{path}: the page text does not hold what was rendered")
            slot = count.get(node["id"], 0)
            count[node["id"]] = slot + 1
            file, sheet, ref = receipt["source_ref"].split("!", 2)
            self.db.execute(
                "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis, receipt, kind, chart)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rel, 0, 0, 0, 0, 0, json.dumps(None), rendered, "confirmed", file, sheet, ref, "exact", values[fact], 1.0,
                 f"node {node['id']}: {text}", "", "", "exact", "born", json.dumps(receipt), "scene", json.dumps({"node": node["id"], "slot": slot, "fact": fact})),
            )
            n += 1
        return n

    def _plan_scene(self, plan: Plan, deck_rel: str, items: list[tuple[Tie, float]]) -> None:
        """Re-render the tied text of a visual page from new source values. A node whose text no longer matches its template was edited by hand and is held."""

        from .build.formats import format_value
        from .build.spec import SLOT

        doc = json.loads((self.root / deck_rel).read_bytes().decode("utf-8"))
        cache = dict(doc.get("cache", {}))
        nodes = {n["id"]: n for n in doc["nodes"]}
        changed: dict[str, dict[str, float]] = {}
        meta: dict[int, dict] = {}
        for t, new in items:
            info = json.loads(t.chart)
            meta[t.id] = info
            changed.setdefault(info["node"], {})[info["fact"]] = new

        def render(template: str, vals: dict[str, float]) -> str:
            return SLOT.sub(lambda m: format_value(m.group(2), vals[m.group(1)]), template)

        held_nodes: set[str] = set()
        for node_id, fresh in changed.items():
            node = nodes.get(node_id)
            if node is None or "template" not in node or node.get("text") != render(node["template"], cache):
                held_nodes.add(node_id)
                continue
            vals = {**cache, **fresh}
            node["text"] = render(node["template"], vals)
        applied = 0
        for t, new in items:
            info = meta[t.id]
            if info["node"] in held_nodes:
                plan.skipped.append(f"{deck_rel} slide {t.slide}: '{t.raw}' was changed by hand in the page; held")
                continue
            node = nodes[info["node"]]
            slots = list(SLOT.finditer(node["template"]))
            new_text = format_value(slots[info["slot"]].group(2), new)
            plan.impacts.append(Impact(deck_rel, t.slide, t.raw, new_text, f"{t.src_file}!{t.sheet}!{t.ref}", t.linked_value, new))
            cache[info["fact"]] = new
            applied += 1
        if applied:
            doc["cache"] = cache
            plan.files[deck_rel] = (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")

    def _commit_scene(self, deck_rel: str, data: bytes, values: dict) -> None:

        from .build.formats import format_value
        from .build.spec import SLOT

        doc = json.loads(data.decode("utf-8"))
        nodes = {n["id"]: n for n in doc["nodes"]}
        for t in self.ties():
            if t.deck != deck_rel or t.kind != "scene":
                continue
            info = json.loads(t.chart)
            node = nodes.get(info["node"])
            if node is None or "template" not in node:
                continue
            slots = list(SLOT.finditer(node["template"]))
            if info["slot"] >= len(slots):
                continue
            new = doc.get("cache", {}).get(info["fact"], t.linked_value)
            self.db.execute("UPDATE ties SET linked_value=?, raw=?, context=? WHERE id=?",
                            (new, format_value(slots[info["slot"]].group(2), new), f"node {node['id']}: {node['text']}", t.id))

    def locate_charts(self, rel: str, data: bytes, points: list[dict], values: dict[str, float]) -> list[dict]:
        """Find the chart each chart block became and check that every tied point holds exactly its fact's value."""
        if not points:
            return []
        deck = open_document(data, rel)
        shapes = deck.chart_shapes()
        out = []
        order: dict[str, int] = {}
        for pt in points:
            order.setdefault(pt["chart"], len(order))
        for pt in points:
            idx = order[pt["chart"]]
            if idx >= len(shapes):
                raise ValueError(f"{pt['chart']}: the chart was not found in the built file")
            slide_no, uid, shape_id, _ = shapes[idx]
            series = deck.chart_series(slide_no, shape_id)
            if pt["series"] >= len(series) or pt["point"] >= len(series[pt["series"]].values):
                raise ValueError(f"{pt['where']}: no such point in the built chart")
            got = series[pt["series"]].values[pt["point"]]
            want = values[pt["fact"]]
            if got is None or abs(got - want) > 1e-9 * max(1.0, abs(want)):
                raise ValueError(f"{pt['where']}: the built chart holds {got}, the source says {want}")
            out.append({**pt, "slide": slide_no, "slide_uid": uid, "shape_id": shape_id})
        return out

    def register_chart_ties(self, rel: str, located: list[dict], values: dict[str, float]) -> int:
        for pt in located:
            file, sheet, ref = pt["receipt"]["source_ref"].split("!", 2)
            self.db.execute(
                "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis, receipt, kind, chart)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rel, pt["slide"], pt["shape_id"], pt["series"], pt["point"], 0, json.dumps(None), plain(values[pt['fact']]), "confirmed", file, sheet, ref,
                 "exact", values[pt["fact"]], 1.0, f"chart point {pt['category']}", pt["slide_uid"], "", "exact", "born", json.dumps(pt["receipt"]), "chart",
                 json.dumps({"series": pt["series"], "category": pt["category"]})),
            )
        return len(located)

    # ---- anchors ----
    @staticmethod
    def _fp_near(dm: DocMention) -> str:
        """The number, the two words on each side of it and its row and column headings. Survives text added elsewhere."""
        text = dm.context[0] if dm.context else ""
        raw = dm.number.raw
        pos = dm.para_offset if dm.para_offset is not None and text[dm.para_offset : dm.para_offset + len(raw)] == raw else text.find(raw)
        pos = max(pos, 0)
        words = lambda part: re.findall(r"\w+", part.lower())  # noqa: E731
        before = words(text[:pos])[-2:]
        after = words(text[pos + len(raw) :])[:2]
        heads = [h.lower() for h in dm.context[1:]]
        return hashlib.sha1("|".join([raw, " ".join(before), " ".join(after), "/".join(heads)]).encode()).hexdigest()[:16]

    @staticmethod
    def _mkey(dm: DocMention, uid: str | None = None) -> tuple:
        return (uid if uid is not None else (dm.slide_uid or f"#{dm.slide}"), dm.shape_id, dm.para, dm.seg, dm.offset, dm.cell)

    @staticmethod
    def _tkey(t: Tie) -> tuple:
        return (t.slide_uid or f"#{t.slide}", t.shape_id, t.para, t.seg, t.offset, t.cell_rc)

    # ---- discover ----
    def _discover_charts(self, rel: str, deck, index: SourceIndex, chart_ties: list[Tie], kept_ids: set[int]) -> None:
        """Link the points of charts that were already in the deck to the cells they came from.

        The chart's own words are the evidence: the series name and the category label, matched against the workbook's row and column
        headings exactly as for a figure in a sentence. A point nothing names is left unlinked (a value alone is a coincidence). Links made
        earlier are kept while their chart point is still there; ones whose chart was removed are dropped."""
        if not hasattr(deck, "chart_shapes"):
            return
        live = {(t.slide_uid or f"#{t.slide}", t.shape_id, t.para, t.seg): t for t in chart_ties}
        try:
            shapes = deck.chart_shapes()
        except (EditError, KeyError, ValueError):
            kept_ids.update(t.id for t in chart_ties)
            return
        for slide_no, uid, shape_id, _name in shapes:
            if not deck.chart_writable(slide_no, shape_id):
                kept_ids.update(t.id for t in chart_ties if t.shape_id == shape_id and (t.slide_uid or f"#{t.slide}") == (uid or f"#{slide_no}"))
                continue  # nothing could be written back to this chart, so none of its points is linked
            try:
                series = deck.chart_series(slide_no, shape_id)
            except (EditError, KeyError, ValueError):
                kept_ids.update(t.id for t in chart_ties if t.shape_id == shape_id and (t.slide_uid or f"#{t.slide}") == (uid or f"#{slide_no}"))
                continue
            for si, ser in enumerate(series):
                for pi, value in enumerate(ser.values):
                    if value is None:
                        continue
                    key = (uid or f"#{slide_no}", shape_id, si, pi)
                    old = live.get(key)
                    if old is not None:
                        kept_ids.add(old.id)
                        if old.slide != slide_no:
                            self.db.execute("UPDATE ties SET slide=? WHERE id=?", (slide_no, old.id))
                        continue
                    category = ser.categories[pi] if pi < len(ser.categories) else ""
                    if not category or list(ser.categories).count(category) != 1:
                        continue  # a point is rewritten by its category, which must name it exactly once
                    if "!" not in (ser.val_formula or ""):
                        continue  # values typed into the chart with no sheet behind them cannot be written back, so they are not linked
                    mentions = parse_numbers(repr(float(value)))
                    if not mentions:
                        continue
                    res = match_mentions([Mention(f"chart:{key}", mentions[0], (str(ser.name or ""), str(category)))], index)[0]
                    # the cell must carry every word of the series name and of the category: "Series 2" is not "Series 1", whatever the values
                    need = set(tokens(str(ser.name or ""))) | set(tokens(str(category)))
                    pick = next((c for c in res.candidates if not c.period_conflict and c.label_score >= 0.15
                                 and need <= set(tokens(" ".join(c.cell.row_labels + c.cell.col_labels + (c.cell.sheet,))))), None)
                    if pick is None:
                        continue
                    ok, transform = consistent_with_source(mentions[0], pick.cell.value)
                    if not ok:
                        continue
                    res = MatchResult(res.mention, res.decision if pick is res.best else "confirm", pick, res.runner_up, res.reason, res.candidates)
                    self.db.execute(
                        "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis, receipt, kind, chart)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rel, slide_no, shape_id, si, pi, 0, json.dumps(None), plain(value), "accepted" if res.decision == "accept" else "confirm", res.best.cell.file,
                         res.best.cell.sheet, res.best.cell.ref, transform, res.best.cell.value, res.best.label_score, f"chart point {category}", uid, "", "exact", "matched", "", "chart",
                         json.dumps({"series": si, "category": category})),
                    )

    @contextlib.contextmanager
    def _transaction(self):
        """One transaction around a group of writes. Nested uses join the outermost one. Each statement on its own is a synced write, which
        made reading a project with a thousand links take minutes."""
        depth = getattr(self, "_tx_depth", 0)
        if depth == 0:
            self.db.execute("BEGIN")
        self._tx_depth = depth + 1
        try:
            yield
        except BaseException:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self.db.execute("ROLLBACK")
            raise
        else:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self.db.execute("COMMIT")

    def discover(self) -> Discovery:
        with self._transaction():
            return self._discover()

    def _discover(self) -> Discovery:
        """Find numbers and link new ones. A link that already exists is kept as it is: its state (confirmed or skipped by the
        owner), its source cell and the value it was linked at, even when the source value has since changed.

        A link is found again by, in order: its exact place (the slide's stable id, shape, paragraph, run position and cell);
        then, if the document was edited around it, its fingerprint (the number and the words next to it), shown as
        'reanchored'. A tied number that a person retyped becomes 'held' and is left alone; it returns to its old state when the
        original number is put back. A link is dropped only when its number is gone."""
        self.relocate_sources()
        index = self.source_index()
        self._seed_snapshot(index.cells)
        existing = self.ties()
        kept_ids: set[int] = set()
        found = no_source = kept = reanchored = 0
        unreadable: list[str] = []
        for p in self._files(DECK_EXT):
            rel = self._rel(p)
            deck_ties = [t for t in existing if t.deck == rel and t.kind in ("text", "derived")]
            chart_ties = [t for t in existing if t.deck == rel and t.kind == "chart"]
            kept_ids.update(t.id for t in chart_ties if t.basis != "matched")  # points of charts Workroom built stay as they are
            try:
                deck = open_document(p.read_bytes(), p.name)
                dms = list(deck.mentions())
            except (PackageError, EditError, KeyError, ValueError):
                unreadable.append(rel)
                kept_ids.update(t.id for t in deck_ties)  # its links are not lost because the file cannot be read now
                kept_ids.update(t.id for t in chart_ties)
                continue
            self._discover_charts(rel, deck, index, chart_ties, kept_ids)
            results = match_mentions([Mention(str(i), dm.number, dm.context, (dm.para_offset, dm.para_offset + len(dm.number.raw)) if dm.para_offset is not None else None) for i, dm in enumerate(dms)], index)
            results = align_tables(dms, results, index)
            found += len(dms)
            by_pos = {self._tkey(t): t for t in deck_ties}
            matched: dict[int, DocMention] = {}
            consumed: set[int] = set()
            via_fingerprint: set[int] = set()
            held_now: dict[int, DocMention] = {}
            # pass 1: the exact place
            for i, dm in enumerate(dms):
                t = by_pos.get(self._mkey(dm)) or by_pos.get(self._mkey(dm, f"#{dm.slide}"))
                if t is not None and t.id not in matched and t.raw == dm.number.raw:
                    matched[t.id] = dm
                    consumed.add(i)
            # pass 2: the number and the words around it, when exactly one link and one number fit
            pending_ties = [t for t in deck_ties if t.id not in matched and t.fp_near and t.state != "held"]
            pending_dms = [(i, dm) for i, dm in enumerate(dms) if i not in consumed]
            if pending_ties and pending_dms:
                tf: dict[str, list[Tie]] = {}
                for t in pending_ties:
                    tf.setdefault(t.fp_near, []).append(t)
                mf: dict[str, list[tuple[int, DocMention]]] = {}
                for i, dm in pending_dms:
                    mf.setdefault(self._fp_near(dm), []).append((i, dm))
                for fp, ts in tf.items():
                    if len(ts) == 1 and len(mf.get(fp, [])) == 1:
                        i, dm = mf[fp][0]
                        if ts[0].raw == dm.number.raw:
                            matched[ts[0].id] = dm
                            consumed.add(i)
                            via_fingerprint.add(ts[0].id)
            # pass 3: a tied number that a person changed in place is held, not forgotten, unless they corrected it to exactly what the source says now
            adopted: dict[int, tuple[DocMention, float, dict | None]] = {}
            values_now: dict[tuple[str, str, str], float] | None = None

            def retyped(t: Tie, dm: DocMention) -> None:
                nonlocal values_now
                if values_now is None:
                    values_now = self._current_values()
                now_v = self._tie_value(t, values_now)
                if now_v is not None and t.state != "held" and self._shows(dm.number, t, now_v):
                    adopted[t.id] = (dm, now_v, None)  # a person corrected it to exactly what the source says now: it stays managed
                    return
                moved = self._hand_rolled(t, dm, index, values_now) if t.state != "held" else None
                if moved is not None:
                    adopted[t.id] = (dm, moved["value"], moved)  # a person moved it to another period by hand: the tie follows
                else:
                    held_now[t.id] = dm

            for t in deck_ties:
                if t.id in matched:
                    continue
                for i, dm in enumerate(dms):
                    if i not in consumed and self._mkey(dm) == self._tkey(t) or (i not in consumed and self._mkey(dm, f"#{dm.slide}") == self._tkey(t)):
                        if dm.number.raw != t.raw:
                            retyped(t, dm)
                            consumed.add(i)
                        break
            # pass 4: words were added or removed before a number that was also retyped, so its place moved; within one paragraph, when the
            # leftover links and the leftover numbers are equally many, they pair in order
            left = [t for t in deck_ties if t.id not in matched and t.id not in held_now and t.id not in adopted]
            if left:
                tgroups: dict[tuple, list[Tie]] = {}
                for t in left:
                    tgroups.setdefault((t.slide_uid or f"#{t.slide}", t.shape_id, t.para, t.cell_rc), []).append(t)
                dgroups: dict[tuple, list[tuple[int, DocMention]]] = {}
                for i, dm in enumerate(dms):
                    if i not in consumed:
                        dgroups.setdefault((dm.slide_uid or f"#{dm.slide}", dm.shape_id, dm.para, dm.cell), []).append((i, dm))
                for key, ts in tgroups.items():
                    ds = sorted(dgroups.get(key, []), key=lambda x: (x[1].seg, x[1].offset))
                    ts.sort(key=lambda t: (t.seg, t.offset))
                    if len(ts) != len(ds):
                        continue
                    for t, (i, dm) in zip(ts, ds):
                        consumed.add(i)
                        if dm.number.raw == t.raw:
                            matched[t.id] = dm
                            via_fingerprint.add(t.id)
                        else:
                            retyped(t, dm)
            for tid, dm in matched.items():
                old = next(t for t in deck_ties if t.id == tid)
                state = old.state
                note = old.held_note
                prior = old.prior_state
                if old.state == "held":  # the original number is back
                    state = old.prior_state or "confirm"
                    note = prior = ""
                self.db.execute(
                    "UPDATE ties SET slide=?, slide_uid=?, shape_id=?, para=?, seg=?, offset=?, cell_rc=?, fp_near=?, anchor=?, context=?, state=?, held_note=?, prior_state=? WHERE id=?",
                    (dm.slide, dm.slide_uid, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), self._fp_near(dm),
                     "reanchored" if tid in via_fingerprint else "exact", dm.context[0] if dm.context else "", state, note, prior, tid),
                )
                kept_ids.add(tid)
                kept += 1
                reanchored += tid in via_fingerprint
            for tid, (dm, now_v, moved) in adopted.items():
                old = next(t for t in deck_ties if t.id == tid)
                formula = old.formula
                if moved is not None:
                    f_, sh_, rf_ = moved["src"]
                    self.db.execute("UPDATE ties SET src_file=?, sheet=?, ref=?, src_labels=NULL WHERE id=?", (f_, sh_, rf_, tid))
                    if moved.get("formula"):
                        formula = moved["formula"]
                if old.kind == "derived":
                    from .meaning.calc import direction_cue

                    text = dm.context[0] if dm.context else ""
                    pos = dm.para_offset if dm.para_offset is not None else max(text.find(dm.number.raw), 0)
                    formula = json.dumps({**json.loads(formula), "cue": direction_cue(text, pos, pos + len(dm.number.raw))})
                self.db.execute(
                    "UPDATE ties SET slide=?, slide_uid=?, shape_id=?, para=?, seg=?, offset=?, cell_rc=?, fp_near=?, anchor='exact', context=?, raw=?, linked_value=?, formula=? WHERE id=?",
                    (dm.slide, dm.slide_uid, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), self._fp_near(dm), dm.context[0] if dm.context else "", dm.number.raw, now_v, formula, tid),
                )
                kept_ids.add(tid)
                kept += 1
            for tid, dm in held_now.items():
                old = next(t for t in deck_ties if t.id == tid)
                prior = old.prior_state if old.state == "held" else old.state
                self.db.execute("UPDATE ties SET state='held', prior_state=?, held_note=?, slide=? WHERE id=?",
                                (prior, f"you changed {old.raw} to {dm.number.raw} by hand", dm.slide, tid))
                kept_ids.add(tid)
            for i, (dm, res) in enumerate(zip(dms, results)):
                if i in consumed:
                    continue
                if res.best is None:
                    no_source += 1
                    continue
                b = res.best
                ok, transform = consistent_with_source(dm.number, b.cell.value)
                self.db.execute(
                    "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context, slide_uid, fp_near, anchor, basis)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rel, dm.slide, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), dm.number.raw,
                     "accepted" if res.decision == "accept" else "confirm", b.cell.file, b.cell.sheet, b.cell.ref, transform,
                     b.cell.value, b.label_score, dm.context[0] if dm.context else "", dm.slide_uid, self._fp_near(dm), "exact",
                     "aligned" if res.reason.startswith(TABLE_ALIGNMENT) else "matched"),
                )
        present = {self._rel(p) for p in self._files(DECK_EXT)}
        missing = sorted({t.deck for t in existing if t.kind != "scene" and t.deck not in present})
        kept_ids.update(t.id for t in existing if t.deck in missing)  # a document that is away for a moment (a save in progress, a sync) keeps every link and decision
        for tie in existing:
            if tie.id not in kept_ids and tie.kind != "scene":
                self.db.execute("DELETE FROM ties WHERE id=?", (tie.id,))
        self.relocate_sources()  # remembers the headings of the ties just made
        held = self.db.execute("SELECT COUNT(*) FROM ties WHERE state='held'").fetchone()[0]
        return Discovery(found=found, no_source=no_source, kept=kept, unreadable=tuple(unreadable) + tuple(getattr(self, "unreadable_sources", [])), missing=tuple(missing), uncalculated=tuple(sorted(getattr(self, "uncalculated_sources", {}).items())), reanchored=reanchored, held=held)

    def ties(self, states: tuple[str, ...] | None = None) -> list[Tie]:
        cur = self.db.execute("SELECT * FROM ties ORDER BY id")
        names = [d[0] for d in cur.description]
        ties = []
        for r in cur.fetchall():
            row = dict(zip(names, r))
            cell = json.loads(row["cell_rc"]) if row["cell_rc"] else None
            ties.append(Tie(row["id"], row["deck"], row["slide"], row["shape_id"], row["para"], row["seg"], row["offset"], tuple(cell) if cell else None,
                            row["raw"], row["state"], row["src_file"], row["sheet"], row["ref"], row["transform"], row["linked_value"], row["label_score"],
                            row.get("context") or "", row.get("slide_uid") or "", row.get("fp_near") or "", row.get("anchor") or "exact",
                            row.get("prior_state") or "", row.get("held_note") or "", row.get("basis") or "matched", row.get("receipt") or "", row.get("kind") or "text", row.get("chart") or "", row.get("formula") or "", row.get("src_labels") or ""))
        return [t for t in ties if states is None or t.state in states]

    def confirm(self, tie_id: int) -> None:
        """The owner says the source cell is the right one: it becomes the reference for its headings from now on."""
        t = self.tie(tie_id)
        if t is None or t.state != "confirm":
            return
        if t.kind == "derived":
            try:
                f = json.loads(t.formula)
                f.pop("labels", None)
                self.db.execute("UPDATE ties SET formula=? WHERE id=?", (json.dumps(f), tie_id))
            except ValueError:
                pass
        self.db.execute("UPDATE ties SET state='confirmed', src_labels=NULL, held_note='' WHERE id=?", (tie_id,))
        self.relocate_sources()

    def skip(self, tie_id: int) -> None:
        """The owner says this number is not tied to that cell; it is left alone from now on."""
        self.db.execute("UPDATE ties SET state='skipped' WHERE id=? AND state IN ('confirm','accepted','confirmed')", (tie_id,))

    def tie(self, tie_id: int):
        return next((t for t in self.ties() if t.id == tie_id), None)

    def relocate_sources(self) -> list[str]:
        """Check each tie's source cell against its remembered headings; follow cells that moved. Writes only this project's own database."""
        from .meaning.anchors import relocate_sources

        with self._transaction():
            self.last_notes = relocate_sources(self)
        return self.last_notes

    # ---- calculated numbers ----
    def calculations(self):
        """Numbers in the documents that a calculation over tied cells reproduces. Writes nothing."""
        from .meaning.scan import find_calculations

        return find_calculations(self)

    def accept_calculation(self, candidate_id: str, option: int = 0) -> int:
        from .meaning.scan import accept_calculation

        return accept_calculation(self, candidate_id, option)

    def dismiss_calculation(self, candidate_id: str) -> None:
        from .meaning.scan import dismiss_calculation

        dismiss_calculation(self, candidate_id)

    @staticmethod
    def _edit_number(doc, dm: DocMention, new_text: str) -> None:
        """Replace the number the mention points at. A figure written with an explicit plus that turns negative gives up its plus."""
        from dataclasses import replace

        text = dm.context[0] if dm.context else ""
        po = dm.para_offset
        if new_text.startswith(("-", "−")) and po is not None and po >= 1 and text[po - 1] == "+":
            doc.edit_mention(replace(dm, number=replace(dm.number, raw="+" + dm.number.raw, start=dm.number.start - 1), offset=dm.offset - 1), new_text)
        else:
            doc.edit_mention(dm, new_text)

    def plan_rollforward(self, steps: int = 1):
        """Everything needed to roll the project's documents to the next reporting period, as new file bytes. Writes nothing."""
        from .meaning.rollforward import plan_rollforward

        return plan_rollforward(self, steps)

    def apply_rollforward(self, meta: dict) -> None:
        from .meaning.rollforward import apply_rollforward

        apply_rollforward(self, meta)

    def revert_rollforward(self, meta: dict) -> dict:
        from .meaning.rollforward import revert_rollforward

        return revert_rollforward(self, meta)

    def consequences(self, plan: Plan, roll: dict | None = None):
        """What the planned update means for the sentences around the numbers: claims it makes false, and what could not be checked."""
        from .meaning.claimscan import claim_findings
        from .meaning.findings import sort_findings
        from .meaning.sourcehealth import source_findings
        from .meaning.surfaces import clipped_charts, surface_findings

        found, cov = claim_findings(self, plan, roll)
        merged = {f.id: f for f in found + surface_findings(self, plan, roll) + clipped_charts(self, plan) + source_findings(self, plan)}
        return sort_findings(list(merged.values())), cov

    def _hand_rolled(self, t: Tie, dm: DocMention, index, values: dict[tuple[str, str, str], float]) -> dict | None:
        """A person retyped a number to the value the same series holds in another period (they rolled it forward or back by hand).
        When exactly one such period fits, the tie moves to it instead of being held."""
        from .meaning.calc import evaluate
        from .meaning.timeline import Timeline

        tl = Timeline(index.cells)
        cells = {(c.file, c.sheet, c.ref): c for c in index.cells}
        found: list[tuple[int, dict]] = []
        for k in (1, 2, 3, 4, -1, -2, -3, -4):
            if t.kind == "derived":
                try:
                    f = json.loads(t.formula)
                except ValueError:
                    return None
                terms, ok = [], True
                for term in f["terms"]:
                    c = cells.get(tuple(term))
                    nxt = tl.shifted(c, k) if c is not None else None
                    if nxt is None:
                        ok = False
                        break
                    terms.append([nxt.file, nxt.sheet, nxt.ref])
                if not ok:
                    continue
                nf = json.dumps({**{a: b for a, b in f.items() if a != "labels"}, "terms": terms})
                v = evaluate(nf, values)
                if v is not None and self._shows(dm.number, t, v):
                    found.append((k, {"src": tuple(terms[0]), "value": v, "formula": nf}))
            else:
                c = cells.get((t.src_file, t.sheet, t.ref))
                nxt = tl.shifted(c, k) if c is not None else None
                if nxt is not None and consistent_with_source(dm.number, nxt.value)[0]:
                    found.append((k, {"src": (nxt.file, nxt.sheet, nxt.ref), "value": nxt.value, "formula": None}))
        if not found:
            return None
        # the nearest period wins, forward before backward; two equally near periods are not guessed between
        found.sort(key=lambda kv: (abs(kv[0]), -kv[0]))
        if len(found) > 1 and abs(found[0][0]) == abs(found[1][0]):
            return None
        return found[0][1]


    @staticmethod
    def _display_value(t: Tie, value: float) -> float:
        """A calculated change written beside "up" or "down" shows its size, not its sign."""
        if t.kind == "derived":
            try:
                if json.loads(t.formula).get("cue"):
                    return abs(value)
            except ValueError:
                pass
        return value

    @staticmethod
    def _shows(number, t: Tie, value: float) -> bool:
        """Is the number a person typed exactly what the source (or the calculation) says now?"""
        if consistent_with_source(number, value)[0]:
            return True
        return t.kind == "derived" and consistent_with_source(number, abs(value))[0]

    @staticmethod
    def _sign_fits(t: Tie, new: float) -> bool:
        """A calculated change written as up or down keeps its direction; a change that has turned over is held, not rewritten."""
        if t.kind != "derived":
            return True
        try:
            cue = json.loads(t.formula).get("cue", "")
        except ValueError:
            return True
        return not (cue == "up" and new <= 0 or cue == "down" and new >= 0)

    # ---- plan ----
    def _current_values(self) -> dict[tuple[str, str, str], float]:
        return {(c.file, c.sheet, c.ref): c.value for c in self.source_index().cells}

    @staticmethod
    def _snapshot_keys(cells) -> dict[tuple[str, str, str], str]:
        """A key for each source cell that survives rows and columns being inserted or the window of periods sliding: its headings
        (or its address, for a cell whose headings are not unique on its sheet)."""
        from .meaning.anchors import label_key

        count: dict[tuple[str, str, str], int] = {}
        for c in cells:
            k = (c.file, c.sheet, label_key(c))
            count[k] = count.get(k, 0) + 1
        return {(c.file, c.sheet, c.ref): (label_key(c) if count[(c.file, c.sheet, label_key(c))] == 1 else f"@{c.ref}") for c in cells}

    def snapshot_values(self) -> dict[tuple[str, str, str], float]:
        """Every source cell as it stood at the last release (or when it was first seen): the baseline that "changed" is measured against.
        Found by the cell's headings, so a cell that moved keeps its own baseline."""
        cells = self.source_index().cells
        keys = self._snapshot_keys(cells)
        stored = {(f, s, k): v for f, s, k, v in self.db.execute("SELECT file, sheet, key, value FROM snapshot2")}
        return {ref: stored.get((ref[0], ref[1], keys[ref]), c.value) for ref, c in ((((c.file, c.sheet, c.ref)), c) for c in cells)}

    def _seed_snapshot(self, cells) -> None:
        keys = self._snapshot_keys(cells)
        with self._transaction():
            self.db.executemany("INSERT OR IGNORE INTO snapshot2 (file, sheet, key, value) VALUES (?,?,?,?)", [(c.file, c.sheet, keys[(c.file, c.sheet, c.ref)], c.value) for c in cells])

    def _write_snapshot(self, values: dict[tuple[str, str, str], float]) -> None:
        cells = self.source_index().cells
        keys = self._snapshot_keys(cells)
        with self._transaction():
            self.db.executemany("INSERT OR REPLACE INTO snapshot2 (file, sheet, key, value) VALUES (?,?,?,?)",
                                [(c.file, c.sheet, keys[(c.file, c.sheet, c.ref)], values.get((c.file, c.sheet, c.ref), c.value)) for c in cells])

    @staticmethod
    def _tie_value(t: Tie, values: dict[tuple[str, str, str], float], default: float | None = None) -> float | None:
        """What a tie should show now: its source cell's value, or, for a calculated number, the calculation over the current cells."""
        if t.kind == "derived":
            from .meaning.calc import evaluate

            got = evaluate(t.formula, values)
            return default if got is None else got
        return values.get((t.src_file, t.sheet, t.ref), default)

    def plan_refresh(self) -> Plan:
        plan = Plan()
        plan.notes = self.relocate_sources()
        values = self._current_values()
        by_deck: dict[str, list[tuple[Tie, float]]] = {}
        for t in self.ties(("held",)):
            plan.skipped.append(f"{t.deck} slide {t.slide}: '{t.raw}' was changed by hand ({t.held_note}); held for you, not updated")
        for t in self.ties(("accepted", "confirmed")):
            new = self._tie_value(t, values)
            if new is None:
                plan.skipped.append(f"{t.deck} slide {t.slide}: source {t.src_file}!{t.sheet}!{t.ref} is missing{' or the calculation cannot be made' if t.kind == 'derived' else ''}; not changed")
                continue
            if not self._sign_fits(t, new):
                plan.skipped.append(f"{t.deck} slide {t.slide}: '{t.raw}' is a calculated change and its direction has turned over, so the words next to it no longer fit; held for you, not updated")
                continue
            if new != t.linked_value:
                by_deck.setdefault(t.deck, []).append((t, new))
        for deck_rel, items in by_deck.items():
            if is_scene(deck_rel):
                self._plan_scene(plan, deck_rel, items)
                continue
            if not (self.root / deck_rel).is_file():
                plan.skipped.append(f"{deck_rel}: the document is missing from the folder; its {len(items)} figure(s) were not changed and its links are kept")
                continue
            deck = open_document((self.root / deck_rel).read_bytes(), deck_rel)
            if self._config().get("tracked_changes") and hasattr(deck, "tracked"):
                deck.tracked = True
            dms: dict[tuple, DocMention] = {}
            for d in deck.mentions():
                dms[self._mkey(d)] = d
                dms.setdefault(self._mkey(d, f"#{d.slide}"), d)
            applied = 0
            for t, new in [x for x in items if x[0].kind == "chart"]:
                category = ""
                try:
                    category = json.loads(t.chart)["category"]
                    uids = deck.slide_uids()
                    slide_no = uids.index(t.slide_uid) + 1 if t.slide_uid in uids else t.slide
                    shape = _TRANSFORMS.get(t.transform, _TRANSFORMS["exact"])
                    new = shape(new, 1.0)
                    expected_now = shape(t.linked_value, 1.0)
                    sers = deck.chart_series(slide_no, t.shape_id)
                    holds = sers[t.para].values[t.seg] if t.para < len(sers) and t.seg < len(sers[t.para].values) else None
                    if holds is None or abs(holds - expected_now) > 1e-9 * max(1.0, abs(expected_now)):
                        plan.skipped.append(f"{deck_rel} slide {slide_no}: chart point '{category}' of series {t.para + 1} holds {holds} where Workroom last left {expected_now}; it was changed by hand, so it is held for you, not updated")
                        continue
                    deck.set_chart_value(slide_no, t.shape_id, t.para, category, new)
                except (EditError, ValueError, KeyError) as exc:
                    plan.skipped.append(f"{deck_rel} slide {t.slide}: chart point '{category or t.raw}' of series {t.para + 1} could not be updated ({exc}); held")
                    continue
                applied += 1
                plan.impacts.append(Impact(deck_rel, slide_no, t.raw, plain(new), f"{t.src_file}!{t.sheet}!{t.ref}", t.linked_value, new))
            for t, new in sorted([x for x in items if x[0].kind in ("text", "derived")], key=lambda x: (x[0].slide, x[0].shape_id, x[0].para, x[0].seg, -x[0].offset)):
                dm = dms.get(self._tkey(t))
                if dm is None or dm.number.raw != t.raw:
                    plan.skipped.append(f"{deck_rel} slide {t.slide}: '{t.raw}' is no longer where it was linked (edited by hand?); held")
                    continue
                shown = self._display_value(t, new)
                new_text = format_like(dm.number, shown, t.transform)
                ok, _ = consistent_with_source(_reparse(new_text), shown)
                if new_text == t.raw:
                    continue
                if not ok:
                    plan.skipped.append(f"{deck_rel} slide {t.slide}: could not write {new} as '{new_text}' faithfully; held")
                    continue
                self._edit_number(deck, dm, new_text)
                applied += 1
                plan.impacts.append(Impact(deck_rel, t.slide, t.raw, new_text, f"{t.src_file}!{t.sheet}!{t.ref}", t.linked_value, new))
            if applied:
                data, _report = deck.serialize()
                plan.files[deck_rel] = data
        return plan

    def impact(self) -> Inbox:
        """What the latest source changes touch, grouped by source cell and sorted by consequence (largest relative change first).

        Every linked element gets a decision: auto (a refresh will rewrite it), hold (a person changed it, or it cannot be written
        faithfully, so it is left alone) or blocked (its source cell is missing). Links the owner skipped, and links still waiting for
        confirmation, are not part of the inbox."""
        cells = {(c.file, c.sheet, c.ref): c for c in self.source_index().cells}
        cell_values = {k: c.value for k, c in cells.items()}
        plan = self.plan_refresh()
        auto = {(i.deck, i.slide, i.old_text, i.src): i for i in plan.impacts}
        groups: dict[str, list[Element]] = {}
        blocked: list[Element] = []
        meta: dict[str, tuple[float, float]] = {}
        from .meaning.calc import formula_words

        def label_of(k):
            c = cells.get(k)
            return " ".join(dict.fromkeys(c.row_labels + c.col_labels))[:40] if c is not None else "?"

        calc_meta: dict[str, tuple[str, str]] = {}
        for t in self.ties(("accepted", "confirmed", "held")):
            key = f"{t.src_file}!{t.sheet}!{t.ref}"
            if t.kind == "derived":
                key = "calculation: " + formula_words(t.formula, label_of)
                calc_meta[key] = (t.transform, formula_words(t.formula, label_of))
            cell = cells.get((t.src_file, t.sheet, t.ref))
            now = self._tie_value(t, cell_values) if t.kind == "derived" else (cell.value if cell is not None else None)
            if cell is None or now is None:
                blocked.append(Element(t.id, t.deck, t.slide, t.raw, "", "blocked", f"source {key} is missing; not changed", t.context))
                continue
            if now == t.linked_value:
                continue
            meta[key] = (t.linked_value, now)
            if t.state == "held":
                el = Element(t.id, t.deck, t.slide, t.raw, "", "hold", f"changed by hand: {t.held_note}", t.context)
            else:
                hit = auto.get((t.deck, t.slide, t.raw, key))
                if hit is not None:
                    el = Element(t.id, t.deck, t.slide, t.raw, hit.new_text, "auto", "rewritten from the source", t.context)
                else:
                    reason = next((x for x in plan.skipped if f"slide {t.slide}" in x and t.raw in x), "could not be written faithfully")
                    el = Element(t.id, t.deck, t.slide, t.raw, "", "hold", reason.split(": ", 1)[-1], t.context)
            groups.setdefault(key, []).append(el)
        out = []
        for key, els in groups.items():
            old, new = meta[key]
            if key in calc_meta:
                transform, words = calc_meta[key]
                scale = 100.0 if transform == "fraction_to_percent" else 1.0
                out.append(SourceChange(key, words, old * scale, new * scale, abs(new - old) * scale, tuple(els), "calculation", "%" if scale == 100.0 else ""))
                continue
            cell = cells[tuple(key.split("!"))]
            label = " ".join(dict.fromkeys(cell.row_labels + cell.col_labels))
            pct = abs(new - old) / abs(old) * 100 if old else 100.0
            out.append(SourceChange(key, label, old, new, pct, tuple(els)))
        out.sort(key=lambda c: -c.delta_pct)
        return Inbox(out, blocked)

    def _realign(self, ties: list[Tie], mentions: list[DocMention], values: dict[tuple[str, str, str], float]) -> None:
        """After a release, point each tie of one paragraph at the number it now sits on.

        A paragraph usually holds numbers that were never linked (a year, a count of offices), so ties and numbers are not one to one. Each
        tie looks, in order, for a number written as it was or as the release just wrote it, and among those takes the one nearest where it
        stood once earlier edits in the same text run are allowed for. A tie that finds nothing goes back to "confirm" by itself; the others
        in the paragraph are not disturbed."""
        ties = sorted(ties, key=lambda t: (t.seg, t.offset))
        taken: set[int] = set()
        shift: dict[int, int] = {}  # seg -> characters added by edits to the left, so far
        for t in ties:
            new = self._tie_value(t, values, t.linked_value)
            raws = {t.raw}
            probe = parse_numbers(t.raw)
            if probe and new is not None and t.kind in ("text", "derived"):
                try:
                    raws.add(format_like(probe[0], self._display_value(t, new), t.transform))
                except (ValueError, KeyError):
                    pass
            raws |= {r.lstrip("+") for r in raws}  # a plus written outside the number is not part of the mention
            expected = t.offset + shift.get(t.seg, 0)
            choices = [(abs(d.offset - expected) if d.seg == t.seg else 10**6 + abs(d.seg - t.seg), i) for i, d in enumerate(mentions) if i not in taken and d.number.raw in raws]
            if not choices:
                if t.state != "held":
                    self.db.execute("UPDATE ties SET state='confirm' WHERE id=?", (t.id,))
                continue
            _, i = min(choices)
            taken.add(i)
            d = mentions[i]
            shift[t.seg] = shift.get(t.seg, 0) + (len(d.number.raw) - len(t.raw) if d.number.raw != t.raw else 0)
            if t.state == "held":
                continue
            self.db.execute("UPDATE ties SET seg=?, offset=?, raw=?, linked_value=?, fp_near=? WHERE id=?", (d.seg, d.offset, d.number.raw, new, self._fp_near(d), t.id))

    def commit_snapshot(self, plan: Plan, override: dict[tuple[str, str, str], float] | None = None) -> None:
        """After a successful release: new source values become the baseline, and ties in edited decks are re-anchored.

        Numbers keep their order inside each text segment, so the n-th tie of a segment maps to the n-th number of the
        edited segment. If the count differs, the ties of that segment go back to 'confirm' instead of being guessed.
        """
        current = self._current_values()
        for deck_rel, data in plan.files.items():
            if not (is_scene(deck_rel) or deck_rel.lower().endswith(DECK_EXT)):
                continue  # an export (SVG, HTML) or any other file holds no ties
            if is_scene(deck_rel):
                self._commit_scene(deck_rel, data, {**current, **(override or {})})
                continue
            # a restored deck holds the numbers it had before a release, so its links go back to those baseline values
            values = {**current, **(override or {})}
            fresh: dict[tuple, list[DocMention]] = {}
            for d in open_document(data, deck_rel).mentions():
                for uid in {d.slide_uid or f"#{d.slide}", f"#{d.slide}"}:
                    fresh.setdefault((uid, d.shape_id, d.para, d.cell), []).append(d)
            groups: dict[tuple, list[Tie]] = {}
            for t in self.ties():
                if t.deck == deck_rel and t.kind == "chart":
                    new = self._tie_value(t, values, t.linked_value)
                    shown = _TRANSFORMS.get(t.transform, _TRANSFORMS["exact"])(new, 1.0)
                    self.db.execute("UPDATE ties SET linked_value=?, raw=? WHERE id=?", (new, plain(shown), t.id))
                elif t.deck == deck_rel:
                    groups.setdefault((t.slide_uid or f"#{t.slide}", t.shape_id, t.para, t.cell_rc), []).append(t)
            for key, ts in groups.items():
                self._realign(ts, sorted(fresh.get(key, []), key=lambda d: (d.seg, d.offset)), values)
        self._write_snapshot({**current, **(override or {})})
        for t in self.ties():
            if t.deck not in plan.files:
                new = self._tie_value(t, current)
                if new is not None:
                    self.db.execute("UPDATE ties SET linked_value=? WHERE id=?", (new, t.id))


def _reparse(text: str):
    from .match.numbers import parse_numbers

    return parse_numbers(text)[0]
