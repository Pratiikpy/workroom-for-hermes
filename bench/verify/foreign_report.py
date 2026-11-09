"""Print, from the result files only, the figures that the evidence ledger, the README and the audit-readiness report quote for the foreign-document work.

    python foreign_report.py <results folder> <agent runs folder> <perf folder>

Nothing is typed by hand: every number below is computed from a result file, and a missing file is printed as missing, never as zero.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def j(folder: Path, name: str):
    p = folder / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def rows(d):
    return [] if d is None else (d["rows"] if isinstance(d, dict) and "rows" in d else d)


def edit(d):
    if d is None:
        return "missing"
    r = rows(d)
    c = Counter(x["status"] for x in r)
    return {"files": len(r), "edited_and_checked_ok": c["ok"], "failed": c["FAILED"], "skipped": c["skipped"], "original_not_openable": c["original_not_openable"]}


def links(d):
    if d is None:
        return "missing"
    r = [x for x in rows(d) if x.get("status") == "ok"]
    cls: Counter = Counter()
    for x in r:
        cls.update(x["classes"])
    auto = cls["linked_right"] + cls["LINKED_WRONG"] + cls["linked_equivalent"] + cls["unlabelled_ambiguous_linked"]
    return {"documents": len(r), "figures": sum(x["seeds"] for x in r), "automatic_links": auto, "automatic_wrong": cls["LINKED_WRONG"], "classes": dict(cls),
            "updates_checked": sum(x.get("updated", 0) for x in r), "docs_update_ok": sum(1 for x in r if x.get("text_ok")), "docs_update_failed": sum(1 for x in r if x.get("updated") and not x.get("text_ok"))}


def cycles(d):
    if d is None:
        return "missing"
    r = rows(d)
    c = Counter(x["status"] for x in r)
    return {"documents": len(r), "ok": c["ok"], "failed": c["FAILED"], "errors": c["error"], "skipped": c["skipped"]}


def charts(d):
    if d is None:
        return "missing"
    r = [x for x in rows(d) if x["status"] != "skipped"]
    c = Counter(x["status"] for x in r)
    return {"decks_with_charts": len(r), "end_to_end_ok": c["ok"], "failed": c["FAILED"], "errors": c["error"], "no_writable_point_or_none_linked": c["nothing_writable"] + c["measured"],
            "points": sum(x.get("points", 0) for x in r), "linked": sum(x.get("chart_links", 0) for x in r), "accepted_right": sum(x.get("accepted_right", 0) for x in r),
            "accepted_wrong": sum(x.get("accepted_WRONG", 0) for x in r), "proposed": sum(x.get("proposed", 0) for x in r),
            "changed_points_read_back": sum(x.get("changed_points", 0) for x in r), "points_wrong_in_real_powerpoint": sum(x.get("points_WRONG", 0) for x in r)}


def xlsx(d, only: set[str] | None = None):
    if d is None:
        return "missing"
    r = rows(d)
    if only is not None:
        r = [x for x in r if x["file"] in only]
    ok = [x for x in r if x["status"] == "ok"]
    c = Counter(x["status"] for x in r)
    return {"workbooks": len(r), "compared": len(ok), "excel_refused": c["excel_refused"], "workroom_refused": c["workroom_refused"], "excel_cells": sum(x["excel_cells"] for x in ok),
            "workroom_cells": sum(x["workroom_cells"] for x in ok), "with_missing_cells": sum(1 for x in ok if x["missing"]), "with_extra_cells": sum(1 for x in ok if x["extra"]),
            "with_value_mismatch": sum(1 for x in ok if x["value_mismatch"]), "with_hidden_not_flagged": sum(1 for x in ok if x["hidden_not_flagged"])}


def main() -> None:
    res, agent, perf = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out = {
        "own": {"edit": edit(j(res, "edit_own3.json")), "links_labelled": links(j(res, "ties_own_labelled3.json")), "links_bare": links(j(res, "ties_own_bare3.json")),
                "update_checks": links(j(res, "ties_own_labelled4.json")), "three_cycles_in_real_word": cycles(j(res, "cycles_own2.json"))},
        "public_dev": {"poi_edit": edit(j(res, "edit_poi_dev2.json")), "lo_edit": edit(j(res, "edit_lo_dev2.json")), "charts": charts(j(res, "charts_dev3.json")), "xlsx_vs_excel": xlsx(j(res, "xlsx_poi_dev2.json"))},
        "sealed": {"xlsx_vs_excel": xlsx(j(res, "sealed_xlsx.json")), "poi_edit": edit(j(res, "sealed_edit_poi.json")), "lo_edit": edit(j(res, "sealed_edit_lo.json")), "charts": charts(j(res, "sealed_charts.json")),
                   "poi_links": links(j(res, "sealed_ties_poi.json")), "lo_links": links(j(res, "sealed_ties_lo.json")), "poi_three_cycles": cycles(j(res, "sealed_cycles_poi.json")),
                   "code_commit": (res / "sealed_run_commit.txt").read_text().strip() if (res / "sealed_run_commit.txt").is_file() else "missing"},
        "restructuring_with_real_excel": dict(Counter(x["status"] for x in (j(res, "shift4.json") or []))),
        "performance": {n: j(perf, n + ".json") for n in ("perf_mid", "perf_mid4", "perf_large", "perf_large2")},
        "agent_runs": {},
    }
    for f in sorted(agent.glob("*.report.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        out["agent_runs"][f.name.replace(".report.json", "")] = {"exit": r["exit"], "seconds": r["seconds"], "files_changed": r["files_changed"], "release_waiting": r["release_waiting"], "tools": r["tool_calls"]}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
