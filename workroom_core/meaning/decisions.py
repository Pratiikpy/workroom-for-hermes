"""What the owner decided about a finding, remembered across update cycles so the same question is never asked twice."""

from __future__ import annotations

import hashlib
import sqlite3
import time


class Decisions:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS decisions (key TEXT PRIMARY KEY, kind TEXT, decision TEXT, note TEXT, at REAL)")

    @staticmethod
    def key(*parts: object) -> str:
        return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT decision FROM decisions WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, kind: str, decision: str, note: str = "") -> None:
        self.db.execute("INSERT OR REPLACE INTO decisions (key, kind, decision, note, at) VALUES (?,?,?,?,?)", (key, kind, decision, note, time.time()))

    def forget(self, key: str) -> None:
        self.db.execute("DELETE FROM decisions WHERE key=?", (key,))

    def all(self, kind: str | None = None) -> list[tuple[str, str, str, str]]:
        q = "SELECT key, kind, decision, note FROM decisions" + (" WHERE kind=?" if kind else "") + " ORDER BY at"
        return self.db.execute(q, (kind,) if kind else ()).fetchall()
