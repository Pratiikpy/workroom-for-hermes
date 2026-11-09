"""The release dossier: one readable record of a published release, built only from what Workroom itself recorded.

It lists what changed (every figure, old and new, with its source cell), the files before and after (by hash), which checks ran, which found something
and which could not run, what was held back, who approved it and through which channel, and how to restore it. Nothing in it is written by a model.

What it is not: tamper-proof. The record, and the key that signs Workroom's history, sit on the machine of the person whose agent runs beside Workroom.
A dossier lets a reader check a release against the files and the history; it cannot prove that this history was not rewritten by someone with that
person's access. The dossier says so in its last section.
"""

from __future__ import annotations

import time
from typing import Any

MAX_CHANGES = 400


def _when(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + time.strftime(" %z", time.localtime(ts)) if ts else "not recorded"


def build(project_name: str, release_id: str, meta: dict[str, Any], times: dict[str, float | None], approval: dict[str, Any], digest: str, staged: list[dict[str, Any]],
          restored_at: float | None) -> dict[str, Any]:
    """The facts, as data: used for the readable text and for anything that wants them without reading prose."""
    flags = meta.get("flags", []) or []
    coverage = meta.get("coverage", {}) or {}
    changes = meta.get("changes", []) or []
    return {
        "project": project_name, "release": release_id, "digest": digest,
        "approved_by": approval.get("principal", ""), "channel": approval.get("channel", ""), "published_at": times.get("PUBLISHED"), "staged_at": times.get("STAGED"),
        "verified_at": times.get("VERIFIED"), "approved_at": times.get("APPROVED"), "restored_at": restored_at,
        "created": bool(meta.get("created")), "rolled": bool(meta.get("rolled")),
        "changes": changes[:MAX_CHANGES], "changes_total": len(changes),
        "files": [{"file": c.get("rel_path", ""), "before": c.get("base_sha") or "", "after": c.get("new_sha") or ""} for c in staged],
        "checks": {
            "ran": ["Each rewritten document parsed again and was found to contain every new figure.",
                    *([f"{coverage['sentences_checked']} sentences around the changed figures were read for claims the update makes false."] if coverage.get("sentences_checked") else [])],
            "found": [{"kind": f.get("kind"), "where": f.get("where"), "said": f.get("what") or f.get("title") or f.get("summary") or "", "decision": f.get("decision") or ""} for f in flags],
            "could_not_run": coverage.get("not_checked", []) if isinstance(coverage.get("not_checked"), list) else [],
        },
        "held": meta.get("held", []) or [], "blocked": meta.get("blocked", []) or [], "notes": meta.get("notes", []) or [],
        "restated": (meta.get("rolled") or {}).get("restated", []) or [], "nil_cells": meta.get("nil_cells", []) or [],
    }


def text(d: dict[str, Any]) -> str:
    out = [f"# Release {d['release']} of {d['project']}", ""]
    out += [f"- Published: {_when(d['published_at'])} (prepared {_when(d['staged_at'])}, checked {_when(d['verified_at'])})",
            f"- Approved by: {d['approved_by'] or 'not recorded'} through {d['channel'] or 'an unrecorded channel'} at {_when(d['approved_at'])}, for exactly the changes below (fingerprint {d['digest'][:16] or 'not recorded'})",
            f"- Kind: {'a new file Workroom created' if d['created'] else 'a roll to the next period' if d['rolled'] else 'an update of linked figures'}"]
    if d["restored_at"]:
        out.append(f"- Restored: {_when(d['restored_at'])}")
    out += ["", "## What changed", ""]
    if not d["changes"]:
        out.append("No figure changed (a created file, or nothing recorded).")
    for c in d["changes"]:
        old, new = c.get("old_text", ""), c.get("new_text", "")
        out.append(f"- {c.get('deck', '')}, {c.get('where') or 'slide ' + str(c.get('slide', ''))}: {old} -> {new} (from {c.get('src', '')}: {c.get('old_value', '')} -> {c.get('new_value', '')})")
    if d["changes_total"] > len(d["changes"]):
        out.append(f"- and {d['changes_total'] - len(d['changes'])} more")
    out += ["", "## Files (SHA-256)", ""]
    for f in d["files"]:
        out.append(f"- {f['file']}: before {f['before'][:16] or 'did not exist'}, after {f['after'][:16]}")
    out += ["", "## Checks", "", "Ran:"] + [f"- {x}" for x in d["checks"]["ran"]]
    out += ["", "Found something:"] + ([f"- {x['kind']}: {x['said']} ({x['where']}); decision: {x['decision'] or 'none recorded'}" for x in d["checks"]["found"]] or ["- Nothing."])
    out += ["", "Could not run:"] + ([f"- {x}" for x in d["checks"]["could_not_run"]] or ["- Nothing was recorded as unchecked."])
    out += ["", "## Left alone", ""]
    out += [f"- Held for you: {x}" for x in d["held"]] + [f"- Blocked, would have mixed old and new numbers: {x}" for x in d["blocked"]]
    if not d["held"] and not d["blocked"]:
        out.append("- Nothing was held back.")
    if d["notes"]:
        out += ["", "## Sources that moved", ""] + [f"- {x}" for x in d["notes"]]
    if d["restated"]:
        out += ["", "## Figures for a period the report already showed, now different", ""] + [f"- {x}" for x in d["restated"]]
    if d["nil_cells"]:
        out += ["", "## Dashes that may now hold a figure (not changed)", ""] + [f"- {x}" for x in d["nil_cells"]]
    out += ["", "## Restoring", "",
            "Workroom keeps a backup of every file this release replaced. Restore puts them back as they were, and is refused when you have worked in those files since, so later work is never overwritten.",
            "", "## What this record does not prove", "",
            "It is written from Workroom's own history on this computer. It lets you check a release against the files and the history, but anyone who can act as you on this machine could also have rewritten that history, so it is evidence for you, not a signed statement a third party can rely on."]
    return "\n".join(out) + "\n"
