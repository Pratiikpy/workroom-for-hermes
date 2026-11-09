"""Run Workroom once, blind, on a report and its workbooks and write every decision to a file for adjudication.

    python holdout_run.py <report.docx|pptx> <out.json> <workbook.xlsx> [<workbook.xlsx> ...]

The files are copied into a fresh project folder; the originals are never touched. The same functions the product runs are called, so every figure the
document holds gets a recorded decision (accept, confirm, coincidence, none), not only the ones stored as links. Samples for the human and independent
adjudication are drawn with a fixed seed written down in the protocol, before the run.
"""

import json
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core.match.engine import Mention, is_coincidence, match_mentions  # noqa: E402
from workroom.workroom_core.match.tables import align_tables  # noqa: E402
from workroom.workroom_core.ooxml.package import open_package  # noqa: E402,F401
from workroom.workroom_core.project import open_document  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

SEED = 20261109
SAMPLES = {"accept": 120, "confirm": 60, "none": 80, "coincidence": 40}


def decide(r, in_table: bool = False) -> str:
    if r.decision == "confirm" and r.best is not None and is_coincidence(r.best.label_score, r.mention.number.raw, in_table):
        return "coincidence"
    return r.decision


def view(i, dm, r) -> dict:
    b, u = r.best, r.runner_up
    return {
        "i": i, "figure": dm.number.raw, "context": list(dm.context), "table": dm.table, "row_head": dm.row_head, "col_head": dm.col_head,
        "decision": decide(r, dm.cell is not None), "reason": r.reason, "section": dm.section,
        "candidates": [{"cell": f"{c.cell.sheet}!{c.cell.ref}", "v": c.cell.value, "ls": round(c.label_score, 2), "sec": c.in_section, "score": round(c.score, 2)} for c in r.candidates[:5]],
        "best": None if b is None else {"cell": f"{b.cell.file} {b.cell.sheet}!{b.cell.ref}", "value": b.cell.value, "row": list(b.cell.row_labels), "col": list(b.cell.col_labels),
                                        "label_score": round(b.label_score, 3), "transform": b.transform},
        "runner_up": None if u is None else {"cell": f"{u.cell.file} {u.cell.sheet}!{u.cell.ref}", "value": u.cell.value, "row": list(u.cell.row_labels), "col": list(u.cell.col_labels)},
    }


def main() -> None:
    report, out, books = Path(sys.argv[1]), Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]]
    tmp = Path(tempfile.mkdtemp(prefix="holdout_"))
    root = tmp / "project"
    root.mkdir()
    for p in [report, *books]:
        shutil.copy2(p, root / p.name)
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    proj, _ = svc._open(pid)  # the same project object the product uses
    t0 = time.time()
    index = proj.source_index()
    deck = open_document((root / report.name).read_bytes(), report.name)
    dms = list(deck.mentions())
    results = match_mentions([Mention(str(i), dm.number, dm.context, (dm.para_offset, dm.para_offset + len(dm.number.raw)) if dm.para_offset is not None else None, dm.section, dm.row_head) for i, dm in enumerate(dms)], index)
    results = align_tables(dms, results, index)
    rows = [view(i, dm, r) for i, (dm, r) in enumerate(zip(dms, results))]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    rng = random.Random(SEED)
    sample: dict[str, list[int]] = {}
    for kind, cap in SAMPLES.items():
        ids = [row["i"] for row in rows if row["decision"] == kind]
        sample[kind] = sorted(ids if len(ids) <= cap else rng.sample(ids, cap))
    result = {
        "report": report.name, "workbooks": [b.name for b in books], "seed": SEED, "seconds": round(time.time() - t0, 1),
        "figures": len(rows), "counts": counts, "sample_ids": sample, "rows": rows,
        "source_cells": len(index.cells),
    }
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"figures": len(rows), "counts": counts, "source_cells": len(index.cells), "seconds": result["seconds"], "sampled": {k: len(v) for k, v in sample.items()}}, indent=1))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
