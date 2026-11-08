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
APPROVE_SEEN = "Approve and publish; I have read the flagged sentences"
CANCEL = "Cancel"
_LOCAL_PLATFORMS = (None, "", "cli", "local", "desktop", "tui", "api_server")


def principal_for(platform: Any, source: Any) -> str:
    plat = str(getattr(platform, "value", platform) or "").lower() or None
    if plat in _LOCAL_PLATFORMS:
        return "local:session"
    uid = getattr(source, "user_id", None)
    return f"{plat}:{uid}" if uid else f"{plat}:unknown"


def _card(view: dict[str, Any]) -> str:
    if view.get("created"):
        grouped: dict[tuple, int] = {}
        for f in view.get("figures", []):
            grouped[(f["text"], f["source"])] = grouped.get((f["text"], f["source"]), 0) + 1
        lines = [f"Workroom release {view['release_id']}: will create {view['changes'][0]['deck']} with {len(view.get('figures', []))} figures, each tied to its source cell."]
        for (text, source), n in list(grouped.items())[:6]:
            lines.append(f"  {text}   ({source}{', in ' + str(n) + ' places' if n > 1 else ''})")
        if len(grouped) > 6:
            lines.append(f"  and {len(grouped) - 6} more")
        lines.append("Nothing has been written yet. Restore removes the new file again.")
    elif view.get("edited_page"):
        lines = [f"Workroom release {view['release_id']}: your edits to {view['changes'][0]['deck']} will be written ({view['changes'][0]['new_text']}).",
                 "Nothing has been written yet. A backup of the replaced file is kept."]
    elif view.get("rolled"):
        r = view["rolled"]
        span = f" ({', '.join(r['from'])} to {', '.join(r['to'])})" if r["from"] and r["to"] else ""
        lines = [f"Workroom release {view['release_id']}: rolls your documents forward {r['steps']} period{'s' if r['steps'] != 1 else ''}{span}: {r['figures']} figures re-pointed to the next period, {r['period_words']} period words advanced."]
        for c in view["changes"][:5]:
            lines.append(f"  {c['old_text']} -> {c['new_text']}   ({c['deck']}, {c.get('where') or 'slide ' + str(c['slide'])})")
        if len(view["changes"]) > 5:
            lines.append(f"  and {len(view['changes']) - 5} more")
        if view.get("held"):
            lines.append(f"{len(view['held'])} left for you")
        lines.append("Nothing has changed yet. A backup of every replaced file is kept, and Restore undoes the whole roll.")
    else:
        lines = [f"Workroom release {view['release_id']}: {len(view['changes'])} number(s) will change in your documents."]
        for c in view["changes"][:6]:
            lines.append(f"  {c['old_text']} -> {c['new_text']}   ({c['deck']}, {c.get('where') or 'slide ' + str(c['slide'])})")
        if len(view["changes"]) > 6:
            lines.append(f"  and {len(view['changes']) - 6} more")
        if view.get("held"):
            lines.append(f"{len(view['held'])} held for you")
        lines.append("Nothing has changed yet. A backup of every replaced file is kept.")
    flags = [f for f in view.get("flags", []) if f["severity"] in ("high", "medium")]
    if flags and not view.get("created") and not view.get("edited_page"):
        lines.append(f"{len(flags)} sentence{'s' if len(flags) != 1 else ''} to read before you approve:")
        for f in flags[:4]:
            lines.append(f"  [{f['severity']}] {f['summary']}")
            lines.append(f"      now reads: {f['sentence_after'][:140]}")
        if len(flags) > 4:
            lines.append(f"  and {len(flags) - 4} more")
    lines.append(f"Fingerprint {view['digest'][:12]}; your answer applies to exactly this release.")
    return chr(10).join(lines)


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
            needs_ack = bool(view.get("needs_acknowledgement"))
            approve_label = APPROVE_SEEN if needs_ack else APPROVE
            choice = ask_choice(_card(view), [approve_label, CANCEL])
            if choice != approve_label:
                return "Nothing was changed." if choice == CANCEL else "No answer was given; nothing was changed."
            svc.approve_and_publish(pid, rid, view["digest"], principal=principal, channel=str(getattr(platform, "value", platform) or "local"), acknowledge=needs_ack)
            if view.get("created"):
                return f"Created {view['changes'][0]['deck']}. Every figure in it is tied to its source; Restore removes it."
            if view.get("edited_page"):
                return f"Wrote your edits to {view['changes'][0]['deck']}. A backup of the replaced file is kept."
            return f"Published {len(view['changes'])} number(s). A backup of each replaced file is kept."
        except ServiceError as exc:
            return f"Not published: {exc}"

    return handler


def make_watch_command(service_factory: Callable[[], Service]) -> Callable[..., str]:
    """Print what to save and run to have Hermes cron check a project on a schedule. It changes nothing itself."""

    def handler(raw_args: str, **_: Any) -> str:
        arg = (raw_args or "").strip()
        if not arg:
            return "Usage: /workroom-watch <project>"
        try:
            pid = service_factory()._resolve(arg)
        except ServiceError as exc:
            return str(exc)
        name = f"workroom-watch-{pid}.py"
        body = chr(10).join([
            "import os, runpy, sys",
            f'sys.argv = ["watch.py", "--project", "{pid}"]',
            'runpy.run_path(os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "plugins", "workroom", "scripts", "watch.py"), run_name="__main__")',
        ])
        return chr(10).join([
            f"To have Hermes check project {pid} on a schedule, save this as ~/.hermes/scripts/{name}:",
            "",
            body,
            "",
            "then run:",
            f'  hermes cron create "every 6h" --no-agent --script {name} --deliver origin --name workroom-watch',
            "",
            "No model is involved. Each run prepares at most one release when a source changed and says nothing otherwise; it never approves or publishes.",
        ])

    return handler
