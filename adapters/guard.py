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
from typing import Any
from collections.abc import Callable

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
    r"\bos\.replace\b|unzip\s+-o|sed\s+-i|open\s{0,8}\([^)\n]{0,200}['\"][wax]\+?b?['\"])", re.I)
# verbs that can reach files nobody named: a whole folder, a wildcard, a working directory
_FOLDERISH = re.compile(
    r"\b(?:rm|del|erase|rd|rmdir|rmtree|remove|removedirs|unlink\w*|rmSync|Delete|move|mv|ren|rename|renames|robocopy|xcopy|Remove-Item|Move-Item|Rename-Item|Clear-Content)\b", re.I)
_OFFICE_EXT = re.compile(r"\.(?:pptx|docx|xlsx)\b", re.I)
_OFFICE_WORD = re.compile(r"(?:pptx|docx|xlsx)", re.I)
_NAME_RUN = re.compile(r"[^\s'\"<>|]+")
_GLOB_CHAR = re.compile(r"[*?\[{]")
_GIT_STEP = re.compile(r"(?P<cut>[;&|\n])|(?P<git>\bgit\b)|(?P<verb>\b(?:checkout|restore|reset|clean|stash|mv|rm)\b)", re.I)
NAME_SPAN = 260
GIT_SPAN = 200


def _office_names(text: str) -> list[str]:
    """Every Office file name in the text, each at most NAME_SPAN characters before its extension. The text is walked once, run by run, so a long run without spaces costs no more than its length."""
    names: list[str] = []
    seen: set[str] = set()
    for run in _NAME_RUN.finditer(text):
        token = run.group()
        for m in _OFFICE_EXT.finditer(token):
            name = token[max(0, m.start() - NAME_SPAN):m.end()]
            if m.start() and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _office_glob(text: str) -> bool:
    """A wildcard that could reach an Office file: a wildcard character followed, in the same run of name characters and within NAME_SPAN, by an Office extension."""
    for run in _NAME_RUN.finditer(text):
        token = run.group()
        for m in _OFFICE_WORD.finditer(token):
            if _GLOB_CHAR.search(token, max(0, m.start() - NAME_SPAN), m.start()):
                return True
    return False


def _git_rewrite(text: str) -> bool:
    """A git command that can rewrite or remove working files: the word git and, in the same command and within GIT_SPAN characters, checkout, restore, reset, clean, stash, mv or rm. One pass."""
    git_at = -1
    for m in _GIT_STEP.finditer(text):
        if m.lastgroup == "cut":
            git_at = -1
        elif m.lastgroup == "git":
            git_at = m.end()
        elif git_at >= 0 and m.start() - git_at <= GIT_SPAN:
            return True
    return False


def _writeish(text: str) -> bool:
    return bool(_WRITEISH.search(text)) or _git_rewrite(text)


def _folderish(text: str) -> bool:
    return bool(_FOLDERISH.search(text)) or _git_rewrite(text)


SHELL_MESSAGE = ("This command looks like it writes {name}, which Workroom manages. A direct change bypasses the verified release; "
                 "approve only if you mean to edit it by hand.")


def _shell_text(args: dict[str, Any]) -> str:
    return " ".join(str(args[k]) for k in ("command", "cmd", "code", "script") if isinstance(args.get(k), str))


_SCRIPT_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".rb", ".pl", ".php")
_TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|[^\s'\"]+")
MAX_SCRIPT_BYTES = 64 * 1024


def _script_text(command: str, args: dict[str, Any]) -> tuple[str, bool]:
    """Scan up to 64 KiB total; require approval when a named script cannot be fully inspected."""
    base = next((str(args[k]) for k in ("workdir", "cwd", "working_dir", "directory") if isinstance(args.get(k), str) and args[k].strip()), "")
    found: list[str] = []
    remaining = MAX_SCRIPT_BYTES
    seen: set[Path] = set()
    for token in _TOKEN.findall(command):
        name = token.strip("\"'")
        if not name.lower().endswith(_SCRIPT_EXT):
            continue
        try:
            path = Path(name).expanduser()
            if not path.is_absolute() and base:
                path = Path(base).expanduser() / path
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                with path.open("rb") as script:
                    data = script.read(remaining + 1)
                if len(data) > remaining:
                    return "\n".join(found), True
                remaining -= len(data)
                found.append(data.decode("utf-8", errors="replace"))
        except OSError:
            return "\n".join(found), True
    return "\n".join(found), False


def make_guard(roots: Callable[[], list[str]]) -> Callable[..., dict[str, str] | None]:
    def guard(tool_name: str = "", args: dict[str, Any] | None = None, **_: Any) -> dict[str, str] | None:
        if not isinstance(args, dict) or (tool_name not in WRITE_TOOLS and tool_name not in SHELL_TOOLS):
            return None
        managed = [Path(r).resolve() for r in roots()]
        if not managed:
            return None
        if tool_name in SHELL_TOOLS:
            text = _shell_text(args)
            scripts, incomplete = _script_text(text, args) if len(text) <= MAX_SCRIPT_BYTES else ("", True)
            if incomplete:
                return {"action": "approve", "message": SHELL_MESSAGE.format(name="a script Workroom could not fully inspect"), "rule_key": "workroom-shell-write"}
            text = text + "\n" + scripts
            if not _writeish(text):
                return None
            if _office_glob(text):
                return {"action": "approve", "message": SHELL_MESSAGE.format(name="the Office files in this folder"), "rule_key": "workroom-shell-write"}
            lowered = text.lower().replace("\\", "/")
            folderish = _folderish(text)
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
            if not any(ext in text.lower() for ext in OFFICE):
                return None
            for raw in _office_names(text):
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
