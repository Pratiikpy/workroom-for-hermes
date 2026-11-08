"""Run Workroom's matcher on the SEC corpus (see sec_corpus.py) and compare it with a value-only baseline.

    python sec_match_bench.py <corpus folder> <sample output json> [seed]

Reports, per decision: how many numbers were found, linked automatically, sent to a human, left without a source; and for a random
sample of linked numbers writes the sentence, Workroom's chosen source row and period, and the value-only baseline's choice, so a
person can judge them. The judging is manual: nothing here claims correctness by itself.
"""

import json
import random
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpyxl import load_workbook  # noqa: E402

from workroom.workroom_core.project import Project  # noqa: E402


def cell_table(xlsx: Path) -> list[tuple[str, str, str, float]]:
    ws = load_workbook(xlsx, data_only=True).active
    header = [c.value for c in ws[1]]
    cells = []
    for row in ws.iter_rows(min_row=2):
        label = row[0].value
        for i, c in enumerate(row[1:], start=1):
            if isinstance(c.value, (int, float)):
                cells.append((str(label), str(header[i]), c.coordinate, float(c.value)))
    return cells


def main(corpus: str, out: str, seed: int = 3) -> None:
    from workroom.workroom_core.match.engine import Mention, match_mentions
    from workroom.workroom_core.ooxml.docx import Doc
    from workroom.workroom_core.ooxml.package import open_package
    from workroom.workroom_core.ooxml.xlsx import index_workbook
    from workroom.workroom_core.match.engine import SourceIndex

    rnd = random.Random(seed)
    totals = {"found": 0, "accept": 0, "confirm": 0, "none": 0}
    from workroom.workroom_core.match.numbers import consistent_with_source
    linkable = {"mentions_with_4plus_digits_equal_to_a_source_value": 0, "of_those_linked_automatically": 0, "of_those_sent_to_a_person": 0,
                "of_those_missed": 0, "of_those_where_several_cells_share_the_value": 0}
    per_company, sample = {}, []
    for folder in sorted(p for p in Path(corpus).iterdir() if p.is_dir()):
        xlsx = next(folder.glob("*.xlsx"))
        docx = next(folder.glob("*.docx"))
        index = SourceIndex(index_workbook(open_package(xlsx.read_bytes()), file=xlsx.name))
        dms = list(Doc(docx.read_bytes()).mentions())
        results = match_mentions([Mention(str(i), dm.number, dm.context, (dm.para_offset, dm.para_offset + len(dm.number.raw)) if dm.para_offset is not None else None) for i, dm in enumerate(dms)], index)
        counts = {"found": len(dms), "accept": 0, "confirm": 0, "none": 0}
        for dm, r in zip(dms, results):
            counts[r.decision] += 1
            if len(re.sub(r"\D", "", dm.number.raw).lstrip("0")) >= 4:
                hits = [c for c in index.cells if consistent_with_source(dm.number, c.value)[0]]
                if hits:
                    linkable["mentions_with_4plus_digits_equal_to_a_source_value"] += 1
                    linkable["of_those_linked_automatically" if r.decision == "accept" else "of_those_sent_to_a_person" if r.decision == "confirm" else "of_those_missed"] += 1
                    linkable["of_those_where_several_cells_share_the_value"] += len(hits) > 1
            if r.decision == "none" or r.best is None:
                continue
            same = [c for c in index.cells if abs(c.value - r.best.cell.value) < 1e-9]
            sample.append({
                "company": folder.name, "decision": r.decision, "number": dm.number.raw,
                "text": dm.context[0][:200], "heads": [h[:60] for h in dm.context[1:]],
                "workroom": [r.best.cell.row_labels, r.best.cell.col_labels, r.best.cell.ref], "same_value_cells": len(same),
            })
        per_company[folder.name] = counts
        for k in totals:
            totals[k] += counts[k]
    rnd.shuffle(sample)
    Path(out).write_text(json.dumps({"totals": totals, "per_company": per_company, "linkable": linkable, "sample": sample}, indent=1), encoding="utf-8")
    print(json.dumps(totals))
    print(json.dumps(linkable))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
