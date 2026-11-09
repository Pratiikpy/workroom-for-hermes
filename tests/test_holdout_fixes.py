"""Fixes that came from reading two independently authored Victorian department reports (holdout 1, `bench/verify/HOLDOUT1_RESULT.md`)."""

import io

import openpyxl

from workroom.workroom_core.match.engine import Mention, SourceIndex, is_coincidence, match_mentions, section_agrees
from workroom.workroom_core.match.numbers import parse_numbers
from workroom.workroom_core.ooxml.package import open_package
from workroom.workroom_core.ooxml.xlsx import SourceCell, footnoted_number, index_workbook


def cell(ref: str, value: float, row: str, col: str = "2025", sheet: str = "S") -> SourceCell:
    return SourceCell(sheet, ref, 2, 2, value, False, False, (row,), (col,), False, "b.xlsx")


def decide(text: str, shown: str, cells: list[SourceCell], heads: tuple[str, ...] = (), section: str = "", row_head: str = ""):
    pos = text.rfind(shown)
    nm = parse_numbers(shown)[0]
    return match_mentions([Mention("t", nm, (text,) + heads, (pos, pos + len(shown)), section, row_head)], SourceIndex(cells))[0]


def workbook(build) -> bytes:
    wb = openpyxl.Workbook()
    build(wb.active)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_a_figure_typed_as_text_with_a_footnote_mark_is_a_source_number() -> None:
    assert footnoted_number("14,263(i)") == 14263.0
    assert footnoted_number("(2,345)(ii)") == -2345.0
    assert footnoted_number("-7.5(a)") == -7.5
    assert footnoted_number("2025(a)") is None  # a year with a mark is still a heading
    assert footnoted_number("Total (i)") is None
    assert footnoted_number("14,263") is None  # no mark: not guessed at

    def build(ws) -> None:
        ws["A1"] = "Net assets"
        ws["B1"] = "14,263(i)"
        ws["A2"] = "Year"
        ws["B2"] = "2025"

    cells = index_workbook(open_package(workbook(build)))
    assert [(c.ref, c.value) for c in cells] == [("B1", 14263.0)]


def test_a_merged_heading_heads_every_column_it_spans() -> None:
    def build(ws) -> None:
        ws["B1"] = "Fire and Emergency"
        ws.merge_cells("B1:C1")
        ws["B2"] = "$'000"
        ws["C2"] = "$'000"
        ws["A3"] = "Net gain"
        ws["B3"] = -14
        ws["C3"] = -14

    cells = {c.ref: c for c in index_workbook(open_package(workbook(build)))}
    assert "Fire and Emergency" in cells["B3"].col_labels and "Fire and Emergency" in cells["C3"].col_labels


def test_the_heading_a_figure_sits_under_can_name_the_sheet() -> None:
    assert section_agrees("4.1.2", "4.1.2 Departmental Outputs") is True
    assert section_agrees("3.1.1a", "3.1.1 (a) Employee benefits") is True
    assert section_agrees("Balance sheet", "Balance sheet as at 30 June 2025") is True
    assert section_agrees("2.2.1", "2.2.3 Annotated income agreements") is False
    assert section_agrees("OHS", "Incident management") is False
    assert section_agrees("4.1.2", "") is False


def test_the_sheet_the_section_names_breaks_a_tie_between_equal_cells() -> None:
    cells = [cell("B2", 180599.0, "Net result", sheet="Cash flow"), cell("B3", 180599.0, "Net result", sheet="4.1.2")]
    plain = decide("Net result 2025 180,599", "180,599", cells)
    assert plain.best.cell.sheet == "Cash flow"
    named = decide("Net result 2025 180,599", "180,599", cells, section="4.1.2 Departmental Outputs")
    assert named.best.cell.sheet == "4.1.2" and named.best.in_section


def test_a_closest_cell_off_the_named_sheet_is_not_accepted_when_a_cell_on_it_fits_too() -> None:
    cells = [cell("B2", 117938.0, "Metropolitan parks at fair value", sheet="5.1"), cell("B3", 117938.0, "Crown land Metropolitan parks", sheet="5.1.3")]
    r = decide("Metropolitan parks 117,938", "117,938", cells, section="5.1.3 Fair value determination")
    assert r.decision == "confirm"


def test_a_movement_in_the_text_is_not_linked_to_a_balance() -> None:
    cells = [cell("B2", 14913.0, "Derivative financial instruments", "$000")]
    balance = decide("Derivative financial instruments were 14,913 at year end", "14,913", cells)
    assert balance.decision == "accept"
    movement = decide("Derivative financial instruments decreased by 14,913 in the year", "14,913", cells)
    assert movement.decision == "confirm" and "change" in movement.reason
    moved = [cell("B2", 14913.0, "Increase in derivative financial instruments", "$000")]
    assert decide("Derivative financial instruments increased by 14,913 in the year", "14,913", moved).decision == "accept"


def test_the_row_heading_of_a_report_table_has_to_be_the_row_or_column_heading_of_the_cell() -> None:
    cells = [cell("B2", 68901.0, "Total borrowings", sheet="6.2")]
    wrong = decide("Total 68,901", "68,901", cells, heads=("Derivative financial assets",), row_head="Derivative financial assets")
    assert wrong.decision != "accept"
    turned = [SourceCell("OHS", "D3", 3, 4, 10.0, False, False, ("July",), ("Near miss",), False, "b.xlsx")]
    assert decide("10", "10", turned, heads=("Near miss",), row_head="Near miss").best is not None  # a table turned on its side still matches


def test_a_short_number_does_not_borrow_the_workbooks_unit_to_become_a_candidate() -> None:
    assert decide("Seven (7) projects were funded", "7", [cell("B2", 7000.0, "Net result", "$'000", sheet="4.2.1")]).decision == "none"
    assert decide("Net result (in thousands) 66,670", "66,670", [cell("B2", 66_670_000.0, "Net result", "2025", sheet="4.2.1")]).decision == "accept"


def test_a_short_number_with_little_behind_it_is_listed_apart_not_asked() -> None:
    assert is_coincidence(0.0, "25") and is_coincidence(0.29, "25")
    assert not is_coincidence(0.32, "25") and not is_coincidence(0.2, "180,599")


def test_a_dated_balance_label_is_a_point_that_steps_by_a_year() -> None:
    from workroom.workroom_core.meaning.periods import describe_period, find_periods, parse_period, period_label

    opening = parse_period("Balance at 1 July 2023")
    closing = parse_period("Balance at 30 June 2024")
    assert opening.kind == "dt" and closing.kind == "dt" and opening != parse_period("Balance at 30 June 2023")
    assert period_label(closing.shifted(1), "Balance at 30 June 2024") == "Balance at 30 June 2025"
    assert describe_period(opening.shifted(1)) == "1 Jul 2024"
    assert [p.index for _, _, p in find_periods("as at 30 June 2025 the department held")] == [2025]
    assert parse_period("July 2023").kind == "m" and parse_period("1 July 2023 and 1 July 2024") is None
