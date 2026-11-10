"""Before-images of the files an agent is about to change, so any one of them can be put back.

Only the files a tool names are copied (a whole-folder copy per turn measured 13 s per 100 MB of small files on Windows, too slow), into a content-addressed
store in the project's state folder. A file that did not exist is recorded as "created" and restoring it moves it to a recovery folder, never deleting it.
Restoring is an owner action: the agent has no tool for it.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import time
from pathlib import Path

MAX_BYTES = 200 * 1024 * 1024


class SnapshotError(ValueError):
    pass


class SnapshotStore:
    def __init__(self, state: Path, root: Path) -> None:
        self.root = Path(root).resolve()
        self.dir = Path(state) / "snapshots"
        (self.dir / "objects").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.dir / "snapshots.db"))
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS snaps (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, tool TEXT, path TEXT, sha TEXT, size INTEGER, state TEXT, restored_at REAL)")

    def close(self) -> None:
        self.db.close()

    def _relative(self, path: Path) -> str | None:
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return None

    def take(self, path: str | Path, tool: str) -> int | None:
        """Record the state of ``path`` before a tool changes it. Returns the snapshot id, or None when the path is outside the project or is a folder."""
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        rel = self._relative(p)
        if rel is None or p.is_dir():
            return None
        if not p.exists():
            return self._row(tool, rel, None, 0, "created")
        size = p.stat().st_size
        if size > MAX_BYTES:
            return self._row(tool, rel, None, size, "too_large")
        data = p.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        obj = self.dir / "objects" / sha
        if not obj.exists():
            tmp = obj.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, obj)
        return self._row(tool, rel, sha, size, "saved")

    def _row(self, tool: str, rel: str, sha: str | None, size: int, state: str) -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO snaps (at, tool, path, sha, size, state) VALUES (?,?,?,?,?,?)", (time.time(), tool, rel, sha, size, state))
        return int(cur.lastrowid)

    def list(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute("SELECT * FROM snaps ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [{"id": r["id"], "at": r["at"], "tool": r["tool"], "path": r["path"], "state": r["state"], "size": r["size"], "restored": r["restored_at"] is not None,
                 "now": self._now(r)} for r in rows]

    def _now(self, r: sqlite3.Row) -> str:
        p = self.root / r["path"]
        if not p.exists():
            return "missing"
        if r["sha"] is None:
            return "present"
        return "unchanged" if hashlib.sha256(p.read_bytes()).hexdigest() == r["sha"] else "changed"

    def restore(self, snap_id: int) -> dict:
        """Put the file back as it was before the change. What is there now is first moved to the recovery folder, so a restore can itself be undone."""
        r = self.db.execute("SELECT * FROM snaps WHERE id=?", (int(snap_id),)).fetchone()
        if r is None:
            raise SnapshotError("unknown snapshot")
        if r["state"] == "too_large":
            raise SnapshotError("this file was too large to keep a copy of")
        target = (self.root / r["path"]).resolve()
        if self._relative(target) is None:
            raise SnapshotError("the file is outside the project")
        recovery = self.dir / "recovery" / f"{int(time.time())}-{r['id']}"
        if target.exists():
            recovery.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(recovery / target.name))
        if r["state"] == "saved":
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".workroom-restore")
            shutil.copyfile(self.dir / "objects" / r["sha"], tmp)
            os.replace(tmp, target)
        with self.db:
            self.db.execute("UPDATE snaps SET restored_at=? WHERE id=?", (time.time(), r["id"]))
        return {"path": r["path"], "restored_to": "earlier content" if r["state"] == "saved" else "not existing (the new file was moved to the recovery folder)"}

    def paths(self) -> list[str]:
        return [r["path"] for r in self.db.execute("SELECT path, MAX(id) AS last FROM snaps GROUP BY path ORDER BY last DESC")]

    def versions(self, rel: str) -> list[dict]:
        """Earlier versions of one file, oldest first: each before-image the store kept (a file that did not exist yet has none)."""
        return [{"id": r["id"], "at": r["at"], "tool": r["tool"], "sha": r["sha"], "state": r["state"], "size": r["size"]}
                for r in self.db.execute("SELECT * FROM snaps WHERE path=? ORDER BY id", (rel,))]

    def version_bytes(self, snap_id: int) -> bytes | None:
        r = self.db.execute("SELECT * FROM snaps WHERE id=?", (int(snap_id),)).fetchone()
        if r is None:
            raise SnapshotError("unknown version")
        if r["state"] != "saved":
            return None
        return (self.dir / "objects" / r["sha"]).read_bytes()
