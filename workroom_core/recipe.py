"""The reporting recipe: how a model report is built, remembered so that a copy of it is linked to the same sources in one step.

A report that is made every month or every year is rarely written again from nothing: last period's file is copied and its numbers are replaced.
Workroom already keeps, for every figure of a report, where it sits in the document and which cell of the workbook it comes from (a tie, with
the headings of the source cell). The recipe is the owner's approved snapshot of those ties for one model report. It is not a second source of
truth: when a copy of the model is found in the project, the snapshot is turned back into ordinary ties for the copy, and from there the normal
rules apply (a figure is linked only if it is still where the model had it, or has the same words around it; a source that moved is followed
by its headings; anything that does not fit is dropped or asked about, never guessed).

The snapshot is proposed by an agent or the owner and installed only by the owner, bound to its digest, like a release.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .project import Project, Tie

FORMAT = 1
TIE_FIELDS = ("slide", "shape_id", "para", "seg", "offset", "cell_rc", "raw", "src_file", "sheet", "ref", "transform", "linked_value", "label_score",
              "context", "slide_uid", "fp_near", "kind", "chart", "formula", "src_labels")
STATES_THAT_COUNT = ("accepted", "confirmed")


class RecipeError(Exception):
    """The recipe cannot be made, installed or applied as asked."""


def ensure_tables(project: Project) -> None:
    project.db.execute(
        "CREATE TABLE IF NOT EXISTS recipe_versions (version INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, approver TEXT, digest TEXT, active INT, doc TEXT)"
    )


def digest_of(doc: dict[str, Any]) -> str:
    body = {k: v for k, v in doc.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _rule(t: Tie) -> dict[str, Any]:
    return {
        "slide": t.slide, "shape_id": t.shape_id, "para": t.para, "seg": t.seg, "offset": t.offset, "cell_rc": list(t.cell_rc) if t.cell_rc else None,
        "raw": t.raw, "src_file": t.src_file, "sheet": t.sheet, "ref": t.ref, "transform": t.transform, "linked_value": t.linked_value,
        "label_score": t.label_score, "context": t.context, "slide_uid": t.slide_uid, "fp_near": t.fp_near, "kind": t.kind, "chart": t.chart,
        "formula": t.formula, "src_labels": t.src_labels,
    }


def propose(project: Project, deck: str) -> dict[str, Any]:
    """Snapshot the links of one model report (those that are accepted or confirmed). Changes nothing."""
    ties = [t for t in project.ties() if t.deck == deck and t.kind != "scene"]
    if not ties:
        raise RecipeError(f"{deck} has no links yet; find its links first, then make it the model")
    kept = [t for t in ties if t.state in STATES_THAT_COUNT]
    if not kept:
        raise RecipeError(f"none of the {len(ties)} links in {deck} is accepted or confirmed yet; confirm the ones that are right first")
    doc: dict[str, Any] = {
        "format": FORMAT, "model": deck, "model_sha": hashlib.sha256((project.root / deck).read_bytes()).hexdigest() if (project.root / deck).is_file() else "",
        "rules": [_rule(t) for t in kept],
        "left_out": {s: sum(1 for t in ties if t.state == s) for s in sorted({t.state for t in ties} - set(STATES_THAT_COUNT))},
        "sources": sorted({t.src_file for t in kept}),
    }
    doc["digest"] = digest_of(doc)
    return doc


def install(project: Project, doc: dict[str, Any], approver: str) -> dict[str, Any]:
    """Owner route: make the proposed snapshot the active recipe. Refused if it was altered or its model report changed since it was proposed."""
    ensure_tables(project)
    if doc.get("format") != FORMAT or digest_of(doc) != doc.get("digest"):
        raise RecipeError("this recipe does not match its digest")
    path = project.root / doc["model"]
    if not path.is_file():
        raise RecipeError(f"the model report {doc['model']} is not in the project")
    if doc.get("model_sha") and hashlib.sha256(path.read_bytes()).hexdigest() != doc["model_sha"]:
        raise RecipeError(f"{doc['model']} changed since this recipe was proposed; propose it again")
    with project._transaction():
        project.db.execute("UPDATE recipe_versions SET active=0")
        cur = project.db.execute("INSERT INTO recipe_versions (created, approver, digest, active, doc) VALUES (?,?,?,1,?)",
                                 (time.time(), approver, doc["digest"], json.dumps(doc, ensure_ascii=False)))
    return {"version": cur.lastrowid, "digest": doc["digest"], "model": doc["model"], "rules": len(doc["rules"])}


def revoke(project: Project) -> None:
    ensure_tables(project)
    project.db.execute("UPDATE recipe_versions SET active=0")


def current(project: Project) -> dict[str, Any] | None:
    ensure_tables(project)
    row = project.db.execute("SELECT version, created, approver, digest, doc FROM recipe_versions WHERE active=1 ORDER BY version DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {"version": row[0], "approved_at": row[1], "approver": row[2], "digest": row[3], "doc": json.loads(row[4])}


def history(project: Project) -> list[dict[str, Any]]:
    ensure_tables(project)
    return [{"version": v, "approved_at": c, "approver": a, "digest": d, "active": bool(act)}
            for v, c, a, d, act in project.db.execute("SELECT version, created, approver, digest, active FROM recipe_versions ORDER BY version")]


def carry(project: Project, deck: str) -> int:
    """If an active recipe exists and ``deck`` has no links yet, give it the model's links as ordinary links. Returns how many were made.

    Only a document of the same kind as the model is used (a Word report never takes a PowerPoint model's links), and never the model itself."""
    active = current(project)
    if active is None:
        return 0
    model = active["doc"]["model"]
    if deck == model or project.db.execute("SELECT COUNT(*) FROM ties WHERE deck=?", (deck,)).fetchone()[0]:
        return 0
    if deck.rsplit(".", 1)[-1].lower() != model.rsplit(".", 1)[-1].lower():
        return 0
    made = 0
    with project._transaction():
        for r in active["doc"]["rules"]:
            project.db.execute(
                "INSERT INTO ties (deck, slide, shape_id, para, seg, offset, cell_rc, raw, state, src_file, sheet, ref, transform, linked_value, label_score, context,"
                " slide_uid, fp_near, anchor, basis, receipt, kind, chart, formula, src_labels, intent_labels) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (deck, r["slide"], r["shape_id"], r["para"], r["seg"], r["offset"], json.dumps(r["cell_rc"]), r["raw"], "accepted", r["src_file"], r["sheet"], r["ref"],
                 r["transform"], r["linked_value"], r["label_score"], r["context"], r["slide_uid"], r["fp_near"], "exact", "matched" if r["kind"] == "chart" else "recipe", "", r["kind"], r["chart"],
                 r["formula"], r["src_labels"], r["src_labels"]),
            )
            made += 1
    return made
