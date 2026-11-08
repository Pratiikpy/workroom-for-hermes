"""pre_tool_call guard: the agent's own file tools may not write Office files inside a registered project.

Releases go through Workroom so every change is verified, approved and recoverable. A write that bypasses it would
silently desynchronise the saved links. File-tool arguments are checked exactly and blocked. Shell commands are checked heuristically (a write-like verb plus the
name of a managed Office file) and escalated to the human approval gate; a determined script can still evade this.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

OFFICE = (".pptx", ".docx", ".xlsx")
WRITE_TOOLS = {"write_file", "patch", "edit_file", "apply_patch"}
_PATCH_PATH = re.compile(r"^\*\*\* (?:Update File|Add File|Delete File|Update|Add|Delete|Move to):?\s+(.+?)\s*$", re.M)
MESSAGE = ("Workroom manages {name}. Editing it directly would bypass the verified release. "
           "Change the source numbers, then use workroom_plan and workroom_stage_release; the owner approves the release.")


def _paths(args: dict[str, Any]) -> list[str]:
    out = [str(args[k]) for k in ("path", "file_path", "filename", "target") if isinstance(args.get(k), str)]
    for k in ("patch", "diff", "content_patch"):
        if isinstance(args.get(k), str):
            out += _PATCH_PATH.findall(args[k])
    return out


SHELL_TOOLS = {"terminal", "shell", "bash", "execute_code", "run_command"}
_WRITEISH = re.compile(r"(>>?|\b(?:mv|cp|rm|del|move|copy|ren|rename|touch|tee|truncate|dd|zip|7z|unzip -o|Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|save|write)\b|sed\s+-i|open\s*\([^)]*['\"][wax]\+?b?['\"])", re.I)
_OFFICE_NAME = re.compile(r"[^\s'\"<>|]+\.(?:pptx|docx|xlsx)\b", re.I)
SHELL_MESSAGE = ("This command looks like it writes {name}, which Workroom manages. A direct change bypasses the verified release; "
                 "approve only if you mean to edit it by hand.")


def _shell_text(args: dict[str, Any]) -> str:
    return " ".join(str(args[k]) for k in ("command", "cmd", "code", "script") if isinstance(args.get(k), str))


def make_guard(roots: Callable[[], list[str]]) -> Callable[..., dict[str, str] | None]:
    def guard(tool_name: str = "", args: dict[str, Any] | None = None, **_: Any) -> dict[str, str] | None:
        if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
            return None
        managed = [Path(r).resolve() for r in roots()]
        if not managed:
            return None
        if tool_name in SHELL_TOOLS:
            text = _shell_text(args)
            if not _WRITEISH.search(text):
                return None
            for raw in _OFFICE_NAME.findall(text):
                try:
                    rp = Path(raw.strip("\"'")).expanduser().resolve()
                except OSError:
                    continue
                if any(rp == m or m in rp.parents for m in managed) or any((m / rp.name).exists() for m in managed):
                    return {"action": "approve", "message": SHELL_MESSAGE.format(name=rp.name), "rule_key": "workroom-shell-write"}
            return None
        for raw in _paths(args):
            p = Path(raw).expanduser()
            if p.suffix.lower() not in OFFICE:
                continue
            try:
                rp = p.resolve()
            except OSError:
                continue
            if any(rp == m or m in rp.parents for m in managed):
                return {"action": "block", "message": MESSAGE.format(name=rp.name)}
        return None

    return guard
