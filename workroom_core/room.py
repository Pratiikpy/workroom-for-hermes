"""The Room: what one project knows, kept in one place that every capability reads.

Sources (files, folders, links, notes), memory with provenance (a fact, preference or correction, each with where it came from), and an append-only audit
log. The agent may add sources and propose memory; only the owner approves, edits or rejects memory, so nothing the agent "remembers" is acted on unless a
person said yes. Stored in the project's state folder, never inside the user's folder.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

SOURCE_KINDS = ("file", "folder", "url", "note")
MEMORY_KINDS = ("fact", "preference", "correction")
ACTORS = ("owner", "agent")
MAX_NOTE = 2000
MAX_LABEL = 120
MAX_MEMORY = 1000
MAX_SOURCE_OF_MEMORY = 300
MAX_REF = 1000


class RoomError(ValueError):
    pass


class Room:
    def __init__(self, state: Path, root: Path) -> None:
        self.root = Path(root).resolve()
        Path(state).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(state) / "room.db"))
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref TEXT, label TEXT, added_by TEXT, added_at REAL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, text TEXT, source TEXT, state TEXT, proposed_by TEXT,"
                            " proposed_at REAL, decided_by TEXT, decided_at REAL, history TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS policy (key TEXT PRIMARY KEY, value TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS deliverables (path TEXT PRIMARY KEY, registered_by TEXT, note TEXT, at REAL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS approvals (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, sha TEXT, at REAL, by TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, actor TEXT, event TEXT, detail TEXT)")

    def close(self) -> None:
        self.db.close()

    # ---- audit
    def _log(self, actor: str, event: str, detail: dict) -> None:
        self.db.execute("INSERT INTO audit (at, actor, event, detail) VALUES (?,?,?,?)", (time.time(), actor, event, json.dumps(detail, ensure_ascii=False)))

    def audit(self, limit: int = 200) -> list[dict]:
        rows = self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r["id"], "at": r["at"], "actor": r["actor"], "event": r["event"], "detail": json.loads(r["detail"])} for r in reversed(rows)]

    @staticmethod
    def _actor(by: str) -> str:
        if by not in ACTORS:
            raise RoomError("the actor must be owner or agent")
        return by

    # ---- sources
    def _check_ref(self, kind: str, ref: str) -> str:
        if not isinstance(ref, str) or not ref.strip():
            raise RoomError("a source needs a reference")
        ref = ref.strip()
        if kind in ("file", "folder"):
            if len(ref) > MAX_REF:
                raise RoomError("the path is too long")
            target = (self.root / ref).resolve() if not Path(ref).is_absolute() else Path(ref).resolve()
            try:
                relative = target.relative_to(self.root)
            except ValueError:
                raise RoomError("a file or folder source must be inside the project folder") from None
            return relative.as_posix() or "."
        if kind == "url":
            parts = urlparse(ref)
            if parts.scheme not in ("http", "https") or not parts.netloc or len(ref) > MAX_REF:
                raise RoomError("a link source must be an http or https address")
            return ref
        if len(ref) > MAX_NOTE:
            raise RoomError(f"a note source is limited to {MAX_NOTE} characters")
        return ref

    def add_source(self, kind: str, ref: str, label: str, by: str) -> int:
        actor = self._actor(by)
        if kind not in SOURCE_KINDS:
            raise RoomError("a source is a file, folder, url or note")
        ref = self._check_ref(kind, ref)
        label = (label or "").strip()[:MAX_LABEL] or ref[:MAX_LABEL]
        with self.db:
            cur = self.db.execute("INSERT INTO sources (kind, ref, label, added_by, added_at) VALUES (?,?,?,?,?)", (kind, ref, label, actor, time.time()))
            self._log(actor, "source_added", {"id": cur.lastrowid, "kind": kind, "ref": ref[:200], "label": label})
        return int(cur.lastrowid)

    def remove_source(self, source_id: int, by: str) -> None:
        actor = self._actor(by)
        with self.db:
            row = self.db.execute("SELECT * FROM sources WHERE id=?", (int(source_id),)).fetchone()
            if row is None:
                raise RoomError("unknown source")
            self.db.execute("DELETE FROM sources WHERE id=?", (int(source_id),))
            self._log(actor, "source_removed", {"id": row["id"], "kind": row["kind"], "label": row["label"]})

    def sources(self) -> list[dict]:
        out = []
        for r in self.db.execute("SELECT * FROM sources ORDER BY id"):
            present = None
            if r["kind"] in ("file", "folder"):
                present = (self.root / r["ref"]).exists()
            out.append({"id": r["id"], "kind": r["kind"], "ref": r["ref"], "label": r["label"], "added_by": r["added_by"], "added_at": r["added_at"], "present": present})
        return out

    # ---- memory
    def propose_memory(self, text: str, kind: str, source: str, by: str) -> int:
        actor = self._actor(by)
        if kind not in MEMORY_KINDS:
            raise RoomError("a memory is a fact, preference or correction")
        text = (text or "").strip()
        source = (source or "").strip()
        if not text or len(text) > MAX_MEMORY:
            raise RoomError(f"a memory is 1 to {MAX_MEMORY} characters")
        if not source or len(source) > MAX_SOURCE_OF_MEMORY:
            raise RoomError("a memory needs its source (where it came from), up to 300 characters")
        with self.db:
            cur = self.db.execute("INSERT INTO memory (kind, text, source, state, proposed_by, proposed_at, history) VALUES (?,?,?,?,?,?,?)",
                                  (kind, text, source, "proposed", actor, time.time(), "[]"))
            self._log(actor, "memory_proposed", {"id": cur.lastrowid, "kind": kind})
        return int(cur.lastrowid)

    def _memory_row(self, memory_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM memory WHERE id=?", (int(memory_id),)).fetchone()
        if row is None:
            raise RoomError("unknown memory")
        return row

    def decide_memory(self, memory_id: int, approve: bool, by: str) -> None:
        if self._actor(by) != "owner":
            raise RoomError("only the owner decides what is remembered")
        row = self._memory_row(memory_id)
        if row["state"] != "proposed":
            raise RoomError("this memory was already decided")
        state = "approved" if approve else "rejected"
        with self.db:
            self.db.execute("UPDATE memory SET state=?, decided_by=?, decided_at=? WHERE id=?", (state, by, time.time(), row["id"]))
            self._log(by, f"memory_{state}", {"id": row["id"]})

    def edit_memory(self, memory_id: int, text: str, by: str) -> None:
        if self._actor(by) != "owner":
            raise RoomError("only the owner edits what is remembered")
        row = self._memory_row(memory_id)
        text = (text or "").strip()
        if not text or len(text) > MAX_MEMORY:
            raise RoomError(f"a memory is 1 to {MAX_MEMORY} characters")
        history = json.loads(row["history"]) + [row["text"]]
        with self.db:
            self.db.execute("UPDATE memory SET text=?, history=? WHERE id=?", (text, json.dumps(history, ensure_ascii=False), row["id"]))
            self._log(by, "memory_edited", {"id": row["id"]})

    def memory(self, state: str = "approved") -> list[dict]:
        if state not in ("approved", "proposed", "rejected"):
            raise RoomError("state must be approved, proposed or rejected")
        return [{"id": r["id"], "kind": r["kind"], "text": r["text"], "source": r["source"], "state": r["state"], "proposed_by": r["proposed_by"],
                 "proposed_at": r["proposed_at"], "decided_by": r["decided_by"], "decided_at": r["decided_at"], "history": json.loads(r["history"])}
                for r in self.db.execute("SELECT * FROM memory WHERE state=? ORDER BY id", (state,))]

    # ---- policy: files the agent may not change, and whether removing many files needs a human yes
    DEFAULT_PROTECTED = (".git/*", ".env", "*.pem", "*.key", "workroom.md")

    def policy(self) -> dict:
        row = self.db.execute("SELECT value FROM policy WHERE key='policy'").fetchone()
        if row is None:
            return {"protected": list(self.DEFAULT_PROTECTED), "confirm_delete": True}
        return json.loads(row["value"])

    def set_policy(self, protected: list[str], confirm_delete: bool, by: str) -> dict:
        if self._actor(by) != "owner":
            raise RoomError("only the owner changes the policy")
        clean = []
        for pat in protected:
            pat = str(pat).strip().replace(chr(92), "/")
            if not pat or len(pat) > 200 or pat.startswith("/") or ".." in pat.split("/"):
                raise RoomError("a protected pattern is a path inside the project, such as reports/final/* or *.pem")
            clean.append(pat)
        value = {"protected": clean[:100], "confirm_delete": bool(confirm_delete)}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO policy (key, value) VALUES ('policy', ?)", (json.dumps(value),))
            self._log(by, "policy_changed", {"protected": len(value["protected"]), "confirm_delete": value["confirm_delete"]})
        return value

    # ---- deliverables: files registered as work product, and the owner's approval of an exact version
    def register_deliverable(self, path: str, note: str, by: str) -> str:
        actor = self._actor(by)
        rel = self._check_ref("file", path)
        note = (note or "").strip()[:MAX_LABEL]
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO deliverables (path, registered_by, note, at) VALUES (?,?,?,?)", (rel, actor, note, time.time()))
            self._log(actor, "deliverable_registered", {"path": rel})
        return rel

    def registered(self) -> dict[str, dict]:
        return {r["path"]: {"registered_by": r["registered_by"], "note": r["note"], "at": r["at"]} for r in self.db.execute("SELECT * FROM deliverables")}

    def approve_version(self, path: str, sha: str, by: str) -> None:
        if self._actor(by) != "owner":
            raise RoomError("only the owner approves a deliverable")
        rel = self._check_ref("file", path)
        with self.db:
            self.db.execute("INSERT INTO approvals (path, sha, at, by) VALUES (?,?,?,?)", (rel, sha, time.time(), by))
            self._log(by, "deliverable_approved", {"path": rel, "sha": sha[:16]})

    def approvals(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.db.execute("SELECT * FROM approvals ORDER BY id"):
            out[r["path"]] = {"sha": r["sha"], "at": r["at"], "by": r["by"]}
        return out
