"""Unattended watch for a Hermes cron script job: stage ONE release when a source changed, and say nothing otherwise.

    python watch.py --project <id or folder> [--data-dir <Workroom data dir>]

It only prepares a release (nothing in your folders changes) and prints where to approve it. It never approves or publishes.
Schedule it with Hermes cron as a no-agent script job so no model is involved.
"""

import argparse
import os
import sys
from pathlib import Path


def _service(data_dir: str | None):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root.parent))
    from importlib import import_module

    service = import_module(f"{root.name}.workroom_core.service")
    if data_dir:
        folder = Path(data_dir)
    elif os.environ.get("WORKROOM_DATA_DIR"):
        folder = Path(os.environ["WORKROOM_DATA_DIR"])
    else:
        from plugins.plugin_storage import plugin_data_dir  # available inside Hermes

        folder = plugin_data_dir("workroom")
    return service.Service(folder), service.ServiceError


def _receipt(svc, args, outcome: str, detail: str) -> None:
    try:
        svc.watch_receipt(args.project, outcome, detail, args.every)
    except Exception:  # noqa: BLE001  the receipt is a record of the run, never a reason for the run to fail
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage a Workroom release when sources changed.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-dir")
    ap.add_argument("--every", type=float, default=0, help="how often the job is scheduled, in hours, so a missed run can be noticed")
    args = ap.parse_args(argv)
    try:
        svc, error = _service(args.data_dir)
        try:
            inbox = svc.changes_inbox(args.project)
            auto = [(c, e) for c in inbox["changes"] for e in c["elements"] if e["decision"] == "auto"]
            if not auto:
                _receipt(svc, args, "ok", "")
                if inbox["blocked"]:
                    print(f"Workroom: {len(inbox['blocked'])} linked number(s) have a missing source and need you. Open Workroom to review.")
                return 0
            pid = svc._resolve(args.project)
            waiting = svc.awaiting(pid)
            if waiting:
                _receipt(svc, args, "prepared", "a release was already waiting")
                print(f"Workroom: sources changed, and release {waiting[0]['release_id'][:8]} is already waiting for your approval.")
                return 0
            staged = svc.stage(pid)
        except error as exc:
            _receipt(svc, args, "failed", str(exc))
            print(f"Workroom could not check {args.project}: {exc}")
            return 1
    except Exception as exc:  # noqa: BLE001  a scheduled job must report, never crash silently
        try:
            _receipt(svc, args, "failed", f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001
            pass
        print(f"Workroom could not check {args.project}: {type(exc).__name__}: {exc}")
        return 1
    _receipt(svc, args, "prepared", f"release {staged['release_id'][:8]}")
    lines = [f"Workroom: {len(staged['changes'])} number(s) changed in your sources and release {staged['release_id'][:8]} is waiting for your approval."]
    for c in staged["changes"][:6]:
        lines.append(f"  {c['old_text']} -> {c['new_text']}   ({c['deck']}, {c.get('where') or 'slide ' + str(c['slide'])})")
    if len(staged["changes"]) > 6:
        lines.append(f"  and {len(staged['changes']) - 6} more")
    lines.append("Nothing has been changed. Approve it in the Workroom screen, or reply /workroom-approve in a chat.")
    print(chr(10).join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
