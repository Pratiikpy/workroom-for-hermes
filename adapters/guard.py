"""pre_tool_call guard: the agent's own file tools may not write Office files inside a registered project.

Releases go through Workroom so every change is verified, approved and recoverable. A write that bypasses it would
silently desynchronise the saved links. File-tool arguments are checked exactly and blocked. Shell commands are checked heuristically (a write-like verb plus the
name of a managed Office file) and escalated to the human approval gate. A command that runs a script file is read together with that script (a real model, told to skip
approval, wrote a Python script and ran it by name, so the command text alone showed nothing). A determined program can still evade this, and in an auto-approve mode
the approval gate answers itself.
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
_WRITEISH = re.compile(
    r"(>>?|\b(?:mv|cp|rm|del|erase|rd|rmdir|move|copy|copyfile|ren|rename|renames|touch|tee|truncate|dd|zip|7z|xcopy|robocopy|mklink|save|saveas|write|write_bytes|write_text|writelines|"
    r"writeFile\w*|appendFile\w*|unlink\w*|rmSync|rmtree|remove|removedirs|Delete|WriteAll\w*|copyFile\w*|createWriteStream|"
    r"Set-Content|Add-Content|Clear-Content|Out-File|Remove-Item|Move-Item|Copy-Item|Rename-Item|New-Item|Compress-Archive|Expand-Archive)\b|"
    r"\bos\.replace\b|\bgit\b[^;&|]*\b(?:checkout|restore|reset|clean|stash|mv|rm)\b|unzip\s+-o|sed\s+-i|open\s*\([^)]*['\"][wax]\+?b?['\"])", re.I)
# verbs that can reach files nobody named: a whole folder, a wildcard, a working directory
_FOLDERISH = re.compile(
    r"(?:\b(?:rm|del|erase|rd|rmdir|rmtree|remove|removedirs|unlink\w*|rmSync|Delete|move|mv|ren|rename|renames|robocopy|xcopy|Remove-Item|Move-Item|Rename-Item|Clear-Content)\b|"
    r"\bgit\b[^;&|]*\b(?:checkout|restore|reset|clean|stash|mv|rm)\b)", re.I)
_GLOB = re.compile(r"[*?\[{][^\s'\"<>|]*(?:pptx|docx|xlsx)", re.I)
_OFFICE_NAME = re.compile(r"[^\s'\"<>|]+\.(?:pptx|docx|xlsx)\b", re.I)
SHELL_MESSAGE = ("This command looks like it writes {name}, which Workroom manages. A direct change bypasses the verified release; "
                 "approve only if you mean to edit it by hand.")


def _shell_text(args: dict[str, Any]) -> str:
    return " ".join(str(args[k]) for k in ("command", "cmd", "code", "script") if isinstance(args.get(k), str))


_SCRIPT_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".rb", ".pl", ".php")
_TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|[^\s'\"]+")
MAX_SCRIPT_BYTES = 400_000


def _script_text(command: str, args: dict[str, Any]) -> str:
    """The text of every script file the command names, so a write hidden inside a script is judged like one typed on the command line."""
    base = next((str(args[k]) for k in ("workdir", "cwd", "working_dir", "directory") if isinstance(args.get(k), str) and args[k].strip()), "")
    found: list[str] = []
    for token in _TOKEN.findall(command):
        name = token.strip("\"'")
        if not name.lower().endswith(_SCRIPT_EXT):
            continue
        try:
            path = Path(name).expanduser()
            if not path.is_absolute() and base:
                path = Path(base).expanduser() / path
            if path.is_file() and path.stat().st_size <= MAX_SCRIPT_BYTES:
                found.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(found)


def make_guard(roots: Callable[[], list[str]]) -> Callable[..., dict[str, str] | None]:
    def guard(tool_name: str = "", args: dict[str, Any] | None = None, **_: Any) -> dict[str, str] | None:
        if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
            return None
        managed = [Path(r).resolve() for r in roots()]
        if not managed:
            return None
        if tool_name in SHELL_TOOLS:
            text = _shell_text(args)
            text = text + "\n" + _script_text(text, args)
            if not _WRITEISH.search(text):
                return None
            if _GLOB.search(text):
                return {"action": "approve", "message": SHELL_MESSAGE.format(name="the Office files in this folder"), "rule_key": "workroom-shell-write"}
            lowered = text.lower().replace("\\", "/")
            folderish = bool(_FOLDERISH.search(text))
            for m in managed:
                if folderish and m.as_posix().lower() in lowered:
                    return {"action": "approve", "message": SHELL_MESSAGE.format(name=f"files inside {m.name}"), "rule_key": "workroom-shell-write"}
            for key in ("workdir", "cwd", "working_dir", "directory"):
                if folderish and isinstance(args.get(key), str) and args[key].strip():
                    try:
                        here = Path(args[key]).expanduser().resolve()
                    except OSError:
                        continue
                    if any(here == m or m in here.parents for m in managed):
                        return {"action": "approve", "message": SHELL_MESSAGE.format(name=f"files inside {here.name}"), "rule_key": "workroom-shell-write"}
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
