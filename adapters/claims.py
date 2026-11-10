"""transform_llm_output helper: a reply that says a file was made, when no such file exists, gets one honest line under it.

A real model asked for a 6-slide deck made two workbooks, staged them for approval, and then wrote "I created a 6-slide board deck" with a slide-by-slide summary.
There was no deck: nothing was in the folder, and what was staged was two spreadsheets. The reply is never rewritten; one line says what is actually there, and
when a release that would create the file is waiting, that nothing is written until the owner approves it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .session_cwd import session_folder

KINDS = {
    "deck": (r"deck|presentation|slides?|slide deck|pptx|powerpoint", (".pptx",)),
    "report": (r"report|word document|docx|memo", (".docx",)),
    "workbook": (r"spreadsheet|workbook|xlsx|excel file", (".xlsx",)),
}
_MADE = r"(?:created|made|built|produced|prepared|generated|wrote|written|saved|put together|finished|completed|have (?:now )?(?:made|created|built))"
_CLAIM = {k: re.compile(rf"\b{_MADE}\b[^.\n]{{0,80}}?\b(?:{words})\b", re.I) for k, (words, _) in KINDS.items()}
_NEGATED = re.compile(r"\b(?:not|n't|never|could ?n'?t|unable|cannot|can't|failed|without)\b[^.\n]{0,40}$", re.I)


def claimed_kinds(text: str) -> list[str]:
    out = []
    for kind, rx in _CLAIM.items():
        for m in rx.finditer(text or ""):
            before = text[max(0, m.start() - 40): m.start()]
            if _NEGATED.search(before):
                continue
            out.append(kind)
            break
    return out


def make_claim_check(projects: Callable[[], list[dict[str, Any]]], staged: Callable[[str], list[str]]):
    """``staged(pid)`` lists the paths of files that releases waiting for approval would create."""

    def check(response_text: str = "", **kwargs: Any) -> str | None:
        try:
            if not isinstance(response_text, str) or len(response_text) < 20:
                return None
            kinds = claimed_kinds(response_text)
            if not kinds:
                return None
            here = session_folder(kwargs)
            if here is None:
                return None
            pid = root = None
            for p in projects():
                r = Path(p["folder"]).resolve()
                try:
                    here.relative_to(r)
                except ValueError:
                    continue
                pid, root = p["project"], r
                break
            if pid is None or root is None:
                return None
            waiting = list(staged(pid))
            notes = []
            for kind in kinds:
                suffixes = KINDS[kind][1]
                present = [str(f.relative_to(root)) for s in suffixes for f in list(root.rglob("*" + s))[:50] if f.is_file()]
                waiting_here = [w for w in waiting if w.lower().endswith(suffixes)]
                label = {"deck": "deck", "report": "report", "workbook": "workbook"}[kind]
                if present:
                    continue
                if waiting_here:
                    notes.append(f"the {label} is not in your folder yet: {', '.join(waiting_here)} {'is' if len(waiting_here) == 1 else 'are'} waiting for your approval, and nothing is written until you approve")
                elif waiting:
                    notes.append(f"no {label} exists in your folder or is waiting for approval; what is waiting is {', '.join(waiting)}")
                else:
                    notes.append(f"no {label} exists in your folder, and none is waiting for approval")
            if not notes:
                return None
            return response_text.rstrip() + "\n\n_Workroom: " + "; ".join(notes) + "._"
        except Exception:  # noqa: BLE001  a reply is never lost to a check
            return None

    return check
