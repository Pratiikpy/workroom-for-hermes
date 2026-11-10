"""pre_tool_call observer: before a tool changes a file inside a registered project, keep a copy of it (see snapshots.py).

Covers the file tools exactly (their arguments name the file) and shell commands that name files the command removes, moves or overwrites by redirect
(best effort: a command that reaches files it does not name, or runs a script, is not covered, and the product says so). It never blocks and never raises.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .guard import SHELL_TOOLS, WRITE_TOOLS, _paths, _shell_text

_DESTRUCTIVE = {"rm", "del", "erase", "mv", "move", "ren", "rename", "remove-item", "move-item", "rename-item", "truncate", "shred"}
_REDIRECT = re.compile(r">>?\s*(\"[^\"]+\"|'[^']+'|[^\s;&|]+)")


def shell_targets(text: str) -> list[str]:
    """File names a simple command removes, moves or overwrites. Flags and wildcards are skipped; a pipeline is read command by command."""
    out: list[str] = []
    for part in re.split(r"[;&|\n]+", text):
        try:
            words = shlex.split(part, posix=False)
        except ValueError:
            continue
        if not words:
            continue
        verb = words[0].strip("\"'").lower()
        if verb in _DESTRUCTIVE:
            out += [w.strip("\"'") for w in words[1:] if not w.startswith("-") and not w.startswith("/") and not re.search(r"[*?\[]", w)]
    out += [m.strip("\"'") for m in _REDIRECT.findall(text)]
    return out


def make_snapshotter(projects: Callable[[], list[dict[str, Any]]], take: Callable[[str, str, str], None]):
    """``take(project_id, path, tool)`` stores one before-image."""

    def hook(tool_name: str = "", args: dict[str, Any] | None = None, **_: Any) -> None:
        try:
            if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
                return None
            base = next((str(args[k]) for k in ("workdir", "cwd", "working_dir", "directory") if isinstance(args.get(k), str) and args[k].strip()), "")
            raws = _paths(args) if tool_name in WRITE_TOOLS else shell_targets(_shell_text(args))
            for p in projects():
                folder = Path(p["folder"]).resolve()
                for raw in raws:
                    path = Path(raw).expanduser()
                    if not path.is_absolute():
                        path = (Path(base) if base else folder) / path
                    try:
                        path = path.resolve()
                        path.relative_to(folder)
                    except (ValueError, OSError):
                        continue
                    take(p["project"], str(path), tool_name)
        except Exception:  # noqa: BLE001  an observer must never break a tool call
            return None
        return None

    return hook
