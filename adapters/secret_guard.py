"""pre_tool_call guard: no tool may name Workroom's own data folder (signing key, evidence store, approvals), so an agent cannot read the key, edit the
evidence it is judged by, or forge a record. A string match on every argument of every tool; a program that builds the path from pieces can still reach it
(stated in the product's limits), and the key file is not readable by other operating-system users.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def _norm(text: str) -> str:
    return text.replace("\\", "/").lower()


def _strings(value: Any, depth: int = 0):
    if depth > 4:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, depth + 1)


def make_secret_guard(secret_dirs: Callable[[], list[Path]]):
    def guard(tool_name: str = "", args: dict[str, Any] | None = None, **_: Any) -> dict[str, str] | None:
        try:
            if not isinstance(args, dict) or tool_name.startswith("workroom_"):
                return None  # Workroom's own tools are the sanctioned way in
            needles = [_norm(str(d.resolve())) for d in secret_dirs()]
            for text in _strings(args):
                low = _norm(text)
                for n in needles:
                    if n and n in low:
                        return {"action": "block", "message": "Workroom's private data folder (signing key, evidence, approvals) is not available to agent tools."}
        except Exception:  # noqa: BLE001  this guard must not break unrelated tool calls; the key file's own permissions remain
            return None
        return None

    return guard
