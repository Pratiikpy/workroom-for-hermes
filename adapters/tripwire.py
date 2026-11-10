"""A safety net under the shell guard: whatever a shell or code tool does to a managed or protected file is undone, and everything else it changes can be restored.

The guards in guard.py and workspace_guard.py read the command and send a suspicious one to the human approval prompt. That is a heuristic, and when approvals
answer themselves (auto-approve / YOLO modes) the prompt is no protection at all: a real model told to skip Workroom saved a deck from a Python script, and another,
asked to tidy a folder, moved and renamed the project's protected files. This net does not read commands. Before a shell tool runs it remembers the files of every
registered project; after the tool:

* a managed Office file or a file the project's policy protects that is different, new or gone is put back exactly as it was, and what the agent made (including a
  moved or copied version of a protected file) is kept in Workroom's own storage, never in the project folder, never deleted;
* any other file the tool changed or removed gets a before-image in the changes list, so the owner can Restore it, whatever the command looked like.

A release the owner published while the tool ran is not touched. What it cannot do: see a change made by something other than a tool call, keep a copy of a file over
the size or count caps (it reports those instead), or notice files outside every registered project.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .guard import OFFICE, SHELL_TOOLS

MAX_FILE = 50 * 1024 * 1024  # larger files are not read at all
KEEP_FILE = 2 * 1024 * 1024  # an ordinary file bigger than this is watched but its bytes are not kept
MAX_TOTAL = 200 * 1024 * 1024
MAX_FILES = 3000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
# Tools that only read, or that are Workroom's own, are not watched. Everything else is: a shell, a code tool, or an editing tool that ANOTHER plugin brought
# (a real model, stopped in the shell, used a second plugin's pptx_edit_shape tool to edit the deck directly).
_READING = ("read_", "search_", "web_", "browser_", "vision", "tool_", "session_", "skill", "todo", "clarify", "memory", "get_", "list_", "office_inspect", "pptx_inspect",
            "pptx_diff", "docx_inspect", "xlsx_inspect", "cron", "image_", "tts", "delegate")


def watched(tool_name: str) -> bool:
    return tool_name not in ("", None) and not tool_name.startswith("workroom_") and not tool_name.startswith(_READING)

MESSAGE = ("Workroom put {names} back as it was: managed Office files and the files this project protects are not changed directly, because that would skip the "
           "verified release or the owner's rules. What you wrote is kept for the owner to look at. To change figures, use workroom_plan and workroom_stage_release; "
           "the owner approves the release.")


def _scan(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("~$") or name.endswith(".workroom-restore"):
                continue
            p = Path(dirpath) / name
            found[p.relative_to(root).as_posix()] = p
            if len(found) >= MAX_FILES:
                return found
    return found


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _managed(rel: str, protected: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.lower().endswith(OFFICE) or any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(name, pat) for pat in protected)


def make_tripwire(projects: Callable[[], list[dict[str, Any]]], policy_of: Callable[[str], dict[str, Any]], keep_aside: Callable[[str, str, bytes], None],
                  keep_before: Callable[[str, str, bytes], None], published_since: Callable[[str, float], bool], note: Callable[[str, str, str], None]):
    """Returns (before, after): a pre_tool_call observer and a transform_tool_result hook.

    ``keep_aside(pid, relpath, bytes)`` stores what the agent made in place of a protected file; ``keep_before(pid, relpath, bytes)`` stores the before-image of an
    ordinary file the tool changed; ``published_since(pid, ts)`` says whether the owner published a release since ``ts``; ``note(pid, relpath, outcome)`` records it."""
    lock = threading.Lock()
    pending: dict[str, dict[str, Any]] = {}

    def key_of(kwargs: dict[str, Any]) -> str:
        return f"{kwargs.get('session_id', '')}|{kwargs.get('tool_call_id', '')}|{kwargs.get('task_id', '')}"

    def before(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any) -> None:
        try:
            if not watched(tool_name):
                return None
            shell = tool_name in SHELL_TOOLS
            state: dict[str, Any] = {"at": time.time(), "projects": {}, "shell": shell}
            total = 0
            for p in projects():
                root = Path(p["folder"]).resolve()
                if not root.is_dir():
                    continue
                try:
                    protected = list(policy_of(p["project"]).get("protected", []))
                except Exception:  # noqa: BLE001  without a readable policy only the Office files count as managed
                    protected = []
                files: dict[str, dict[str, Any]] = {}
                for rel, path in _scan(root).items():
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    managed = _managed(rel, protected)
                    if not managed and not shell:
                        continue  # an editing tool that is not a shell is watched for managed files only; ordinary files are not copied for it
                    entry: dict[str, Any] = {"managed": managed, "size": st.st_size, "mtime": st.st_mtime_ns, "digest": None, "data": None}
                    if st.st_size <= MAX_FILE and (managed or st.st_size <= KEEP_FILE):
                        try:
                            data = path.read_bytes()
                        except OSError:
                            data = None
                        if data is not None:
                            entry["digest"] = _digest(data)
                            if managed or total + len(data) <= MAX_TOTAL:
                                entry["data"] = data
                                total += len(data)
                    files[rel] = entry
                state["projects"][p["project"]] = (root, files, protected)
            with lock:
                while len(pending) >= 50:  # a call a guard blocked never reaches the after-hook; do not let those pile up
                    pending.pop(next(iter(pending)))
                pending[key_of(kwargs)] = state
        except Exception:  # noqa: BLE001  an observer never disturbs the call it watches
            return None
        return None

    def current(path: Path) -> tuple[str | None, bytes | None]:
        try:
            if path.stat().st_size > MAX_FILE:
                return None, None
            data = path.read_bytes()
            return _digest(data), data
        except OSError:
            return None, None

    def after(tool_name: str = "", args: dict[str, Any] | None = None, result: Any = None, **kwargs: Any):
        try:
            if not watched(tool_name):
                return None
            with lock:
                state = pending.pop(key_of(kwargs), None)
            if not state:
                return None
            reverted: list[str] = []
            unrestored: list[str] = []
            for pid, (root, files, protected) in state["projects"].items():
                if published_since(pid, state["at"]):
                    continue  # the owner published while the tool ran: those changes are theirs
                now = _scan(root)
                lost: dict[str, str] = {}  # digest of a managed file that is gone or different -> its path, to recognise a moved copy
                for rel, old in files.items():
                    if not old["managed"]:
                        continue
                    path = root / rel
                    if rel in now:
                        try:
                            st = path.stat()
                        except OSError:
                            continue
                        if st.st_size == old["size"] and st.st_mtime_ns == old["mtime"]:
                            continue
                    digest, data = current(path) if rel in now else (None, None)
                    if digest is not None and digest == old["digest"]:
                        continue
                    if old["digest"]:
                        lost[old["digest"]] = rel
                    if data is not None:
                        keep_aside(pid, rel, data)
                    if old["data"] is None:
                        unrestored.append(rel)
                        note(pid, rel, "changed and could not be restored")
                        continue
                    tmp = path.with_name(path.name + ".workroom-restore")
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        tmp.write_bytes(old["data"])
                        os.replace(tmp, path)
                        reverted.append(rel)
                        note(pid, rel, "restored")
                    except OSError:
                        unrestored.append(rel)
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                for rel in sorted(set(now) - set(files)):  # files that did not exist before the tool ran
                    digest, data = current(root / rel)
                    if data is None:
                        continue
                    if digest in lost or _managed(rel, protected) and rel.lower().endswith(OFFICE):
                        keep_aside(pid, rel, data)
                        try:
                            (root / rel).unlink()
                            reverted.append(rel)
                            note(pid, rel, "removed a moved copy or a new managed file")
                        except OSError:
                            unrestored.append(rel)
                for rel, old in files.items():  # ordinary files the tool changed or removed: a before-image, so Restore works whatever the command looked like
                    if old["managed"] or old["data"] is None:
                        continue
                    path = root / rel
                    if rel in now:
                        try:
                            st = path.stat()
                        except OSError:
                            continue
                        if st.st_size == old["size"] and st.st_mtime_ns == old["mtime"]:
                            continue
                        digest, _ = current(path)
                        if digest == old["digest"]:
                            continue
                    try:
                        keep_before(pid, rel, old["data"])
                    except Exception:  # noqa: BLE001  a before-image that cannot be stored must not hide the rest
                        continue
            if not reverted and not unrestored:
                return None
            text = MESSAGE.format(names=", ".join(sorted(set(reverted))) or "the file") if reverted else ""
            if unrestored:
                text += (" " if text else "") + "Could not put back " + ", ".join(unrestored) + " (too large to keep a copy, or in use); the owner can Restore it from the changes list."
            suffix = "\n\n[Workroom] " + text
            return (result if isinstance(result, str) else json.dumps(result, default=str)) + suffix
        except Exception:  # noqa: BLE001
            return None

    return before, after
