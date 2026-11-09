"""Two reporting cycles with a recipe, scored against what the department really published.

    python recipe_cycle.py <report_y1.docx> <workbook_y1.xlsx> <report_y2_official.docx> <workbook_y2.xlsx> <out.json>

Cycle 1: the year-1 report and its workbook; the owner makes the report the model (the recipe).
Cycle 2: the workbook file is replaced by the year-2 data under the same name, and a copy of the year-1 report is added. Workroom links the copy with
the recipe, one release updates it, and every updated figure is compared with the figure the department published in its year-2 report at the
same place (same section, same row heading, same column position). The year-2 report is the oracle; Workroom never reads it.
"""

import collections
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402
from workroom.workroom_core.service import NeedsAcknowledgement, Service  # noqa: E402

DOTTED = re.compile(r"(?<![\d.])\d+(?:\.\d+)+(?![\d.])")


def norm(text: str) -> str:
    """A heading as a key: footnote marks and punctuation dropped, digits kept, so "Balance at 30 June 2025" and "... 2024" stay different rows."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", "", text.lower())).strip()


def figures(docx: Path, by_head: bool = False) -> dict[tuple, str]:
    """Every figure of a Word report keyed by (section, row heading, column position or column heading, nth), so two years can be laid side by side.
    Keyed by column heading, a table whose columns were reordered or regrouped between the years still lines up."""
    out: dict[tuple, str] = {}
    seen: collections.Counter = collections.Counter()
    for dm in Doc(docx.read_bytes()).mentions():
        if dm.cell is None or not dm.row_head:
            continue
        ids = DOTTED.findall(dm.section)
        key = (ids[0] if ids else norm(dm.section), norm(dm.row_head), norm(dm.col_head) if by_head else dm.cell[1])
        n = seen[key]
        seen[key] += 1
        out[key + (n,)] = dm.number.raw
    return out


def main() -> None:
    y1_doc, y1_book, y2_doc, y2_book, out = (Path(a) for a in sys.argv[1:6])
    tmp = Path(tempfile.mkdtemp(prefix="cycle_"))
    root = tmp / "project"
    root.mkdir()
    shutil.copy2(y1_doc, root / "statements_y1.docx")
    shutil.copy2(y1_book, root / "data.xlsx")
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    result: dict = {}
    t0 = time.time()
    first = svc.discover(pid)
    result["cycle1"] = {"seconds": round(time.time() - t0, 1), "figures": first["numbers_found"], "accepted": first["accepted"],
                        "asked": len(first["need_confirmation"]), "listed_apart": len(first["coincidences"]), "no_source": first["no_source"]}
    proposed = svc.recipe_propose(pid, "statements_y1.docx")
    svc.recipe_approve(pid, proposed["proposal"], proposed["digest"])
    result["recipe"] = {"links": proposed["links"], "left_out": proposed["left_out"], "sources": proposed["sources"]}

    # cycle 2: the owner drops the new data over the old file and copies last year's report
    shutil.copy2(y2_book, root / "data.xlsx")
    (tmp / "archive").mkdir()
    shutil.copy2(root / "statements_y1.docx", root / "statements_y2.docx")
    shutil.move(str(root / "statements_y1.docx"), str(tmp / "archive" / "statements_y1.docx"))  # last year's file is put away; the recipe remembers how it was built
    t0 = time.time()
    second = svc.discover(pid)
    ties = svc.ties(pid)
    copy_ties = [t for t in ties if t["deck"] == "statements_y2.docx"]
    states = collections.Counter(t["state"] for t in copy_ties)
    result["cycle2"] = {"seconds": round(time.time() - t0, 1), "copy_links_by_state": dict(states), "all_decks_accepted": second["accepted"],
                        "asked_in_project": len(second["need_confirmation"]), "listed_apart": len(second["coincidences"])}
    try:
        staged = svc.stage_rollforward(pid, 1, window=True)
    except Exception as exc:  # noqa: BLE001
        import traceback

        result["cycle2"]["roll_forward_refused"] = str(exc)[:400]
        result["cycle2"]["trace"] = traceback.format_exc()[-900:]
        staged = {}
    result["cycle2"]["planned_changes"] = len(staged.get("changes", []))
    result["cycle2"]["figures_rolled"] = staged.get("figures")
    result["cycle2"]["held_back"] = staged.get("held") if isinstance(staged.get("held"), int) else len(staged.get("held") or [])
    result["cycle2"]["stage_state"] = staged.get("state")
    result["cycle2"]["restated"] = len(staged.get("restated", []))
    result["restated_examples"] = staged.get("restated", [])
    result["cycle2"]["flags"] = [f["kind"] for f in staged.get("flags", [])]
    if staged.get("state") == "awaiting_approval":
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    # figures whose source headings carry no period are followed by their address, so after the roll one ordinary refresh brings them up to date
    try:
        svc.discover(pid)
        second = svc.stage(pid)
        result["cycle2"]["refresh_after_roll"] = {"changes": len(second.get("changes", [])), "state": second.get("state"), "blocked": len(second.get("blocked", []))}
        if second.get("state") == "awaiting_approval":
            try:
                svc.approve_and_publish(pid, second["release_id"], second["digest"])
            except NeedsAcknowledgement:
                svc.approve_and_publish(pid, second["release_id"], second["digest"], acknowledge=True)
    except Exception as exc:  # noqa: BLE001
        result["cycle2"]["refresh_after_roll"] = {"refused": str(exc)[:300]}
    # score the copy against the department's own year-2 report
    before = figures(tmp / "archive" / "statements_y1.docx")
    after = figures(root / "statements_y2.docx")
    official = figures(y2_doc)
    changed = {k: (before[k], v) for k, v in after.items() if k in before and before[k] != v}
    scored = collections.Counter()
    wrong = []
    for k, (old, new) in changed.items():
        if k not in official:
            scored["changed, no counterpart in the official report"] += 1
        elif official[k] == new:
            scored["changed to the official figure"] += 1
        else:
            scored["changed to something else"] += 1
            wrong.append({"key": list(map(str, k)), "old": old, "new": new, "official": official[k]})
    should = {k for k in before if k in official and before[k] != official[k]}
    result["score"] = {
        "figures_changed_by_the_release": len(changed), "outcomes": dict(scored),
        "figures_that_differ_between_the_two_official_years_at_comparable_places": len(should),
        "of_those_updated_to_the_official_figure": sum(1 for k in should if after.get(k) == official[k]),
        "of_those_left_as_last_year": sum(1 for k in should if after.get(k) == before[k]),
    }
    result["wrong_examples"] = wrong[:400]
    from oracle_groups import figures_grouped

    g_before, g_after, g_official = (figures_grouped(tmp / "archive" / "statements_y1.docx", True), figures_grouped(root / "statements_y2.docx", True), figures_grouped(y2_doc, True))
    grouped = collections.Counter()
    grouped_wrong = []
    for k, v in g_after.items():
        if k in g_before and g_before[k] != v:
            if k not in g_official:
                grouped["changed, no counterpart in the official report"] += 1
            elif g_official[k] == v:
                grouped["changed to the official figure"] += 1
            else:
                grouped["changed to something else"] += 1
                grouped_wrong.append({"key": list(map(str, k)), "old": g_before[k], "new": v, "official": g_official[k]})
    g_should = {k for k in g_before if k in g_official and g_before[k] != g_official[k]}
    result["score_by_group_heading"] = {"outcomes": dict(grouped), "figures_that_differ_between_the_two_official_years": len(g_should),
                                        "of_those_updated_to_the_official_figure": sum(1 for k in g_should if g_after.get(k) == g_official[k]),
                                        "of_those_left_as_last_year": sum(1 for k in g_should if g_after.get(k) == g_before[k])}
    result["grouped_wrong_examples"] = grouped_wrong[:60]
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("cycle1", "recipe", "cycle2", "score", "score_by_group_heading")}, indent=1, ensure_ascii=False))
    if os.environ.get("KEEP_PROJECT"):
        print("kept project at", tmp, file=sys.stderr)
    else:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
