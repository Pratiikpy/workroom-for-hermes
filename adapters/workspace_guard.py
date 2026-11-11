"""pre_tool_call guard for the project's own policy: protected files cannot be changed by the agent, and removing or moving many files needs a human yes.

Protected patterns (paths inside the project, `*` allowed) block file-tool writes and shell commands that name the file. A shell command that removes or moves
a folder, a wildcard, or five or more files is sent to the human approval gate. Heuristics on command text, like the Office guard beside it: a program that
reaches files without naming them is not caught, and in an auto-approve mode the gate answers itself.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .guard import SHELL_TOOLS, WRITE_TOOLS, _folderish, _office_glob, _paths, _shell_text
from .snapshotter import _base_folder, shell_targets

MANY = 5
_ANY_GLOB = re.compile(r"[*?]")


def _rel(raw: str, folder: Path, base: str) -> str | None:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        if not base:
            return None  # a relative path with no known folder is not assumed to be inside this project
        path = Path(base) / path
    try:
        return path.resolve().relative_to(folder).as_posix()
    except (ValueError, OSError):
        return None


def make_workspace_guard(projects: Callable[[], list[dict[str, Any]]], policy_of: Callable[[str], dict[str, Any]]):
    def guard(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, str] | None:
        try:
            if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
                return None
            base = _base_folder(args, kwargs)
            shell = tool_name in SHELL_TOOLS
            text = _shell_text(args) if shell else ""
            raws = shell_targets(text) if shell else _paths(args)
            for p in projects():
                folder = Path(p["folder"]).resolve()
                rels = [r for r in (_rel(x, folder, base) for x in raws) if r is not None]
                in_folder = bool(rels) or (shell and bool(base) and _rel(base, folder, "") is not None)
                if not in_folder:
                    continue
                policy = policy_of(p["project"])
                for rel in rels:
                    for pat in policy["protected"]:
                        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat):
                            return {"action": "block", "message": f"{rel} is protected in this project's Workroom policy; the owner can change that in the Workroom tab."}
                if shell and policy["confirm_delete"] and _folderish(text):
                    many = len(rels) >= MANY or _ANY_GLOB.search(text) or _office_glob(text) or any((folder / r).is_dir() for r in rels)
                    if many:
                        return {"action": "approve", "message": f"This command removes or moves a folder, a wildcard or {MANY}+ files inside {folder.name}. A copy is kept only for files it names.",
                                "rule_key": "workroom-delete"}
        except Exception as exc:  # noqa: BLE001  the policy could not be checked: ask a person rather than let the call through unchecked
            return {"action": "approve", "message": f"Workroom could not check this project's protected-file policy ({type(exc).__name__}); approve only if you meant this change.",
                    "rule_key": "workroom-policy-error"}
        return None

    return guard
