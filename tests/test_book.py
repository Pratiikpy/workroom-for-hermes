import io
import json
from pathlib import Path

import pytest

from workroom.workroom_core.ooxml.book import Book
from workroom.workroom_core.ooxml.package import open_package, raw_unchanged
from workroom.workroom_core.ooxml.runs import EditError
from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell
from workroom.workroom_core.service import Service


def workbook(revenue: float, margin: float) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2"])
    ws.append(["Revenue", 100, revenue])
    ws.append(["Margin", 0.4, margin])
    ws["D2"] = "=C2*2"  # a dependent formula
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_mentions_skip_formulas_and_carry_labels() -> None:
    book = Book(workbook(120, 0.25))
    ms = list(book.mentions())
    refs = {(m.para, m.seg): m for m in ms}
    assert (2, 4) not in refs  # D2 is a formula
    c2 = refs[(2, 3)]
    assert c2.number.raw == "120" and "Revenue" in c2.context and "Q2" in c2.context


def test_edit_changes_one_cell_and_asks_excel_to_recalculate() -> None:
    data = workbook(120, 0.25)
    book = Book(data)
    c2 = next(m for m in book.mentions() if (m.para, m.seg) == (2, 3))
    book.edit_mention(c2, "150")
    out, report = book.serialize()
    assert set(report.parts_changed) == {"xl/worksheets/sheet1.xml", "xl/workbook.xml"}
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(out)).active
    assert ws["C2"].value == 150 and ws["D2"].value == "=C2*2"
    assert b'fullCalcOnLoad="1"' in open_package(out).read("xl/workbook.xml")
    before, after = open_package(data), open_package(out)
    others = [n for n in before.names() if n not in report.parts_changed]
    assert raw_unchanged(before, after, others) == others


def test_a_formula_cell_is_never_overwritten() -> None:
    book = Book(workbook(120, 0.25))
    c2 = next(m for m in book.mentions() if (m.para, m.seg) == (2, 3))
    forged = type(c2)(c2.slide, c2.shape_id, 2, 4, 0, c2.number, c2.context, (2, 4), None)  # D2
    with pytest.raises(EditError):
        book.edit_mention(forged, "9")


def test_a_cell_changed_since_discovery_is_refused() -> None:
    data = workbook(120, 0.25)
    book = Book(data)
    c2 = next(m for m in book.mentions() if (m.para, m.seg) == (2, 3))
    other = Book(patch_numeric_cell(data, "Results", "C2", 130))
    with pytest.raises(EditError):
        other.edit_mention(c2, "150")


def test_a_report_workbook_follows_a_data_workbook_through_the_service(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "data" / "data.xlsx").write_bytes(workbook(120, 0.25))
    (root / "report.xlsx").write_bytes(workbook(120, 0.25))
    (root / "workroom.json").write_text(json.dumps({"targets": ["report.xlsx"]}))
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    found = svc.discover(pid)
    assert found["accepted"] >= 2
    src = root / "data" / "data.xlsx"
    src.write_bytes(patch_numeric_cell(patch_numeric_cell(src.read_bytes(), "Results", "C2", 150), "Results", "C3", 0.3))
    source_before = src.read_bytes()
    staged = svc.stage(pid)
    assert {c["new_text"] for c in staged["changes"]} == {"150", "0.30"}
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    from openpyxl import load_workbook

    ws = load_workbook(root / "report.xlsx").active
    assert ws["C2"].value == 150 and ws["C3"].value == 0.3 and ws["D2"].value == "=C2*2"
    assert src.read_bytes() == source_before  # sources are inputs; a release never writes them
    assert svc.plan(pid)["changes"] == []


def test_changes_say_where_a_number_sits_in_plain_words(tmp_path: Path) -> None:
    from docx import Document

    from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell as patch
    from workroom.tests.test_flagship_headless import make_workbook

    root = tmp_path / "w"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    d = Document()
    d.add_paragraph("Revenue in Q2 was 120 and margin was 25%.")
    d.sections[0].header.paragraphs[0].text = "Revenue Q2 summary: 120"
    d.save(root / "report.docx")
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    (root / "results.xlsx").write_bytes(patch((root / "results.xlsx").read_bytes(), "Results", "C2", 150))
    where = sorted(c["where"] for c in svc.plan(pid)["changes"])
    assert where == ["Body", "Header"]
    assert sorted(c["where"] for c in svc.stage(pid)["changes"]) == ["Body", "Header"]
