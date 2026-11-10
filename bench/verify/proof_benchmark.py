"""How well figure proof tells sourced from unsourced figures, on real reports, judged by an independent reader (no model needed).

    python proof_benchmark.py <result.json> <verdicts.json> <workbooks folder> <out.json>

Evidence is the text and cell values of the department's own workbooks (what an agent would have read). Each figure the independent reader judged is checked
in its own paragraph. Truth: the reader found a source cell (correct, candidate_correct, second_correct, other_cell_correct, source_exists) or found none
(no_source). Reported: how many figures with a source are marked sourced or calculated, and how many without a source are marked unsourced.
"""

import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from workroom.workroom_core.figure_proof import Evidence, build_index, check_text, evidence_text_of_file  # noqa: E402

HAS_SOURCE = {"correct", "candidate_correct", "second_correct", "other_cell_correct", "source_exists"}


def main() -> None:
    result, verdicts, folder, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    res = json.loads(result.read_text(encoding="utf-8"))
    rows = {r["i"]: r for r in res["rows"]}
    items = []
    for i, name in enumerate(res["workbooks"], 1):
        items.append(Evidence(i, "read_file", name, 0.0, evidence_text_of_file(folder / name)))
    t_index = time.time()
    index = build_index(items)
    index_seconds = round(time.time() - t_index, 1)
    table: collections.Counter = collections.Counter()
    misses = []
    t0 = time.time()
    checked = 0
    for kind, vs in json.loads(verdicts.read_text(encoding="utf-8")).items():
        for v in vs:
            if v["verdict"] == "wrong":
                continue  # the matcher's error class, not a statement about whether a source exists
            r = rows[v["id"]]
            para = (r["context"] or [""])[0]
            proofs = [p for p in check_text(para, index, context=" ".join(x for x in (r.get("row_head"), r.get("col_head")) + tuple((r["context"] or [""])[1:]) if x)) if p.raw == r["figure"]]
            state = proofs[0].state if proofs else "not read as a figure"
            truth = "has source" if v["verdict"] in HAS_SOURCE else "no source"
            table[(truth, state)] += 1
            checked += 1
            if (truth == "has source" and state not in ("sourced", "calculated")) or (truth == "no source" and state in ("sourced", "calculated")):
                misses.append({"truth": truth, "state": state, "figure": r["figure"], "paragraph": para[:160], "weak": bool(proofs and proofs[0].weak)})
    secs = time.time() - t0
    has = sum(n for (t, _s), n in table.items() if t == "has source")
    has_ok = sum(n for (t, s), n in table.items() if t == "has source" and s in ("sourced", "calculated"))
    none = sum(n for (t, _s), n in table.items() if t == "no source")
    none_ok = sum(n for (t, s), n in table.items() if t == "no source" and s in ("unsourced", "value only"))
    weak_false = sum(1 for m in misses if m["truth"] == "no source" and m["weak"])
    report = {"report": res["report"], "checked": checked, "seconds": round(secs, 1), "index_seconds": index_seconds, "evidence_chars": sum(len(e.text) for e in items), "table": {f"{t} -> {s}": n for (t, s), n in sorted(table.items())},
              "with_source_marked_sourced": f"{has_ok}/{has}", "without_source_marked_unsourced": f"{none_ok}/{none}",
              "false_sourced_that_were_weak_matches": weak_false, "misses": misses[:80]}
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("report", "checked", "seconds", "index_seconds", "evidence_chars", "table", "with_source_marked_sourced", "without_source_marked_unsourced", "false_sourced_that_were_weak_matches")}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
