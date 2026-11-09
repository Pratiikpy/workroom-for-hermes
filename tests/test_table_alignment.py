"""A column of a report table that agrees, row by row, with one column of one sheet verifies every cell of that column at once."""
from pathlib import Path

from docx import Document
from xlsxwriter import Workbook

from workroom.workroom_core.service import Service

LABELS = ["Revenue", "Cost of sales", "Gross profit", "Operating costs", "Net result"]
REPORT = [1000, 600, 400, 150, 250]
DECOY = [1000, 610, 390, 150, 240]  # equal to the report in two rows only


def _project(tmp_path: Path, sheets: dict[str, list[int]], table_rows: int = 5) -> tuple[Service, str]:
    root = tmp_path / "proj"
    root.mkdir()
    with Workbook(str(root / "data.xlsx")) as wb:
        for name, values in sheets.items():
            ws = wb.add_worksheet(name)
            ws.write_row(0, 0, ["Line", "Amount"])
            for i, (label, v) in enumerate(zip(LABELS, values, strict=True), start=1):
                ws.write_row(i, 0, [label, v])
    d = Document()
    d.add_paragraph("Results for the year.")
    t = d.add_table(rows=table_rows + 1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Item", "Amount"
    for i in range(table_rows):
        t.cell(i + 1, 0).text, t.cell(i + 1, 1).text = LABELS[i], f"{REPORT[i]:,}"
    d.save(str(root / "report.docx"))
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, pid


def _states(svc: Service, pid: str) -> dict[str, tuple[str, str]]:
    return {t["text"]: (t["state"], t["source"].split(" ", 1)[1]) for t in svc.ties(pid)}


def test_a_column_that_agrees_with_one_sheet_resolves_the_cells_that_two_sheets_share(tmp_path: Path) -> None:
    svc, pid = _project(tmp_path, {"Actual": REPORT, "Draft": DECOY})
    got = _states(svc, pid)
    assert all(state == "accepted" for state, _ in got.values()), got
    assert {src for _, src in got.values()} == {f"Actual!B{r}" for r in range(2, 7)}, "every cell, including the two the Draft sheet shares, follows the sheet the whole column agrees with"
    proj, _ = svc._open(pid)
    shared = next(t for t in proj.ties() if t.raw == "1,000")
    svc._close_opened()
    assert shared.basis == "aligned", "the cell both sheets hold could only have been resolved by the column"
    assert "whole column" in svc.explain(pid, shared.id)["how"]


def test_two_sheets_that_agree_equally_are_not_resolved_by_alignment(tmp_path: Path) -> None:
    svc, pid = _project(tmp_path, {"Actual": REPORT, "Copy": REPORT})
    got = _states(svc, pid)
    assert all(state == "confirm" for state, _ in got.values()), got


def test_a_table_of_two_rows_is_not_enough_evidence(tmp_path: Path) -> None:
    svc, pid = _project(tmp_path, {"Actual": REPORT, "Draft": DECOY}, table_rows=2)
    got = _states(svc, pid)
    assert got["1,000"][0] == "confirm", got  # shared by both sheets, and two rows are too few to tell them apart


def test_a_cell_that_disagrees_in_a_verified_column_is_left_as_it_was(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    svc, pid = _project(tmp_path, {"Actual": REPORT, "Draft": DECOY})
    d = Document(str(root / "report.docx"))
    d.tables[0].cell(5, 1).text = "251"  # the report says 251 where the workbook says 250
    d.save(str(root / "report.docx"))
    svc.discover(pid)
    got = _states(svc, pid)
    assert "250" not in got and "251" not in got or got.get("251", ("none",))[0] != "accepted"
    assert all(got[f"{v:,}"][0] == "accepted" for v in REPORT[:4])
