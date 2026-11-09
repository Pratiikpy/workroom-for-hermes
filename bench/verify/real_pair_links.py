"""List the automatic links of one report-and-workbook pair with the document's own headings beside the workbook's, for a person to read.

    python real_pair_links.py <report.docx> <workbook.xlsx> <out.json>

For every automatic link: the number, the heading of its row and column in the report, the paragraph it sits in, and the sheet, cell and headings of the cell it points at.
Nothing here judges a link; the judging is done by reading the output.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402


def main() -> None:
    report, workbook, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    tmp = Path(tempfile.mkdtemp(prefix="real_pair_links_"))
    root = tmp / "project"
    root.mkdir()
    shutil.copy2(report, root / report.name)
    shutil.copy2(workbook, root / workbook.name)
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    mentions = {(m.slide, m.para, m.seg, m.offset): m for m in Doc((root / report.name).read_bytes()).mentions()}
    rows = []
    for t in svc.ties(pid):
        if t["state"] not in ("accepted", "confirmed"):
            continue
        why = svc.explain(pid, t["id"])
        proj, _ = svc._open(pid)
        tie = proj.tie(t["id"])
        svc._close_opened()
        m = mentions.get((tie.slide, tie.para, tie.seg, tie.offset))
        rows.append({
            "n": len(rows) + 1, "number": t["text"], "para": tie.para, "cell": list(tie.cell_rc) if tie.cell_rc else None,
            "doc_context": list(m.context)[:3] if m else [], "source": f"{tie.sheet}!{tie.ref}", "row": why["source"]["row"], "column": why["source"]["column"],
            "formula": bool(why["source"]["formula"]), "value": why["source"]["value_now"],
        })
    rows.sort(key=lambda r: r["para"])
    for i, r in enumerate(rows, 1):
        r["n"] = i
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(rows), "automatic links written")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
