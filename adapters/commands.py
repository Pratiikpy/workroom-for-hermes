"""The /workroom-approve slash command: approve a prepared release from any surface Hermes supports.

Only a person can run a slash command; the agent cannot. On a messaging chat the gateway has already authenticated the
sender, and Workroom additionally requires the sender to be listed under `approvers` in its settings. The choice is
asked through Hermes' own prompt (buttons on Telegram, Discord and Slack; a picker in the CLI and Desktop), so no
platform-specific code is needed. The approval is bound to the release digest shown in the prompt.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..workroom_core.service import Service, ServiceError

APPROVE = "Approve and publish"
CANCEL = "Cancel"
_LOCAL_PLATFORMS = (None, "", "cli", "local", "desktop", "tui", "api_server")


def principal_for(platform: Any, source: Any) -> str:
    plat = str(getattr(platform, "value", platform) or "").lower() or None
    if plat in _LOCAL_PLATFORMS:
        return "local:session"
    uid = getattr(source, "user_id", None)
    return f"{plat}:{uid}" if uid else f"{plat}:unknown"


def _card(view: dict[str, Any]) -> str:
    lines = [f"Workroom release {view['release_id']}: {len(view['changes'])} number(s) will change in your documents."]
    for c in view["changes"][:6]:
        lines.append(f"  {c['old_text']} -> {c['new_text']}   ({c['deck']}, {c.get('where') or 'slide ' + str(c['slide'])})")
    if len(view["changes"]) > 6:
        lines.append(f"  and {len(view['changes']) - 6} more")
    if view.get("held"):
        lines.append(f"{len(view['held'])} held for you")
    lines.append("Nothing has changed yet. A backup of every replaced file is kept.")
    lines.append(f"Fingerprint {view['digest'][:12]}; your answer applies to exactly this release.")
    return "\n".join(lines)


def make_approve_command(service_factory: Callable[[], Service], ask_choice: Callable[[str, list], Any],
                         approvers: Callable[[], list]) -> Callable[..., str]:
    def handler(raw_args: str, source: Any = None, platform: Any = None, **_: Any) -> str:
        svc = service_factory()
        principal = principal_for(platform, source)
        allowed = {str(a) for a in (approvers() or [])}
        if principal != "local:session" and principal not in allowed:
            return (f"{principal} is not allowed to approve Workroom releases. "
                    f"The owner adds it to the `approvers` setting of the Workroom plugin.")
        parts = raw_args.split()
        try:
            if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{12}", parts[0]) and re.fullmatch(r"[0-9a-f]{16}", parts[1]):
                pid, rid = parts
            elif not parts:
                found = svc.latest_awaiting()
                if found is None:
                    return "No Workroom release is waiting for approval."
                pid, rid = found
            else:
                return "Usage: /workroom-approve [<project> <release>]"
            view = svc.release_view(pid, rid)
            if view["state"] != "awaiting_approval":
                return f"That release is not waiting for approval (it is {view['state']})."
            choice = ask_choice(_card(view), [APPROVE, CANCEL])
            if choice != APPROVE:
                return "Nothing was changed." if choice == CANCEL else "No answer was given; nothing was changed."
            svc.approve_and_publish(pid, rid, view["digest"], principal=principal, channel=str(getattr(platform, "value", platform) or "local"))
            return f"Published {len(view['changes'])} number(s). A backup of each replaced file is kept."
        except ServiceError as exc:
            return f"Not published: {exc}"

    return handler
