"""Hooks that capture what the agent read and check the figures in what it writes (see workroom_core/figure_proof.py).

post_tool_call stores the result of every reading tool as evidence for the session; pre_llm_call stores the owner's message as evidence of what the owner
stated; transform_tool_result checks a text deliverable right after it is written and adds one line to the tool result; pre_verify asks the agent once to
source or label figures that still have no source. None of them blocks a tool call, and none of them raises.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .guard import WRITE_TOOLS, _paths
from .session_cwd import session_folder

READING = ("read_file", "search_files", "web_", "browser_", "terminal", "process", "execute_code", "vision", "video_analyze", "mcp_", "delegate", "session_search", "skill_view")
OFFICE = (".xlsx", ".docx", ".pptx", ".pdf")


def _abs(raw: str, kwargs: dict[str, Any], args: dict[str, Any]) -> Path | None:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        base = next((str(args[k]) for k in ("workdir", "cwd") if isinstance(args.get(k), str) and args[k].strip()), "") or str(session_folder(kwargs) or "")
        if not base:
            return None
        p = Path(base) / p
    try:
        return p.resolve()
    except OSError:
        return None


def make_proof_hooks(store: Callable[[], Any]):
    from ..workroom_core.figure_proof import TEXT_DELIVERABLES, check_file, evidence_text_of_file, result_text

    def capture(tool_name: str = "", args: dict[str, Any] | None = None, result: Any = None, **kwargs: Any) -> None:
        try:
            session = str(kwargs.get("session_id") or "")
            if not session or tool_name in WRITE_TOOLS or not tool_name.startswith(READING):
                return None
            args = args if isinstance(args, dict) else {}
            ref = str(args.get("path") or args.get("url") or args.get("query") or args.get("command") or tool_name)[:500]
            text = result_text(result)
            if tool_name == "read_file":
                target = _abs(str(args.get("path") or ""), kwargs, args)
                if target is not None and target.suffix.lower() in OFFICE:
                    text = evidence_text_of_file(target) or text
                    ref = str(target)
            st = store()
            try:
                st.add(session, tool_name, ref, text)
            finally:
                st.close()
        except Exception:  # noqa: BLE001  evidence capture must never break a tool call
            return None
        return None

    def owner(user_message: str = "", **kwargs: Any) -> None:
        try:
            session = str(kwargs.get("session_id") or "")
            if session and isinstance(user_message, str) and user_message.strip():
                st = store()
                try:
                    st.add(session, "owner", "chat", user_message, kind="owner")
                finally:
                    st.close()
        except Exception:  # noqa: BLE001
            return None
        return None

    def written(tool_name: str = "", args: dict[str, Any] | None = None, result: Any = None, **kwargs: Any):
        try:
            if tool_name not in WRITE_TOOLS or not isinstance(args, dict) or not isinstance(result, str):
                return None
            session = str(kwargs.get("session_id") or "")
            notes = []
            for raw in _paths(args):
                target = _abs(raw, kwargs, args)
                if target is None or target.suffix.lower() not in TEXT_DELIVERABLES:
                    continue
                st = store()
                try:
                    summ = check_file(st, session, target)
                finally:
                    st.close()
                if summ and summ["figures"]:
                    if summ["unsourced"]:
                        notes.append(f"Workroom proof for {target.name}: {summ['unsourced']} of {summ['figures']} figures are not verified by anything you read this session "
                                     f"({', '.join(summ['unsourced_figures'][:6])}). Source each one, or say plainly in the text that it is an estimate.")
                    else:
                        notes.append(f"Workroom proof for {target.name}: all {summ['figures']} figures are supported by what you read this session (supported means the figure appears where its words point, not that the claim is true).")
            return result + "\n\n" + "\n".join(notes) if notes else None
        except Exception:  # noqa: BLE001
            return None

    def verify(session_id: str = "", attempt: int = 0, changed_paths: list | None = None, **_: Any):
        try:
            if attempt or not changed_paths:
                return None
            open_figures = []
            st = store()
            try:
                for raw in changed_paths:
                    target = Path(str(raw))
                    if target.suffix.lower() not in TEXT_DELIVERABLES:
                        continue
                    summ = check_file(st, str(session_id or ""), target)
                    if summ and summ["unsourced"]:
                        open_figures.append(f"{target.name}: {', '.join(summ['unsourced_figures'][:6])}")
            finally:
                st.close()
            if open_figures:
                return {"action": "continue", "message": "Before you finish: these figures are not verified by anything you read this session. "
                        "Find a source for each, or mark it as an estimate in the text. " + "; ".join(open_figures)}
        except Exception:  # noqa: BLE001
            return None
        return None

    def reply(response_text: str = "", session_id: str = "", **_: Any):
        """One line under a reply whose figures have no source in what was read this session. The reply itself is never changed."""
        try:
            if not session_id or not isinstance(response_text, str) or not response_text.strip():
                return None
            from ..workroom_core.figure_proof import check_text

            st = store()
            try:
                items = st.items(str(session_id))
            finally:
                st.close()
            loose = [p for p in check_text(response_text, items) if p.state == "unsourced" and not p.weak]
            if not loose:
                return None
            names = ", ".join(dict.fromkeys(p.raw for p in loose))
            n = len(loose)
            verb = "has" if n == 1 else "have"
            return response_text.rstrip() + "\n\n" + f"_Workroom: {n} figure{'' if n == 1 else 's'} in this reply {verb} not verified by anything read this session: {names[:200]}._"
        except Exception:  # noqa: BLE001  a reply is never lost to a proof error
            return None

    return capture, owner, written, verify, reply
