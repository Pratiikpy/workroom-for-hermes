"""Release controller: stage, verify, approve, publish with a journal, recover, restore.

Recovery decisions are made from the files' actual hashes, never from the journal alone, so a crash at any
point (including between a file replace and its journal line) is handled the same way.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Callable

from .approvals import Approval, ApprovalError, verify
from .fsio import FileInUse, replace_durable, sha256_bytes, sha256_file, write_durable
from .journal import Journal

Failpoint = Callable[[str], None]


class ReleaseError(Exception):
    pass


class StaleRelease(ReleaseError):
    """A live file no longer matches the version the release was prepared against."""


class NotReady(ReleaseError):
    pass


@dataclass(frozen=True)
class Change:
    rel_path: str
    base_sha: str | None  # None when the file is new (create and folder modes)
    new_sha: str


def _safe_rel(rel: str) -> str:
    p = PurePosixPath(rel)
    if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel or (len(rel) > 1 and rel[1] == ":"):
        raise ReleaseError(f"unsafe path {rel!r}")
    return str(p)


def release_digest(changes: list[Change], mode: str, counter: int) -> str:
    body = json.dumps(
        {"mode": mode, "counter": counter, "files": sorted([c.rel_path, c.base_sha, c.new_sha] for c in changes)},
        sort_keys=True, separators=(",", ":"),
    )
    return sha256_bytes(body.encode("utf-8"))


class Controller:
    def __init__(self, project: Path, state: Path, key: bytes, allowed_principals: frozenset[str],
                 failpoint: Failpoint | None = None) -> None:
        self.project = Path(project).resolve()
        self.state = Path(state).resolve()
        self.key = key
        self.allowed = allowed_principals
        self.fp: Failpoint = failpoint or (lambda name: None)
        self.journal = Journal(self.state / "journal.db")

    # ---- helpers ----
    def _staging(self, rid: str) -> Path:
        return self.state / "staging" / rid

    def _backups(self, rid: str) -> Path:
        return self.state / "backups" / rid

    def _live(self, rel: str) -> Path:
        p = (self.project / rel).resolve()
        if self.project not in p.parents and p != self.project:
            raise ReleaseError(f"path escapes the project: {rel!r}")
        return p

    def _meta(self, rid: str) -> dict:
        for row in self.journal.rows(rid):
            if row.step == "STAGED":
                return row.detail
        raise ReleaseError(f"unknown release {rid}")

    def _changes(self, rid: str) -> list[Change]:
        return [Change(c["rel_path"], c["base_sha"], c["new_sha"]) for c in self._meta(rid)["changes"]]

    def _next_counter(self) -> int:
        last = 0
        for row in self.journal.rows():
            if row.step == "STAGED":
                last = max(last, row.detail["counter"])
        return last + 1

    # ---- stage ----
    def stage(self, new_files: dict[str, bytes], mode: str = "inplace") -> str:
        if mode not in ("inplace", "folder", "create"):
            raise ReleaseError("mode must be inplace, folder or create")
        if not new_files:
            raise ReleaseError("nothing to release")
        rid = uuid.uuid4().hex[:16]
        changes: list[Change] = []
        for rel, data in sorted(new_files.items()):
            rel = _safe_rel(rel)
            live = self._live(rel)
            if mode == "create":
                if live.exists():
                    raise ReleaseError(f"{rel} already exists; a create release never overwrites")
                base = None
            elif mode == "inplace":
                if not live.is_file():
                    raise ReleaseError(f"{rel} does not exist; in-place releases only replace existing files")
                base = sha256_file(live)
            else:
                base = sha256_file(live) if live.is_file() else None
            changes.append(Change(rel, base, sha256_bytes(data)))
            write_durable(self._staging(rid) / rel, data)
        self.fp("after_stage_write")
        counter = self._next_counter()
        digest = release_digest(changes, mode, counter)
        self.journal.append(rid, "STAGED", mode=mode, counter=counter, digest=digest,
                            changes=[{"rel_path": c.rel_path, "base_sha": c.base_sha, "new_sha": c.new_sha} for c in changes])
        return rid

    def digest(self, rid: str) -> str:
        return self._meta(rid)["digest"]

    # ---- verify ----
    def mark_verified(self, rid: str, findings: list[str] | None = None) -> None:
        if findings:
            self.journal.append(rid, "BLOCKED", findings=findings)
            raise NotReady("blocked: " + "; ".join(findings))
        self.journal.append(rid, "VERIFIED")

    # ---- approve ----
    def record_approval(self, rid: str, approval: Approval, now: float | None = None) -> None:
        now = time.time() if now is None else now
        steps = [r.step for r in self.journal.rows(rid)]
        if "VERIFIED" not in steps:
            raise NotReady("release is not verified")
        if "PUBLISHING" in steps or "PUBLISHED" in steps:
            raise ApprovalError("release already published")
        verify(self.key, approval, rid, self.digest(rid), now, self.allowed)
        for row in self.journal.rows():
            if row.step == "APPROVED" and row.detail.get("nonce") == approval.nonce:
                raise ApprovalError("approval was already used")
        self.journal.append(rid, "APPROVED", nonce=approval.nonce, principal=approval.principal,
                            channel=approval.channel, expires_at=approval.expires_at)

    # ---- publish ----
    def publish(self, rid: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        rows = self.journal.rows(rid)
        steps = [r.step for r in rows]
        meta = self._meta(rid)
        if "APPROVED" not in steps:
            raise NotReady("release is not approved")
        if "PUBLISHED" in steps:
            raise ReleaseError("release already published")
        approved = [r for r in rows if r.step == "APPROVED"][-1]
        if now > approved.detail["expires_at"]:
            self.journal.append(rid, "EXPIRED")
            raise ApprovalError("approval expired before publishing")
        changes = self._changes(rid)
        if meta["mode"] == "create":
            for c in changes:
                if self._live(c.rel_path).exists():
                    self.journal.append(rid, "REFUSED_STALE", file=c.rel_path)
                    raise StaleRelease(f"{c.rel_path} appeared since this release was prepared; it will not be overwritten")
        if meta["mode"] == "inplace":
            for c in changes:
                live = self._live(c.rel_path)
                if not live.is_file() or sha256_file(live) != c.base_sha:
                    self.journal.append(rid, "REFUSED_STALE", file=c.rel_path)
                    raise StaleRelease(f"{c.rel_path} changed since this release was prepared")
        for c in changes:
            staged = self._staging(rid) / c.rel_path
            if not staged.is_file() or sha256_file(staged) != c.new_sha:
                self.journal.append(rid, "BLOCKED", findings=[f"staged copy of {c.rel_path} is missing or altered"])
                raise NotReady(f"staged copy of {c.rel_path} is missing or altered")
        self.journal.append(rid, "PUBLISHING")
        self._apply(rid, meta["mode"], changes)
        self.fp("before_published")
        self.journal.append(rid, "PUBLISHED")

    def _apply(self, rid: str, mode: str, changes: list[Change]) -> None:
        if mode == "folder":
            counter = self._meta(rid)["counter"]
            dest = self.state / "releases" / str(counter)
            for c in changes:
                target = dest / c.rel_path
                if not target.is_file() or sha256_file(target) != c.new_sha:
                    write_durable(target, (self._staging(rid) / c.rel_path).read_bytes())
            self.fp("before_pointer")
            pointer_tmp = self.state / "releases" / ".current.tmp"
            write_durable(pointer_tmp, json.dumps({"release": counter, "id": rid}).encode())
            replace_durable(pointer_tmp, self.state / "releases" / "current.json")
            return
        for i, c in enumerate(changes):
            self._apply_file(rid, i, c)

    def _apply_file(self, rid: str, i: int, c: Change) -> None:
        live = self._live(c.rel_path)
        backup = self._backups(rid) / c.rel_path
        self.journal.append(rid, "FILE_BEGIN", file=c.rel_path)
        if live.is_file() and sha256_file(live) == c.new_sha:
            self.journal.append(rid, "FILE_DONE", file=c.rel_path)
            return
        self.fp(f"before_backup:{i}")
        if c.base_sha is None:  # a new file: there is nothing to back up, and nothing may be there
            if live.exists():
                raise StaleRelease(f"{c.rel_path} appeared while publishing; it will not be overwritten")
            tmp = live.with_name(live.name + f".wr-{rid}.tmp")
            write_durable(tmp, (self._staging(rid) / c.rel_path).read_bytes())
            self.fp(f"before_replace:{i}")
            replace_durable(tmp, live)
            self.fp(f"after_replace:{i}")
            self.journal.append(rid, "FILE_DONE", file=c.rel_path)
            return
        if not (backup.is_file() and sha256_file(backup) == c.base_sha):
            write_durable(backup, live.read_bytes())
        if sha256_file(backup) != c.base_sha or sha256_file(live) != c.base_sha:
            raise StaleRelease(f"{c.rel_path} changed while publishing")
        self.fp(f"after_backup:{i}")
        tmp = live.with_name(live.name + f".wr-{rid}.tmp")
        write_durable(tmp, (self._staging(rid) / c.rel_path).read_bytes())
        self.fp(f"after_tmp_write:{i}")
        self.fp(f"before_replace:{i}")
        try:
            replace_durable(tmp, live)
        except FileInUse:
            if tmp.exists():
                tmp.unlink()
            raise
        self.fp(f"after_replace:{i}")
        self.journal.append(rid, "FILE_DONE", file=c.rel_path)

    # ---- recover ----
    def recover(self) -> dict[str, str]:
        """Settle every release that was interrupted. Returns release id -> outcome."""
        outcomes: dict[str, str] = {}
        for rid in self.journal.release_ids():
            steps = [r.step for r in self.journal.rows(rid)]
            if "PUBLISHING" not in steps or "PUBLISHED" in steps or "ROLLED_BACK" in steps or "RECOVERY_REQUIRED" in steps:
                continue
            meta = self._meta(rid)
            changes = self._changes(rid)
            if meta["mode"] == "folder":
                self._apply(rid, "folder", changes)
                self.journal.append(rid, "PUBLISHED", recovered=True)
                outcomes[rid] = "published"
                continue
            state = {}
            for c in changes:
                live = self._live(c.rel_path)
                h = sha256_file(live) if live.is_file() else None
                state[c.rel_path] = "new" if h == c.new_sha else ("old" if h == c.base_sha else "other")
            for tmp in self.project.rglob(f"*.wr-{rid}.tmp"):
                tmp.unlink()
            if "other" in state.values():
                self.journal.append(rid, "RECOVERY_REQUIRED", state=state)
                outcomes[rid] = "recovery_required"
                continue
            staged_ok = all((self._staging(rid) / c.rel_path).is_file() and sha256_file(self._staging(rid) / c.rel_path) == c.new_sha for c in changes)
            if staged_ok:
                for i, c in enumerate(changes):
                    if state[c.rel_path] == "old":
                        self._apply_file(rid, i, c)
                self.journal.append(rid, "PUBLISHED", recovered=True)
                outcomes[rid] = "published"
            else:
                self._rollback(rid, changes, state)
                outcomes[rid] = "rolled_back"
        return outcomes

    def _rollback(self, rid: str, changes: list[Change], state: dict[str, str]) -> None:
        self.journal.append(rid, "ROLLING_BACK")
        for c in changes:
            if state.get(c.rel_path) == "new" and c.base_sha is None:
                live = self._live(c.rel_path)
                if live.is_file() and sha256_file(live) == c.new_sha:
                    live.unlink()
                    self._prune_empty(live.parent)
            elif state.get(c.rel_path) == "new":
                backup = self._backups(rid) / c.rel_path
                if not (backup.is_file() and sha256_file(backup) == c.base_sha):
                    self.journal.append(rid, "RECOVERY_REQUIRED", reason=f"backup of {c.rel_path} missing")
                    raise ReleaseError(f"backup of {c.rel_path} missing")
                live = self._live(c.rel_path)
                tmp = live.with_name(live.name + f".wr-{rid}.rb")
                write_durable(tmp, backup.read_bytes())
                replace_durable(tmp, live)
        self.journal.append(rid, "ROLLED_BACK")

    def _prune_empty(self, folder: Path) -> None:
        """Remove folders a create release made, never the project root and never a folder that still holds anything."""
        while folder != self.project and self.project in folder.parents:
            try:
                folder.rmdir()
            except OSError:
                return
            folder = folder.parent

    # ---- restore a past release ----
    def restore(self, rid: str) -> None:
        steps = [r.step for r in self.journal.rows(rid)]
        if "PUBLISHED" not in steps:
            raise ReleaseError("only a published release can be restored")
        changes = self._changes(rid)
        state = {}
        for c in changes:
            h = sha256_file(self._live(c.rel_path))
            if h != c.new_sha:
                raise StaleRelease(f"{c.rel_path} has changed since this release; restore refused")
            state[c.rel_path] = "new"
        self._rollback(rid, changes, state)
