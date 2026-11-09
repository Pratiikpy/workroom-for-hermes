"""One question per report table column when the column fits two workbook columns about equally, instead of one per figure."""

import io
from pathlib import Path

import openpyxl
import pytest
from docx import Document

from workroom.workroom_core.service import Service, ServiceError

ROWS = [("Land", 100, 100), ("Buildings", 250, 250), ("Plant", 75, 75), ("Vehicles", 40, 40), ("Other", 12, 13)]


def project(tmp_path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "5.1.3"
    ws.append(["Fair value determination", None, None])
    ws.append(["Asset class", "Carrying amount", "Level 3"])
    for name, a, b in ROWS:
        ws.append([name, a, b])
    buf = io.BytesIO()
    wb.save(buf)
    d = Document()
    d.add_paragraph("5.1.3 Fair value determination")
    t = d.add_table(rows=len(ROWS) + 1, cols=2)
    t.cell(0, 0).text = "Asset class"
    t.cell(0, 1).text = "Fair value measurement"
    for r, (name, a, _b) in enumerate(ROWS, 1):
        t.cell(r, 0).text = name
        t.cell(r, 1).text = str(a)
    dbuf = io.BytesIO()
    d.save(dbuf)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "book.xlsx").write_bytes(buf.getvalue())
    (root / "report.docx").write_bytes(dbuf.getvalue())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return root, svc, pid



def test_a_column_that_fits_two_workbook_columns_is_one_question_with_both_choices(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    questions = svc.column_questions(pid)
    assert len(questions) == 1
    q = questions[0]
    assert q["rows"] >= 2 and {a["column"] for a in q["alternatives"]} == {2, 3}
    assert {tuple(a["labels"]) for a in q["alternatives"]} >= {("Carrying amount",), ("Level 3",)} or all(a["labels"] for a in q["alternatives"])


def test_the_answer_links_every_row_that_agrees_and_leaves_the_row_that_does_not(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    q = svc.column_questions(pid)[0]
    level3 = next(a for a in q["alternatives"] if "Level 3" in " ".join(a["labels"]))
    carrying = next(a for a in q["alternatives"] if "Carrying amount" in " ".join(a["labels"]))
    answered = svc.choose_column(pid, q["signature"], carrying["file"], carrying["sheet"], carrying["column"])
    assert answered["linked_more"] >= 2 and svc.column_questions(pid) == []
    accepted = {t["text"]: t["source"] for t in svc.ties(pid) if t["state"] in ("accepted", "confirmed") and t["deck"] == "report.docx"}
    assert accepted.get("100", "").endswith("B3") and accepted.get("250", "").endswith("B4")
    assert not any(src.endswith(("C3", "C4")) for src in accepted.values())  # the other column was not used
    assert level3["column"] != carrying["column"]


def test_the_owner_can_only_choose_among_the_offered_columns_and_no_agent_tool_can(tmp_path: Path) -> None:
    from workroom import TOOLS

    root, svc, pid = project(tmp_path)
    q = svc.column_questions(pid)[0]
    with pytest.raises(ServiceError, match="not one of the choices"):
        svc.choose_column(pid, q["signature"], "book.xlsx", "5.1.3", 9)
    with pytest.raises(ServiceError, match="not waiting"):
        svc.choose_column(pid, "no such column", "book.xlsx", "5.1.3", 2)
    assert not any("column" in t[0] for t in TOOLS)


def test_the_choice_is_remembered_for_a_copy_of_the_report(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    q = svc.column_questions(pid)[0]
    a = next(a for a in q["alternatives"] if "Carrying amount" in " ".join(a["labels"]))
    svc.choose_column(pid, q["signature"], a["file"], a["sheet"], a["column"])
    (root / "next.docx").write_bytes((root / "report.docx").read_bytes())
    svc.discover(pid)
    assert svc.column_questions(pid) == []
    copy = {t["text"]: t["state"] for t in svc.ties(pid) if t["deck"] == "next.docx"}
    assert copy.get("100") in ("accepted", "confirmed") and copy.get("250") in ("accepted", "confirmed")
