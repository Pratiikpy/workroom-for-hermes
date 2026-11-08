"""Portable, tamper-evident project manifest: a hash-chained, HMAC-signed log kept inside the project folder.

It is a recovery aid and a witness, not an authority. A modified, reordered, truncated or foreign manifest fails
verification. A consistent rollback of every copy of the state to an older valid point is NOT detected (a MAC proves
authenticity, not freshness); the release counter mirrored elsewhere (journal, anchor file, receipts) catches partial
rollbacks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_NAME = "workroom.manifest.json"
GENESIS = "0" * 64


class ManifestError(Exception):
    """The manifest cannot be trusted; the project must be re-approved in recovery mode."""


def _mac(key: bytes, seq: int, kind: str, data: dict[str, Any], prev: str) -> str:
    body = json.dumps({"seq": seq, "kind": kind, "data": data, "prev": prev}, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Entry:
    seq: int
    kind: str
    data: dict[str, Any]
    prev: str
    mac: str


class Manifest:
    def __init__(self, path: Path, key: bytes, project_id: str) -> None:
        self.path = Path(path)
        self.key = key
        self.project_id = project_id
        self.entries: list[Entry] = []
        if self.path.exists():
            self._load()

    # ---- load and verify ----
    def _load(self) -> None:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            raw = doc["entries"]
            project = doc["project"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ManifestError(f"manifest unreadable: {exc}") from exc
        if project != self.project_id:
            raise ManifestError("manifest belongs to a different project")
        prev = GENESIS
        entries: list[Entry] = []
        for i, e in enumerate(raw):
            try:
                ent = Entry(int(e["seq"]), str(e["kind"]), dict(e["data"]), str(e["prev"]), str(e["mac"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ManifestError(f"entry {i} is malformed") from exc
            if ent.seq != i + 1:
                raise ManifestError(f"entry {i} is out of order or missing")
            if ent.prev != prev:
                raise ManifestError(f"entry {ent.seq} does not follow the previous one")
            if not hmac.compare_digest(ent.mac, _mac(self.key, ent.seq, ent.kind, ent.data, ent.prev)):
                raise ManifestError(f"entry {ent.seq} was altered or signed with another key")
            prev = ent.mac
            entries.append(ent)
        head = doc.get("head")
        if entries and head != entries[-1].mac:
            raise ManifestError("the manifest head does not match its last entry (entries were removed)")
        if not entries and head not in (None, GENESIS):
            raise ManifestError("the manifest head does not match an empty log")
        self.entries = entries

    # ---- append ----
    def append(self, kind: str, data: dict[str, Any]) -> Entry:
        prev = self.entries[-1].mac if self.entries else GENESIS
        seq = len(self.entries) + 1
        ent = Entry(seq, kind, data, prev, _mac(self.key, seq, kind, data, prev))
        self.entries.append(ent)
        self._write()
        return ent

    def _write(self) -> None:
        doc = {
            "version": 1,
            "project": self.project_id,
            "counter": self.counter(),
            "head": self.entries[-1].mac if self.entries else GENESIS,
            "entries": [{"seq": e.seq, "kind": e.kind, "data": e.data, "prev": e.prev, "mac": e.mac} for e in self.entries],
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ---- queries ----
    def counter(self) -> int:
        """Number of releases published: the value mirrored in the journal and the anchor file."""
        base, after = 0, 0
        for e in self.entries:
            if e.kind == "recovered":
                base, after = int(e.data["counter"]), 0
            elif e.kind == "published":
                after += 1
        return base + after

    @classmethod
    def start_over(cls, path: Path, key: bytes, project_id: str) -> tuple["Manifest", Path | None]:
        """Move an unreadable or altered manifest aside (kept for the owner) and return an empty one at the same path."""
        path = Path(path)
        aside = None
        if path.exists():
            aside = path.with_name(f"{path.name}.damaged-{int(time.time())}")
            os.replace(path, aside)
        return cls(path, key, project_id), aside

    def published(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "published"]


class Anchor:
    """A MAC-protected copy of the release counter kept OUTSIDE the project folder (in the plugin data directory)."""

    def __init__(self, path: Path, key: bytes, project_id: str) -> None:
        self.path, self.key, self.project_id = Path(path), key, project_id

    def _mac(self, counter: int) -> str:
        return hmac.new(self.key, f"{self.project_id}|{counter}".encode(), hashlib.sha256).hexdigest()

    def write(self, counter: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"counter": counter, "mac": self._mac(counter)}), encoding="utf-8")

    def read(self) -> int:
        if not self.path.exists():
            return 0
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            counter = int(d["counter"])
            if not hmac.compare_digest(str(d["mac"]), self._mac(counter)):
                raise ManifestError("the release counter anchor was altered")
            return counter
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ManifestError(f"the release counter anchor is unreadable: {exc}") from exc
