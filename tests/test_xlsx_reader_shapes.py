"""Workbooks written by other tools: Strict Open XML, cells and rows without positions, hidden columns and sheets."""
import io
import re
import zipfile

from xlsxwriter import Workbook

from workroom.workroom_core.ooxml.package import open_package
from workroom.workroom_core.ooxml.xlsx import index_workbook

STRICT = {
    b"http://schemas.openxmlformats.org/spreadsheetml/2006/main": b"http://purl.oclc.org/ooxml/spreadsheetml/main",
    b"http://schemas.openxmlformats.org/officeDocument/2006/relationships": b"http://purl.oclc.org/ooxml/officeDocument/relationships",
    b"http://schemas.openxmlformats.org/drawingml/2006/main": b"http://purl.oclc.org/ooxml/drawingml/main",
}


def _book(build) -> bytes:
    buf = io.BytesIO()
    wb = Workbook(buf, {"in_memory": True})
    build(wb)
    wb.close()
    return buf.getvalue()


def _simple(wb) -> None:
    ws = wb.add_worksheet("Data")
    ws.write(0, 0, "Revenue")
    ws.write(0, 1, 14.5)
    ws.write(1, 0, "Costs")
    ws.write(1, 1, 9.25)


def _rewrite(data: bytes, fn) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            body = zin.read(item.filename)
            if item.filename.endswith((".xml", ".rels")):
                body = fn(item.filename, body)
            zout.writestr(item.filename, body)
    return out.getvalue()


def _cells(data: bytes):
    return {(c.sheet, c.ref): c for c in index_workbook(open_package(data))}


def test_a_strict_open_xml_workbook_is_read() -> None:
    def to_strict(name: str, body: bytes) -> bytes:
        for a, b in STRICT.items():
            body = body.replace(a, b)
        return body

    cells = _cells(_rewrite(_book(_simple), to_strict))
    assert {(k, round(c.value, 2)) for k, c in cells.items()} == {(("Data", "B1"), 14.5), (("Data", "B2"), 9.25)}
    assert cells[("Data", "B1")].row_labels == ("Revenue",)


def test_rows_and_cells_without_positions_are_read_in_order() -> None:
    def strip_positions(name: str, body: bytes) -> bytes:
        if name.startswith("xl/worksheets/"):
            body = re.sub(rb' r="[A-Z]+[0-9]+"', b"", body)
            body = re.sub(rb'(<row )r="[0-9]+" ?', rb"\1", body)
        return body

    cells = _cells(_rewrite(_book(_simple), strip_positions))
    assert {(k[1], round(c.value, 2)) for k, c in cells.items()} == {("B1", 14.5), ("B2", 9.25)}


def test_figures_in_hidden_columns_and_hidden_sheets_are_flagged() -> None:
    def build(wb) -> None:
        ws = wb.add_worksheet("Visible")
        ws.write(0, 0, "Revenue")
        ws.write(0, 1, 1.5)
        ws.write(0, 2, 2.5)
        ws.set_column(2, 2, None, None, {"hidden": True})
        scratch = wb.add_worksheet("Scratch")
        scratch.write(0, 0, "Tmp")
        scratch.write(0, 1, 7.5)
        scratch.hide()

    cells = _cells(_book(build))
    assert not cells[("Visible", "B1")].hidden
    assert cells[("Visible", "C1")].hidden
    assert cells[("Scratch", "B1")].hidden


def test_formulas_with_no_saved_value_are_counted_not_silently_dropped() -> None:
    from workroom.workroom_core.ooxml.xlsx import index_workbook

    def build(wb) -> None:
        ws = wb.add_worksheet("Model")
        ws.write(0, 0, "Revenue")
        ws.write(0, 1, 10)
        ws.write_formula(1, 1, "=B1*2", None, "")  # a formula written without its result, as some libraries do
        ws.write_formula(2, 1, "=B1*3", None, 30)

    stats: dict = {}
    cells = index_workbook(open_package(_book(build)), stats=stats)
    assert stats["uncalculated"] == 1
    assert sorted(c.ref for c in cells) == ["B1", "B3"]


def test_the_project_reports_a_workbook_with_uncalculated_formulas(tmp_path) -> None:
    from workroom.workroom_core.project import Project

    root = tmp_path / "p"
    root.mkdir()
    with Workbook(str(root / "m.xlsx")) as wb:
        ws = wb.add_worksheet("Model")
        ws.write_row(0, 0, ["Revenue", 10])
        ws.write_formula(1, 1, "=B1*2", None, "")
    found = Project(root, tmp_path / "state").discover()
    assert found.uncalculated == (("m.xlsx", 1),)


def test_dashes_and_unit_marks_between_a_figure_and_its_row_heading_are_not_headings(tmp_path) -> None:
    """Financial statements print a dash for nil; the heading is the text further left, not the dash."""
    from xlsxwriter import Workbook

    from workroom.workroom_core.ooxml.package import open_package
    from workroom.workroom_core.ooxml.xlsx import index_workbook

    path = tmp_path / "w.xlsx"
    with Workbook(str(path)) as wb:
        ws = wb.add_worksheet("Note")
        ws.write_row(0, 0, ["", "Leasehold", "Office"])
        ws.write_row(1, 0, ["", "$", "$"])
        ws.write_row(2, 0, ["Transfer", "-", "-", 35980, "-", -35980])
    cells = {c.ref: c for c in index_workbook(open_package(path.read_bytes()), file="w.xlsx")}
    assert cells["D3"].row_labels == ("Transfer",) and cells["F3"].row_labels == ("Transfer",)
    assert "$" not in cells["D3"].col_labels and "-" not in cells["F3"].row_labels
