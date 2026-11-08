"""A cell's place in time, found from its own row and column headings."""
from pathlib import Path

from xlsxwriter import Workbook

from workroom.workroom_core.meaning.periods import Period
from workroom.workroom_core.meaning.timeline import Timeline
from workroom.workroom_core.ooxml.book import index_workbook
from workroom.workroom_core.ooxml.package import open_package


def _cells(path: Path):
    return index_workbook(open_package(path.read_bytes()), file=path.name)


def _book(path: Path, header: list, rows: list[list]) -> list:
    with Workbook(str(path)) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, header)
        for i, r in enumerate(rows, start=1):
            ws.write_row(i, 0, r)
    return _cells(path)


def test_time_across_columns_finds_previous_and_year_earlier(tmp_path: Path) -> None:
    cells = _book(tmp_path / "a.xlsx", ["Metric", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026"], [["Revenue", 10, 11, 12, 13, 14], ["Margin", 0.5, 0.51, 0.52, 0.53, 0.54]])
    tl = Timeline(cells)
    rev_q3 = next(c for c in cells if c.ref == "F2")
    assert tl.previous(rev_q3).ref == "E2" and tl.year_ago(rev_q3).ref == "B2" and tl.next(rev_q3) is None
    assert [c.ref for c in tl.history(rev_q3)] == ["B2", "C2", "D2", "E2"]
    margin_q3 = next(c for c in cells if c.ref == "F3")
    assert tl.previous(margin_q3).ref == "E3", "each row is its own series"


def test_time_down_rows_finds_previous_and_year_earlier(tmp_path: Path) -> None:
    cells = _book(tmp_path / "b.xlsx", ["Quarter", "Revenue", "Cost"], [["Q1 2025", 1, 5], ["Q2 2025", 2, 6], ["Q3 2025", 3, 7], ["Q4 2025", 4, 8], ["Q1 2026", 5, 9]])
    tl = Timeline(cells)
    cost_q1_26 = next(c for c in cells if c.ref == "C6")
    assert tl.previous(cost_q1_26).ref == "C5" and tl.year_ago(cost_q1_26).ref == "C2"
    assert tl.placed(cost_q1_26).axis == "row" and tl.placed(cost_q1_26).period == Period("q", 2026 * 4)


def test_a_gap_is_a_gap_not_the_nearest_neighbour(tmp_path: Path) -> None:
    cells = _book(tmp_path / "c.xlsx", ["Metric", "Q1 2026", "Q3 2026"], [["Revenue", 1, 3]])
    tl = Timeline(cells)
    assert tl.previous(next(c for c in cells if c.ref == "C2")) is None


def test_two_cells_for_one_period_is_a_conflict(tmp_path: Path) -> None:
    cells = _book(tmp_path / "d.xlsx", ["Metric", "Q1 2026", "Q2 2026", "Q2 2026"], [["Revenue", 1, 2, 3]])
    tl = Timeline(cells)
    assert tl.year_ago(next(c for c in cells if c.ref == "B2")) is None
    q1 = next(c for c in cells if c.ref == "B2")
    assert tl.next(q1) is None, "two Q2 cells: the next period is ambiguous, so it is not answered"


def test_labels_without_a_period_have_no_timeline(tmp_path: Path) -> None:
    cells = _book(tmp_path / "e.xlsx", ["Metric", "Actual", "Plan"], [["Revenue", 1, 2]])
    tl = Timeline(cells)
    assert all(tl.placed(c) is None for c in cells)
