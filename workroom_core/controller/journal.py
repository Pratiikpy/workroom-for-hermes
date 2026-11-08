"""Append-only release journal in its own SQLite database, committed with synchronous=FULL."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JournalRow:
    seq: int
    release_id: str
    step: str
    detail: dict[str, Any]


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY AUTOINCREMENT, release_id TEXT NOT NULL,"
            " step TEXT NOT NULL, detail TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._db.execute(
            "CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END"
        )
        self._db.execute(
            "CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END"
        )

    def append(self, release_id: str, step: str, **detail: Any) -> int:
        cur = self._db.execute(
            "INSERT INTO journal (release_id, step, detail, ts) VALUES (?,?,?,?)",
            (release_id, step, json.dumps(detail, sort_keys=True), time.time()),
        )
        return int(cur.lastrowid)

    def rows(self, release_id: str | None = None) -> list[JournalRow]:
        q = "SELECT seq, release_id, step, detail FROM journal"
        args: tuple = ()
        if release_id is not None:
            q += " WHERE release_id=?"
            args = (release_id,)
        q += " ORDER BY seq"
        return [JournalRow(r[0], r[1], r[2], json.loads(r[3])) for r in self._db.execute(q, args)]

    def release_ids(self) -> list[str]:
        return [r[0] for r in self._db.execute("SELECT release_id FROM journal GROUP BY release_id ORDER BY MIN(seq)")]

    def last_step(self, release_id: str) -> str | None:
        r = self._db.execute("SELECT step FROM journal WHERE release_id=? ORDER BY seq DESC LIMIT 1", (release_id,)).fetchone()
        return r[0] if r else None

    def when(self, release_id: str, step: str) -> float | None:
        r = self._db.execute("SELECT ts FROM journal WHERE release_id=? AND step=? ORDER BY seq DESC LIMIT 1", (release_id, step)).fetchone()
        return float(r[0]) if r else None

    def close(self) -> None:
        self._db.close()
