"""subagent_start / subagent_stop observers: the helper agents the main agent starts are recorded in the Room of the project the session works in.

Hermes passes the helper's role, goal, final status, summary, duration and a history of its tool calls with the files they named. The Room keeps what the
helper was asked, how it ended, and which files inside the project it touched, so the owner sees who did what. These hooks only observe: they never block,
never raise, and record nothing when the session is not working inside a registered project.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .session_cwd import session_folder

_WRITING = {"write_file", "patch", "edit_file", "create_file", "str_replace", "apply_patch", "terminal", "shell", "bash", "execute_code"}


def _project_of(projects: list[dict[str, Any]], folder: Path | None) -> str | None:
    if folder is None:
        return None
    best: tuple[int, str] | None = None
    for p in projects:
        try:
            root = Path(p["folder"]).resolve()
            folder.relative_to(root)
        except (ValueError, OSError):
            continue
        if best is None or len(str(root)) > best[0]:
            best = (len(str(root)), p["project"])
    return best[1] if best else None


def files_touched(history: Any, root: Path | None) -> list[str]:
    """Project-relative paths the helper's tool calls named, from the call history Hermes hands over."""
    out: list[str] = []
    if not isinstance(history, list):
        return out
    for call in history:
        if not isinstance(call, dict) or call.get("tool_name") not in _WRITING:
            continue
        targets = (call.get("tool_input") or {}).get("targets") or {}
        for value in targets.values() if isinstance(targets, dict) else []:
            for raw in value if isinstance(value, list) else [value]:
                if not isinstance(raw, str) or not raw.strip():
                    continue
                path = raw.strip()
                if root is not None:
                    target = Path(path) if Path(path).is_absolute() else root / path
                    try:
                        path = target.resolve().relative_to(root).as_posix()  # a relative path that climbs out with .. is not inside the project either
                    except ValueError:
                        continue
                if path not in out:
                    out.append(path)
    return out


def make_crew_hooks(projects: Callable[[], list[dict[str, Any]]], record: Callable[..., Any]):
    owner: dict[str, str] = {}  # child id -> project, so a stop (which may run on another thread) lands where its start did

    def start(**kwargs: Any) -> None:
        try:
            pid = _project_of(projects(), session_folder(kwargs))
            if pid is None:
                return
            child = str(kwargs.get("child_subagent_id") or "")
            owner[child] = pid
            record(pid, "start", parent=str(kwargs.get("parent_session_id") or ""), child=child, role=str(kwargs.get("child_role") or ""),
                   goal=str(kwargs.get("child_goal") or ""))
        except Exception:  # noqa: BLE001  an observer must never disturb the run it watches
            return

    def stop(**kwargs: Any) -> None:
        try:
            child = str(kwargs.get("child_subagent_id") or "")
            pid = owner.pop(child, None) or _project_of(projects(), session_folder(kwargs))
            if pid is None:
                return
            root = next((Path(p["folder"]).resolve() for p in projects() if p["project"] == pid), None)
            record(pid, "stop", parent=str(kwargs.get("parent_session_id") or ""), child=child, status=str(kwargs.get("child_status") or "done"),
                   summary=str(kwargs.get("child_summary") or ""), duration_ms=int(kwargs.get("duration_ms") or 0),
                   files=files_touched(kwargs.get("tool_call_history"), root))
        except Exception:  # noqa: BLE001
            return

    return start, stop
