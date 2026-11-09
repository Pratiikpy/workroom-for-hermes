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


def _ordinal_project(tmp_path: Path, rows, source_columns: list[str], doc_columns: list[int]):
    """A report table that is a block of a sheet: ``doc_columns`` are the source column positions (0-based among the value columns) it copies."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Executive data"
    ws.append(["Agency", *source_columns])
    for name, values in rows:
        ws.append([name, *values])
    buf = io.BytesIO()
    wb.save(buf)
    d = Document()
    d.add_paragraph("Executive data")
    t = d.add_table(rows=len(rows) + 1, cols=len(doc_columns) + 1)
    t.cell(0, 0).text = "Agency"
    for c in range(len(doc_columns)):
        t.cell(0, c + 1).text = ""
    for r, (name, values) in enumerate(rows, 1):
        t.cell(r, 0).text = name
        for c, k in enumerate(doc_columns, 1):
            t.cell(r, c).text = str(values[k])
    dbuf = io.BytesIO()
    d.save(dbuf)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "book.xlsx").write_bytes(buf.getvalue())
    (root / "report.docx").write_bytes(dbuf.getvalue())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, pid


AGENCIES = [("Alpha Health", [4, 0, 0, 7, 0, 3]), ("Bravo Health", [0, 0, 2, 0, 0, 5]), ("Charlie Health", [1, 0, 0, 0, 6, 0]), ("Delta Health", [0, 0, 0, 9, 0, 0]), ("Echo Health", [8, 0, 0, 0, 0, 4])]
COLUMNS = ["June 2025 - Total", "June 2025 - Women", "June 2025 - Men", "June 2024 - Total", "June 2024 - Women", "Variance - Total"]


def test_columns_that_value_cannot_tell_apart_are_placed_by_their_order(tmp_path: Path) -> None:
    svc, pid = _ordinal_project(tmp_path, AGENCIES, COLUMNS, [0, 1, 2, 3, 4, 5])
    linked = {t["text"]: t["source"] for t in svc.ties(pid) if t["deck"] == "report.docx" and t["state"] in ("accepted", "confirmed")}
    assert len([t for t in svc.ties(pid) if t["deck"] == "report.docx" and t["state"] == "accepted"]) >= 25  # nearly the whole 5 x 6 block
    zeros = [t for t in svc.ties(pid) if t["deck"] == "report.docx" and t["text"] == "0" and t["state"] == "accepted"]
    assert zeros and all("!" in t["source"] for t in zeros)
    assert linked


def test_the_order_corrects_a_link_that_value_alone_made_to_another_period(tmp_path: Path) -> None:
    rows = [("Alpha Health", [4, 0, 4]), ("Bravo Health", [5, 1, 5]), ("Charlie Health", [1, 3, 2]), ("Delta Health", [7, 0, 7]), ("Echo Health", [8, 2, 3])]
    svc, pid = _ordinal_project(tmp_path, rows, ["June 2025 - Total", "June 2025 - Women", "June 2024 - Total"], [0, 2])
    placed = sorted(t["source"].rsplit("!", 1)[-1] for t in svc.ties(pid) if t["deck"] == "report.docx" and t["state"] in ("accepted", "confirmed"))
    # the report's two columns copy "June 2025 - Total" (B) and "June 2024 - Total" (D); on several rows the two hold the same figure
    assert placed == ["B2", "B3", "B4", "B5", "B6", "D2", "D3", "D4", "D5", "D6"]


def test_two_identical_source_columns_cannot_be_told_apart_so_they_stay_questions(tmp_path: Path) -> None:
    rows = [("Alpha Health", [4, 4, 9]), ("Bravo Health", [5, 5, 8]), ("Charlie Health", [1, 1, 7]), ("Delta Health", [3, 3, 6])]
    svc, pid = _ordinal_project(tmp_path, rows, ["June 2025 - Total", "June 2025 - Women", "June 2024 - Total"], [0, 2])
    firsts = [t for t in svc.ties(pid) if t["deck"] == "report.docx" and t["text"] in ("4", "5", "1", "3") and t["state"] == "accepted"]
    assert not firsts or all(t["source"].rsplit("!", 1)[-1][0] in "BC" for t in firsts)  # never the 2024 column: only B and C hold these figures; the order does not pick between them


def test_two_equally_good_orders_leave_the_columns_as_questions(tmp_path: Path) -> None:
    rows = [("Alpha Health", [0, 0, 0]), ("Bravo Health", [0, 0, 0]), ("Charlie Health", [0, 0, 0]), ("Delta Health", [0, 0, 0])]
    svc, pid = _ordinal_project(tmp_path, rows, COLUMNS[:3], [0, 1])
    assert not [t for t in svc.ties(pid) if t["deck"] == "report.docx" and t["state"] == "accepted"]  # nothing can tell which two of three all-zero columns these are
