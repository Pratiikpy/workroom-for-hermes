"""One writer at a time per project: approving, publishing and restoring take this lock, in this process and across processes.

Two approvals of one release arriving together (a Desktop click and a Telegram button, say) must publish it once. The lock is an operating-system
file lock, so it is released by the system if the holder dies.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from typing import Iterator


class LockTimeout(OSError):
    pass


@contextlib.contextmanager
def project_lock(path: Path, timeout: float = 120.0) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeout("another approval or restore of this project is in progress") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
