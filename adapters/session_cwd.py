"""The working folder of the Hermes session a hook is running for.

Hooks do not receive it as an argument (``pre_llm_call`` gets ``session_id`` and friends, no folder), and ``os.getcwd()`` is the gateway's own folder, shared
by every session. Hermes documents ``ctx.session_cwd()`` for this ("the working directory of the session the hook or tool runs for"; user guide, Plugins,
"Plugin code inside the gateway"); ``register()`` hands it to ``use(ctx.session_cwd)``. When it answers nothing, callers get nothing and must not guess.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

_provider: Callable[[], str] | None = None


def use(provider: Callable[[], str] | None) -> None:
    global _provider
    _provider = provider


def session_folder(kwargs: dict[str, Any]) -> Path | None:
    candidates: list[str] = [kwargs[k] for k in ("cwd", "workdir", "session_cwd") if isinstance(kwargs.get(k), str)]
    if _provider is not None:
        try:
            candidates.append(_provider() or "")
        except Exception:  # noqa: BLE001  outside a session the documented call may raise; that means "no folder"
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
