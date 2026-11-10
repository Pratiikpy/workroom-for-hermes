"""A safety net under the shell guard: if a shell or code tool changes a managed Office file anyway, put the file back and keep the agent's version aside.

The guard in guard.py reads the command and sends a suspicious one to the human approval gate. That is a heuristic, and when approvals answer themselves
(auto-approve / YOLO modes) the gate is no protection at all: a real model told to skip Workroom wrote a Python script that saved the deck directly, and it worked.
This net does not read commands. Before a shell tool runs it remembers every Office file of every registered project; after the tool, any file that is
different, new or gone is put back exactly as it was, and what the agent made is kept in the project's ``rejected`` folder in Workroom's own storage (never in
the project folder, never deleted) so nothing the agent did is lost and the owner can look at it. The agent is told in the tool result. A release the owner
published while the tool ran is not touched. What it cannot do: see a change made by something other than a tool call, undo a change to files larger than
the size cap (it reports them instead), or notice a file outside every registered project.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .guard import OFFICE, SHELL_TOOLS

MAX_FILE = 50 * 1024 * 1024
MAX_TOTAL = 300 * 1024 * 1024
MAX_FILES = 400
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

MESSAGE = ("Workroom put {names} back as it was: managed Office files are not edited directly, because a direct edit would skip the verified release. "
           "What you wrote is kept for the owner to look at. To change figures, use workroom_plan and workroom_stage_release; the owner approves the release.")


def _scan(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.lower().endswith(OFFICE) and not name.startswith("~$"):
                p = Path(dirpath) / name
                found[p.relative_to(root).as_posix()] = p
                if len(found) >= MAX_FILES:
                    return found
    return found


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_tripwire(projects: Callable[[], list[dict[str, Any]]], quarantine: Callable[[str, str, bytes], None],
                  published_since: Callable[[str, float], bool], note: Callable[[str, str, str], None]):
    """Returns (before, after): a pre_tool_call observer and a transform_tool_result hook. ``quarantine(pid, relpath, bytes)`` keeps the agent's version,
    ``published_since(pid, ts)`` says whether the owner published a release since ``ts``, ``note(pid, relpath, outcome)`` records what happened."""
    lock = threading.Lock()
    pending: dict[str, dict[str, Any]] = {}

    def key_of(kwargs: dict[str, Any]) -> str:
        return f"{kwargs.get('session_id', '')}|{kwargs.get('tool_call_id', '')}|{kwargs.get('task_id', '')}"

    def before(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any) -> None:
        try:
            if tool_name not in SHELL_TOOLS:
                return None
            import time

            state: dict[str, Any] = {"at": time.time(), "projects": {}}
            total = 0
            for p in projects():
                root = Path(p["folder"]).resolve()
                if not root.is_dir():
                    continue
                files: dict[str, tuple[str, bytes | None]] = {}
                for rel, path in _scan(root).items():
                    try:
                        size = path.stat().st_size
                        data = path.read_bytes() if size <= MAX_FILE else None
                    except OSError:
                        continue
                    if data is None:
                        files[rel] = ("too-large:%d:%d" % (size, path.stat().st_mtime_ns), None)
                        continue
                    keep = data if total + len(data) <= MAX_TOTAL else None
                    total += len(data) if keep is not None else 0
                    files[rel] = (_digest(data), keep)
                state["projects"][p["project"]] = (root, files)
            with lock:
                while len(pending) >= 50:  # a call a guard blocked never reaches the after-hook; do not let those pile up
                    pending.pop(next(iter(pending)))
                pending[key_of(kwargs)] = state
        except Exception:  # noqa: BLE001  an observer never disturbs the call it watches
            return None
        return None

    def after(tool_name: str = "", args: dict[str, Any] | None = None, result: Any = None, **kwargs: Any):
        try:
            if tool_name not in SHELL_TOOLS or not isinstance(result, str):
                return None
            with lock:
                state = pending.pop(key_of(kwargs), None)
            if not state:
                return None
            reverted: list[str] = []
            unrestored: list[str] = []
            for pid, (root, files) in state["projects"].items():
                if published_since(pid, state["at"]):
                    continue  # the owner published while the tool ran: those changes are theirs
                now = _scan(root)
                for rel in sorted(set(files) | set(now)):
                    old = files.get(rel)
                    path = root / rel
                    cur = None
                    if rel in now:
                        try:
                            size = path.stat().st_size
                            cur = path.read_bytes() if size <= MAX_FILE else None
                        except OSError:
                            cur = None
                    if old is None:  # a new Office file appeared
                        if cur is not None:
                            quarantine(pid, rel, cur)
                            try:
                                path.unlink()
                                reverted.append(rel)
                                note(pid, rel, "removed a new file")
                            except OSError:
                                unrestored.append(rel)
                        continue
                    if cur is not None and _digest(cur) == old[0]:
                        continue
                    if old[0].startswith("too-large") and rel in now:
                        try:
                            if "too-large:%d:%d" % (path.stat().st_size, path.stat().st_mtime_ns) == old[0]:
                                continue
                        except OSError:
                            pass
                    if old[1] is None:
                        unrestored.append(rel)
                        note(pid, rel, "changed and could not be restored")
                        if cur is not None:
                            quarantine(pid, rel, cur)
                        continue
                    if cur is not None:
                        quarantine(pid, rel, cur)
                    tmp = path.with_name(path.name + ".workroom-restore")
                    try:
                        tmp.write_bytes(old[1])
                        os.replace(tmp, path)
                        reverted.append(rel)
                        note(pid, rel, "restored")
                    except OSError:
                        unrestored.append(rel)
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
            if not reverted and not unrestored:
                return None
            text = MESSAGE.format(names=", ".join(reverted) or "the file") if reverted else ""
            if unrestored:
                text += (" " if text else "") + "Could not put back " + ", ".join(unrestored) + " (too large to keep a copy, or in use); the owner can Restore it from the changes list."
            return result + "\n\n[Workroom] " + text
        except Exception:  # noqa: BLE001
            return None

    return before, after
