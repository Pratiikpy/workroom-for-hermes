"""The working folder of the Hermes session a hook is running for.

Hooks do not receive it as an argument (``pre_llm_call`` gets ``session_id`` and friends, no folder; Hermes v0.23.0 ``agent/turn_context.py``), but each turn runs
with the session's folder in a context variable (``agent.runtime_cwd.scoped_session_cwd``) and the terminal tool records it per session
(``tools.terminal_tool.get_session_cwd``). These are internal to Hermes, so every read is guarded: when none answers, the caller gets nothing and must not guess
(the process's own folder belongs to the backend, not to the session).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def session_folder(kwargs: dict[str, Any]) -> Path | None:
    candidates: list[str] = []
    for key in ("cwd", "workdir", "session_cwd"):
        if isinstance(kwargs.get(key), str):
            candidates.append(kwargs[key])
    try:
        from agent.runtime_cwd import scoped_session_cwd

        candidates.append(scoped_session_cwd())
    except Exception:  # noqa: BLE001  not running inside Hermes, or the internal moved
        pass
    sid = kwargs.get("session_id") or kwargs.get("task_id")
    if sid:
        try:
            from tools.terminal_tool import get_session_cwd

            candidates.append(get_session_cwd(str(sid)) or "")
        except Exception:  # noqa: BLE001
            pass
    for raw in candidates:
        if raw and raw.strip():
            try:
                p = Path(raw.strip()).expanduser()
                if p.is_dir():
                    return p.resolve()
            except OSError:
                continue
    return None
