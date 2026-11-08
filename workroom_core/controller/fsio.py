"""Durable file operations: temp write, fsync, replace, directory sync, with bounded retry on Windows."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path


class FileInUse(OSError):
    """The destination is locked by another process; the release must not proceed."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":
        return  # directories cannot be opened for fsync on Windows; the weaker guarantee is documented
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_durable(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` (a new file) and flush it to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    _fsync_dir(path.parent)


def replace_durable(src: Path, dest: Path, retries: int = 5, delay: float = 0.2) -> None:
    """Atomically replace ``dest`` with ``src`` (same volume), retrying briefly if the file is locked."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            os.replace(src, dest)
            _fsync_dir(dest.parent)
            return
        except PermissionError as exc:  # Windows sharing violation
            last = exc
            time.sleep(delay * (attempt + 1))
    raise FileInUse(f"{dest} is in use: {last}")
