from __future__ import annotations

import io

import openpyxl

from workroom.workroom_core.meaning.timeline import Timeline
from workroom.workroom_core.ooxml.package import open_package
from workroom.workroom_core.ooxml.xlsx import index_workbook


def _cells(build) -> dict[str, object]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    build(ws)
    buf = io.BytesIO()
    wb.save(buf)
    return {c.ref: c for c in index_workbook(open_package(buf.getvalue()), file="data.xlsx")}


def test_a_year_printed_as_a_number_heads_its_column_even_with_a_unit_row_between() -> None:
    def build(ws) -> None:
        ws.append([None, None, 2025, 2024])
        ws.append([None, "Notes", "$'000", "$'000"])
        ws.append(["Cash", 7.1, 1554, 1449])

    cells = _cells(build)
    assert cells["C3"].col_labels[-1] == "2025" and cells["D3"].col_labels[-1] == "2024"
    assert "2025" not in cells["B3"].col_labels  # the notes column sits under no year heading
    tl = Timeline(list(cells.values()))
    assert tl.previous(cells["C3"]) is cells["D3"]


def test_a_year_alone_on_its_row_opens_a_block_of_rows_and_each_block_is_its_own_period() -> None:
    def build(ws) -> None:
        ws.append(["Appropriations", "Annual", "Other"])
        ws.append([2025])
        ws.append(["Outputs", 100, 10])
        ws.append(["Capital", 40, 4])
        ws.append([2024])
        ws.append(["Outputs", 90, 9])
        ws.append(["Capital", 35, 3])

    cells = _cells(build)
    assert cells["B3"].row_labels == ("Outputs", "2025") and cells["B6"].row_labels == ("Outputs", "2024")
    tl = Timeline(list(cells.values()))
    assert tl.previous(cells["B3"]) is cells["B6"]
    assert tl.previous(cells["C4"]) is cells["C7"]  # the same item in the same column, one block earlier


def test_a_row_of_ordinary_figures_that_happen_to_look_like_years_is_not_a_heading() -> None:
    def build(ws) -> None:
        ws.append(["Region", "Total", "Count"])
        ws.append(["North", 2020, 15])
        ws.append(["South", 1995, 12])

    cells = _cells(build)
    assert all(not any(x.isdigit() and len(x) == 4 for x in c.col_labels + c.row_labels) for c in cells.values())


def test_a_small_figure_that_grows_follows_the_documents_thousands_and_bracket_style() -> None:
    from workroom.workroom_core.match.numbers import format_like, house_style, parse_numbers

    house = house_style(parse_numbers("Grants 12,345 and 6,789 and 4,321 and (1,234) and (5,678) and (9,876)"))
    assert house.commas and house.parens
    assert format_like(parse_numbers("77")[0], 3893.0, "exact", house) == "3,893"
    assert format_like(parse_numbers("68")[0], -59816.0, "exact", house) == "(59,816)"
    assert format_like(parse_numbers("77")[0], 3893.0, "exact") == "3893"  # without a house style the old behaviour stands
    assert format_like(parse_numbers("-77")[0], -3893.0, "exact", house) == "-3,893"  # a minus sign that was written stays a minus sign


def test_a_sheet_stacking_tables_takes_each_cells_headings_from_its_own_block() -> None:
    """Two tables on one sheet, each with its own group and years: the second table's cells are not also labelled with the first table's group."""
    import io

    from xlsxwriter import Workbook

    from workroom.workroom_core.ooxml.package import open_package
    from workroom.workroom_core.ooxml.xlsx import index_workbook

    buf = io.BytesIO()
    with Workbook(buf) as wb:
        ws = wb.add_worksheet("Outputs")
        ws.write_row(0, 1, ["Agriculture", "", "Water", ""])
        ws.write_row(1, 1, ["2025", "2024", "2025", "2024"])
        ws.write_row(2, 0, ["Net result", 10, 20, 30, 40])
        ws.merge_range(3, 0, 3, 4, "Other flows")
        ws.write_row(10, 1, ["Energy", "", "Fire", ""])
        ws.write_row(11, 1, ["2025", "2024", "2025", "2024"])
        ws.write_row(12, 0, ["Net result", 50, 60, 70, 80])
    cells = {c.ref: c for c in index_workbook(open_package(buf.getvalue()), file="x.xlsx")}
    assert "Agriculture" in cells["B3"].col_labels and "Energy" not in cells["B3"].col_labels
    assert "Energy" in cells["B13"].col_labels and "Agriculture" not in cells["B13"].col_labels and "Water" not in cells["D13"].col_labels
