"""How many questions the column questions replace on one report and its workbooks, and what answering them with the top alternative does.

    python column_questions_measure.py <report> <workbook> [<workbook> ...]
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from workroom.workroom_core.service import Service  # noqa: E402


def main() -> None:
    rep, books = Path(sys.argv[1]), [Path(b) for b in sys.argv[2:]]
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "p"
    root.mkdir()
    for f in [rep, *books]:
        shutil.copy2(f, root / f.name)
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    found = svc.discover(pid)
    qs = svc.column_questions(pid)
    print("asked figures", len(found["need_confirmation"]), "accepted", found["accepted"], "| column questions", len(qs), "covering", sum(q["rows"] for q in qs), "rows")
    for q in qs[:4]:
        print("  ", q["section"][:36], "|", q["report_column"][:22], "|", q["rows"], "rows |", [(a["sheet"], a["column"], a["agree"], a["labels"][:2]) for a in q["alternatives"][:3]])
    proj, _ = svc._open(pid)
    for q in qs:
        a = q["alternatives"][0]
        proj.choose_column(q["signature"], a["file"], a["sheet"], a["column"], "measure")
    again = svc.discover(pid)
    print("after answering every question with its top alternative: accepted", found["accepted"], "->", again["accepted"], "| asked figures", len(again["need_confirmation"]))


if __name__ == "__main__":
    main()
