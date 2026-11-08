"""A Workroom project: discover ties between documents and sources, plan a refresh, stage it for release.

Discovery writes nothing to the user's files. Ties live in the project database. A refresh edits only numbers
that are tied to a source cell whose value changed since the last release.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .controller.release import Controller
from .match.engine import Mention, MatchResult, SourceIndex, match_mentions
from .match.numbers import consistent_with_source, format_like
from .ooxml.package import PackageError, open_package
from .ooxml.runs import EditError
from .ooxml.book import Book
from .ooxml.docx import Doc
from .ooxml.pptx import Deck, DocMention


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
    state: str  # accepted | confirm | confirmed | skipped
    src_file: str
    sheet: str
    ref: str
    transform: str
    linked_value: float
    label_score: float
    context: str = ""


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


@dataclass(frozen=True)
class Discovery:
    found: int
    no_source: int
    kept: int
    unreadable: tuple[str, ...] = ()


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
        try:
            self.db.execute("ALTER TABLE ties ADD COLUMN context TEXT")
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

    def _files(self, exts: tuple[str, ...]) -> list[Path]:
        """Source workbooks are every .xlsx unless workroom.json lists `targets`; target workbooks are edited like documents."""
        cfg = self._config()
        targets = self._matching(cfg.get("targets", []))
        files = [p for p in self.root.rglob("*") if p.suffix.lower() in exts and not p.name.startswith("~$")]
        if exts == SOURCE_EXT:
            return sorted(p for p in files if p not in targets)
        return sorted(p for p in files if p.suffix.lower() != ".xlsx" or p in targets)

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def source_index(self) -> SourceIndex:
        cells: list[SourceCell] = []
        self.unreadable_sources: list[str] = []
        for p in self._files(SOURCE_EXT):
            try:
                cells.extend(index_workbook(open_package(p.read_bytes()), file=self._rel(p)))
            except (PackageError, EditError, KeyError, ValueError):
                self.unreadable_sources.append(self._rel(p))
        return SourceIndex(cells)

    # ---- discover ----
    def discover(self) -> "Discovery":
        """Find numbers and link new ones. A link that already exists is kept as it is: its state (confirmed or skipped by the
        owner), its source cell and the value it was linked at, even when the source value has since changed. A link is dropped
        only when its number is no longer where it was or its text was edited."""
        index = self.source_index()
        existing = {(t.deck, t.slide, t.shape_id, t.para, t.seg, t.offset): t for t in self.ties()}
        kept_ids: set[int] = set()
        found = no_source = kept = 0
        unreadable: list[str] = []
        for p in self._files(DECK_EXT):
            rel = self._rel(p)
            try:
                deck = open_document(p.read_bytes(), p.name)
                dms = list(deck.mentions())
            except (PackageError, EditError, KeyError, ValueError):
                unreadable.append(rel)
                kept_ids.update(t.id for t in existing.values() if t.deck == rel)  # its links are not lost because the file cannot be read now
                continue
            results = match_mentions([Mention(str(i), dm.number, dm.context, (dm.para_offset, dm.para_offset + len(dm.number.raw)) if dm.para_offset is not None else None) for i, dm in enumerate(dms)], index)
            for dm, res in zip(dms, results):
                found += 1
                old = existing.get((rel, dm.slide, dm.shape_id, dm.para, dm.seg, dm.offset))
                if old is not None and old.raw == dm.number.raw:
                    kept_ids.add(old.id)
                    kept += 1
                    continue
                if res.best is None:
                    no_source += 1
                    continue
                b = res.best
                ok, transform = consistent_with_source(dm.number, b.cell.value)
                self.db.execute(
                    "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rel, dm.slide, dm.shape_id, dm.para, dm.seg, dm.offset, json.dumps(dm.cell), dm.number.raw,
                     "accepted" if res.decision == "accept" else "confirm", b.cell.file, b.cell.sheet, b.cell.ref, transform,
                     b.cell.value, b.label_score, dm.context[0] if dm.context else ""),
                )
        for tie in existing.values():
            if tie.id not in kept_ids:
                self.db.execute("DELETE FROM ties WHERE id=?", (tie.id,))
        return Discovery(found=found, no_source=no_source, kept=kept, unreadable=tuple(unreadable) + tuple(getattr(self, "unreadable_sources", [])))

    def ties(self, states: tuple[str, ...] | None = None) -> list[Tie]:
        rows = self.db.execute("SELECT * FROM ties ORDER BY id").fetchall()
        ties = [Tie(r[0], r[1], r[2], r[3], r[4], r[5], r[6], tuple(json.loads(r[7])) if r[7] and json.loads(r[7]) else None,
                    r[8], r[9], r[10], r[11], r[12], r[13], r[14], r[15], r[16] or "") for r in rows]
        return [t for t in ties if states is None or t.state in states]

    def confirm(self, tie_id: int) -> None:
        self.db.execute("UPDATE ties SET state='confirmed' WHERE id=? AND state='confirm'", (tie_id,))

    def skip(self, tie_id: int) -> None:
        """The owner says this number is not tied to that cell; it is left alone from now on."""
        self.db.execute("UPDATE ties SET state='skipped' WHERE id=? AND state IN ('confirm','accepted','confirmed')", (tie_id,))

    def tie(self, tie_id: int):
        return next((t for t in self.ties() if t.id == tie_id), None)

    # ---- plan ----
    def _current_values(self) -> dict[tuple[str, str, str], float]:
        return {(c.file, c.sheet, c.ref): c.value for c in self.source_index().cells}

    def plan_refresh(self) -> Plan:
        plan = Plan()
        values = self._current_values()
        by_deck: dict[str, list[tuple[Tie, float]]] = {}
        for t in self.ties(("accepted", "confirmed")):
            new = values.get((t.src_file, t.sheet, t.ref))
            if new is None:
                plan.skipped.append(f"{t.deck} slide {t.slide}: source {t.src_file}!{t.sheet}!{t.ref} is missing; not changed")
                continue
            if new != t.linked_value:
                by_deck.setdefault(t.deck, []).append((t, new))
        for deck_rel, items in by_deck.items():
            deck = open_document((self.root / deck_rel).read_bytes(), deck_rel)
            if self._config().get("tracked_changes") and hasattr(deck, "tracked"):
                deck.tracked = True
            dms = {(d.slide, d.shape_id, d.para, d.seg, d.offset): d for d in deck.mentions()}
            applied = 0
            for t, new in sorted(items, key=lambda x: (x[0].slide, x[0].shape_id, x[0].para, x[0].seg, -x[0].offset)):
                dm = dms.get((t.slide, t.shape_id, t.para, t.seg, t.offset))
                if dm is None or dm.number.raw != t.raw:
                    plan.skipped.append(f"{deck_rel} slide {t.slide}: '{t.raw}' is no longer where it was linked (edited by hand?); held")
                    continue
                new_text = format_like(dm.number, new, t.transform)
                ok, _ = consistent_with_source(_reparse(new_text), new)
                if new_text == t.raw:
                    continue
                if not ok:
                    plan.skipped.append(f"{deck_rel} slide {t.slide}: could not write {new} as '{new_text}' faithfully; held")
                    continue
                deck.edit_mention(dm, new_text)
                applied += 1
                plan.impacts.append(Impact(deck_rel, t.slide, t.raw, new_text, f"{t.src_file}!{t.sheet}!{t.ref}", t.linked_value, new))
            if applied:
                data, _report = deck.serialize()
                plan.files[deck_rel] = data
        return plan

    def commit_snapshot(self, plan: Plan, override: dict[tuple[str, str, str], float] | None = None) -> None:
        """After a successful release: new source values become the baseline, and ties in edited decks are re-anchored.

        Numbers keep their order inside each text segment, so the n-th tie of a segment maps to the n-th number of the
        edited segment. If the count differs, the ties of that segment go back to 'confirm' instead of being guessed.
        """
        current = self._current_values()
        for deck_rel, data in plan.files.items():
            # a restored deck holds the numbers it had before a release, so its links go back to those baseline values
            values = {**current, **(override or {})}
            fresh: dict[tuple, list[DocMention]] = {}
            for d in open_document(data, deck_rel).mentions():
                fresh.setdefault((d.slide, d.shape_id, d.para, d.cell), []).append(d)
            groups: dict[tuple, list[Tie]] = {}
            for t in self.ties():
                if t.deck == deck_rel:
                    groups.setdefault((t.slide, t.shape_id, t.para, t.cell_rc), []).append(t)
            for key, ts in groups.items():
                ts.sort(key=lambda t: (t.seg, t.offset))
                nms = sorted(fresh.get(key, []), key=lambda d: (d.seg, d.offset))
                if len(nms) != len(ts):
                    for t in ts:
                        self.db.execute("UPDATE ties SET state='confirm' WHERE id=?", (t.id,))
                    continue
                for t, d in zip(ts, nms):
                    new = values.get((t.src_file, t.sheet, t.ref), t.linked_value)
                    self.db.execute("UPDATE ties SET seg=?, offset=?, raw=?, linked_value=? WHERE id=?", (d.seg, d.offset, d.number.raw, new, t.id))
        for t in self.ties():
            if t.deck not in plan.files:
                new = current.get((t.src_file, t.sheet, t.ref))
                if new is not None:
                    self.db.execute("UPDATE ties SET linked_value=? WHERE id=?", (new, t.id))


def _reparse(text: str):
    from .match.numbers import parse_numbers

    return parse_numbers(text)[0]
