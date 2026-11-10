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
from .session_cwd import session_folder

_REMOVE_OR_MOVE = {"rm", "del", "erase", "mv", "move", "ren", "rename", "remove-item", "move-item", "rename-item", "shred", "unlink"}
_LAST_IS_TARGET = {"cp", "copy", "copy-item", "install", "xcopy"}
_REDIRECT = re.compile(r">>?\s*(\"[^\"]+\"|'[^']+'|[^\s;&|]+)")
_WIN_FLAG = re.compile(r"^/[A-Za-z?]{1,3}(?::\S*)?$")  # /s, /q, /y:... : a Windows switch, not a path


def _is_path(word: str) -> bool:
    if not word or word.startswith("-") or re.search(r"[*?\[]", word):
        return False
    return not _WIN_FLAG.match(word)


def shell_targets(text: str) -> list[str]:
    """Files a simple command removes, moves, overwrites or edits in place, as named on the command line. Wildcards, flags and switches are skipped; a
    pipeline is read command by command. A program that reaches files it does not name is not covered (stated in the product)."""
    out: list[str] = []
    for part in re.split(r"[;&|\n]+", text):
        try:
            words = [w.strip("\"'") for w in shlex.split(part, posix=False)]
        except ValueError:
            continue
        if not words:
            continue
        verb = words[0].lower()
        args = words[1:]
        if verb in _REMOVE_OR_MOVE:
            out += [w for w in args if _is_path(w)]
        elif verb in _LAST_IS_TARGET:
            paths = [w for w in args if _is_path(w)]
            out += paths[-1:]
        elif verb == "tee":
            out += [w for w in args if _is_path(w)]
        elif verb == "truncate":
            skip = False
            for w in args:
                if skip:
                    skip = False
                    continue
                if w in ("-s", "--size", "-r", "--reference"):
                    skip = True
                    continue
                if _is_path(w) and not w.startswith("--"):
                    out.append(w)
        elif verb == "sed" and any(w == "-i" or w.startswith("-i") or w == "--in-place" for w in args):
            rest = [w for w in args if not w.startswith("-")]
            out += [w for w in rest[1:] if _is_path(w)]  # the first word is the script
        elif verb == "dd":
            out += [w[3:] for w in args if w.startswith("of=") and _is_path(w[3:])]
        elif verb == "find" and "-delete" in args:
            root = next((w for w in args if _is_path(w) and not w.startswith("-")), ".")
            out.append(root)  # a folder: the guard asks first; no single file can be copied in advance
    out += [m.strip("\"'") for m in _REDIRECT.findall(text) if m.strip("\"'") not in ("/dev/null", "nul", "NUL", "&1", "&2")]
    return out


def _base_folder(args: dict[str, Any], kwargs: dict[str, Any]) -> str:
    """The folder relative paths in this call are read from: the tool's own workdir, else the session's folder. Empty when unknown."""
    given = next((str(args[k]) for k in ("workdir", "cwd", "working_dir", "directory") if isinstance(args.get(k), str) and args[k].strip()), "")
    if not given:
        here = session_folder(kwargs)
        given = str(here) if here else ""
    return _after_cd(_shell_text(args), given)


_CD = re.compile(r"(?:^|[;&|\n])\s*(?:cd|pushd|Set-Location)\s+(?:/d\s+)?(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", re.I)


def _after_cd(text: str, base: str) -> str:
    """The folder a command works in once its own leading ``cd`` has run: a model writes ``cd <folder> && mv a b`` and the paths after it are relative to that folder."""
    m = _CD.search(text or "")
    if not m:
        return base
    target = Path(m.group(1).strip("\"'")).expanduser()
    try:
        return str((Path(base) / target).resolve() if not target.is_absolute() and base else target.resolve())
    except OSError:
        return base


def make_snapshotter(projects: Callable[[], list[dict[str, Any]]], take: Callable[[str, str, str], None]):
    """``take(project_id, path, tool)`` stores one before-image."""

    def hook(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any) -> None:
        try:
            if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
                return None
            base = _base_folder(args, kwargs)
            raws = _paths(args) if tool_name in WRITE_TOOLS else shell_targets(_shell_text(args))
            for p in projects():
                folder = Path(p["folder"]).resolve()
                for raw in raws:
                    path = Path(raw).expanduser()
                    if not path.is_absolute():
                        if not base:
                            continue  # a relative path with no known folder could belong to any project; it is not guessed
                        path = Path(base) / path
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
