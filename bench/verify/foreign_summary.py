"""Turn the result files of the foreign-document harnesses into the counts quoted in the evidence ledger and the README.

    python foreign_summary.py <folder holding the result json files> [--seal foreign_seal_poi.json]

Every number printed comes from a result file; nothing is typed by hand. File names of the user's own documents are not repeated.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def load(folder: Path, name: str):
    p = folder / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def rows_of(d):
    if d is None:
        return []
    return d["rows"] if isinstance(d, dict) and "rows" in d else d


def edit(d) -> dict:
    rows = rows_of(d)
    c = Counter(r["status"] for r in rows)
    return {"files": len(rows), "edited_and_checked_ok": c["ok"], "failed": c["FAILED"], "skipped_no_number_or_refused": c["skipped"], "original_not_openable": c["original_not_openable"],
            "docx_ok": sum(1 for r in rows if r["status"] == "ok" and r["kind"] == ".docx"), "pptx_ok": sum(1 for r in rows if r["status"] == "ok" and r["kind"] == ".pptx")}


def ties(d) -> dict:
    rows = [r for r in rows_of(d) if r.get("status") == "ok"]
    classes: Counter = Counter()
    for r in rows:
        classes.update(r["classes"])
    seeds = sum(r["seeds"] for r in rows)
    return {"documents_measured": len(rows), "figures": seeds, "classes": dict(classes), "updates_checked": sum(r.get("updated", 0) for r in rows),
            "documents_update_ok": sum(1 for r in rows if r.get("text_ok")), "documents_update_failed": sum(1 for r in rows if r.get("updated") and not r.get("text_ok"))}


def cycles(d) -> dict:
    rows = rows_of(d)
    c = Counter(r["status"] for r in rows)
    return {"documents": len(rows), "ok": c["ok"], "failed": c["FAILED"], "errors": c["error"], "skipped": c["skipped"]}


def charts(d) -> dict:
    rows = [r for r in rows_of(d) if r["status"] != "skipped"]
    c = Counter(r["status"] for r in rows)
    return {"decks_with_charts": len(rows), "end_to_end_ok": c["ok"], "failed": c["FAILED"], "errors": c["error"], "no_writable_point": c["nothing_writable"] + c["measured"],
            "chart_points": sum(r.get("points", 0) for r in rows), "linked": sum(r.get("chart_links", 0) for r in rows), "accepted_right": sum(r.get("accepted_right", 0) for r in rows),
            "accepted_wrong": sum(r.get("accepted_WRONG", 0) for r in rows), "proposed_to_owner": sum(r.get("proposed", 0) for r in rows),
            "changed_points_checked": sum(r.get("changed_points", 0) for r in rows), "points_wrong_in_real_powerpoint": sum(r.get("points_WRONG", 0) for r in rows)}


def xlsx(d, dev: set[str] | None) -> dict:
    rows = rows_of(d)
    if dev is not None:
        rows = [r for r in rows if r["file"] in dev]
    ok = [r for r in rows if r["status"] == "ok"]
    c = Counter(r["status"] for r in rows)
    return {"workbooks": len(rows), "compared_with_excel": len(ok), "excel_refused": c["excel_refused"], "workroom_refused": c["workroom_refused"],
            "cells_excel_reports": sum(r["excel_cells"] for r in ok), "cells_workroom_indexed": sum(r["workroom_cells"] for r in ok),
            "workbooks_with_missing_cells": sum(1 for r in ok if r["missing"]), "workbooks_with_extra_cells": sum(1 for r in ok if r["extra"]),
            "workbooks_with_value_mismatch": sum(1 for r in ok if r["value_mismatch"]), "workbooks_with_hidden_not_flagged": sum(1 for r in ok if r["hidden_not_flagged"]),
            "cells_value_compared": sum(r["compared"] for r in ok)}


def main() -> None:
    folder = Path(sys.argv[1])
    seal = None
    if "--seal" in sys.argv:
        s = json.loads(Path(sys.argv[sys.argv.index("--seal") + 1]).read_text(encoding="utf-8"))
        seal = {"dev": {r["file"].split("/")[-1] for r in s["files"] if r["set"] == "dev"}, "sealed": {r["file"].split("/")[-1] for r in s["files"] if r["set"] == "sealed"}}
    out = {
        "own_documents": {"edit": edit(load(folder, "edit_own2.json")), "links_labelled": ties(load(folder, "ties_own_labelled2.json")), "links_bare": ties(load(folder, "ties_own_bare2.json")), "three_cycles_with_a_person_in_word": cycles(load(folder, "cycles_own.json"))},
        "public_dev": {"poi_edit": edit(load(folder, "edit_poi_dev2.json")), "lo_edit": edit(load(folder, "edit_lo_dev2.json")), "poi_links": ties(load(folder, "ties_poi_dev.json")), "lo_links": ties(load(folder, "ties_lo_dev.json")),
                       "poi_three_cycles": cycles(load(folder, "cycles_poi_dev.json")), "charts": charts(load(folder, "charts_dev3.json"))},
        "excel": {"poi_dev_workbooks_vs_excel": xlsx(load(folder, "xlsx_poi_dev2.json"), seal["dev"] if seal else None), "own_workbooks_vs_excel": xlsx(load(folder, "xlsx_own2.json"), None)},
        "restructuring_with_real_excel": Counter(r["status"] for r in (load(folder, "shift4.json") or [])),
    }
    print(json.dumps(out, indent=1, default=dict))


if __name__ == "__main__":
    main()
