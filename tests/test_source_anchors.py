"""A tie follows its source cell when the workbook is edited around it, and asks the owner when it cannot tell."""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.project import Project

SENTENCE = "Net revenue reached $15.1 million in Q3 2026, up 7.9% from $14.0 million in Q2 2026."


def _book(root: Path, header: list, rows: list[list]) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, header)
        for i, r in enumerate(rows, 1):
            ws.write_row(i, 0, r)


def _project(tmp_path: Path, header=None, rows=None, text=SENTENCE) -> Project:
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    _book(root, header or ["Metric", "Q2 2026", "Q3 2026"], rows or [["Net revenue", 14_000_000, 15_100_000]])
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = text
    prs.save(str(root / "board.pptx"))
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


def _refs(proj: Project) -> dict[str, str]:
    return {t.raw: t.ref for t in proj.ties() if t.kind == "text"}


def test_inserting_a_column_does_not_make_the_ties_read_the_wrong_cells(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    assert _refs(proj) == {"$15.1 million": "C2", "$14.0 million": "B2"}
    _book(proj.root, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"], [["Net revenue", 13_000_000, 14_000_000, 15_100_000]])  # a new first column pushes everything right
    plan = proj.plan_refresh()
    assert plan.impacts == [] and any("moved from C2 to D2" in n for n in plan.notes)
    assert _refs(proj) == {"$15.1 million": "D2", "$14.0 million": "C2"}
    assert proj.impact().changes == []


def test_a_sliding_window_of_periods_keeps_each_tie_on_its_own_period(tmp_path: Path) -> None:
    root = tmp_path / "p"
    proj = _project(root, ["Quarter", "Net revenue"], [["Q2 2026", 14_000_000], ["Q3 2026", 15_100_000]])
    assert _refs(proj) == {"$15.1 million": "B3", "$14.0 million": "B2"}
    _book(proj.root, ["Quarter", "Net revenue"], [["Q3 2026", 15_100_000], ["Q4 2026", 16_400_000]])  # the oldest row dropped off the top
    plan = proj.plan_refresh()
    assert plan.impacts == [], "nothing about Q3 changed; only its address did, and Q2 left the sheet"
    by_raw = {t.raw: t for t in proj.ties()}
    assert by_raw["$15.1 million"].ref == "B2" and by_raw["$15.1 million"].state == "accepted"
    assert by_raw["$14.0 million"].state == "skipped" and "no longer in the workbook" in by_raw["$14.0 million"].held_note
    assert any("lost its source" in n for n in plan.notes)


def test_a_changed_metric_heading_sends_the_tie_back_to_the_owner_with_the_reason(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    _book(proj.root, ["Metric", "Q2 2026", "Q3 2026"], [["Total sales", 14_000_000, 15_100_000]])
    plan = proj.plan_refresh()
    states = {t.raw: (t.state, t.held_note) for t in proj.ties()}
    assert all(s == "confirm" for s, _ in states.values()), states
    assert "headings" in states["$15.1 million"][1] and "Net revenue" in states["$15.1 million"][1]
    assert plan.impacts == [] and any("needs you" in n for n in plan.notes)
    for t in proj.ties():
        proj.confirm(t.id)
    assert {t.state for t in proj.ties()} == {"confirmed"}
    _book(proj.root, ["Metric", "Q2 2026", "Q3 2026"], [["Total sales", 14_000_000, 15_900_000]])
    assert {i.old_text: i.new_text for i in proj.plan_refresh().impacts} == {"$15.1 million": "$15.9 million"}


def test_a_current_period_slot_that_is_overwritten_is_followed_not_questioned(tmp_path: Path) -> None:
    root = tmp_path / "p"
    proj = _project(root, ["Metric", "Prior quarter", "Q3 2026"], [["Net revenue", 14_000_000, 15_100_000]], "Net revenue reached $15.1 million in Q3 2026.")
    _book(proj.root, ["Metric", "Prior quarter", "Q4 2026"], [["Net revenue", 15_100_000, 16_400_000]])  # the Q3 column now holds Q4
    plan = proj.plan_refresh()
    assert any("period heading" in n and "Q3 2026" in n and "Q4 2026" in n for n in plan.notes)
    assert {t.state for t in proj.ties()} == {"accepted"}
    assert {i.old_text: i.new_text for i in plan.impacts} == {"$15.1 million": "$16.4 million"}


def test_two_cells_with_the_same_headings_are_never_guessed_between(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Metric", "Q2 2026", "Q3 2026"], [["Net revenue", 14_000_000, 15_100_000]], "Net revenue reached $15.1 million in Q3 2026.")
    _book(proj.root, ["Metric", "Q3 2026", "Q4 2026", "Q3 2026"], [["Net revenue", 15_100_000, 15_300_000, 15_400_000]])  # two other cells now carry the old headings
    plan = proj.plan_refresh()
    t = next(t for t in proj.ties() if t.kind == "text")
    assert t.state == "confirm" and "more than one cell" in t.held_note and plan.impacts == []


def test_a_calculation_follows_its_cells_when_they_move(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _book(proj.root, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"], [["Net revenue", 13_000_000, 14_000_000, 16_000_000]])
    plan = proj.plan_refresh()
    texts = {i.old_text: i.new_text for i in plan.impacts}
    assert texts == {"$15.1 million": "$16.0 million", "7.9%": "14.3%"}
    derived = next(t for t in proj.ties() if t.kind == "derived")
    assert derived.state == "accepted" and '"D2"' in derived.formula and '"C2"' in derived.formula


def test_a_missing_workbook_changes_nothing_and_is_reported_the_old_way(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    (proj.root / "results.xlsx").unlink()
    plan = proj.plan_refresh()
    assert {t.state for t in proj.ties()} == {"accepted"} and plan.impacts == []


def test_the_baseline_follows_the_cell_so_a_shift_is_not_a_false_change_in_a_claim(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"], [["Net revenue", 13_000_000, 14_000_000, 15_100_000]], "Record net revenue of $15.1 million in Q3 2026.")
    _book(proj.root, ["Metric", "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026"], [["Net revenue", 12_000_000, 13_000_000, 14_000_000, 15_100_000]])
    plan = proj.plan_refresh()
    findings, _ = proj.consequences(plan)
    assert plan.impacts == [] and findings == []
    base = proj.snapshot_values()
    assert base[("results.xlsx", "Results", "E2")] == 15_100_000 and base[("results.xlsx", "Results", "B2")] == 12_000_000


def test_renaming_the_sheet_does_not_cut_the_ties(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    with Workbook(str(proj.root / "results.xlsx")) as wb:  # the same data on a sheet with a new name, after a new cover sheet
        wb.add_worksheet("Cover").write(0, 0, "Board pack")
        ws = wb.add_worksheet("Figures")
        ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, 16_000_000])
    plan = proj.plan_refresh()
    assert any("sheet Results is now Figures" in n for n in plan.notes)
    assert {i.old_text: i.new_text for i in plan.impacts} == {"$15.1 million": "$16.0 million"}
    assert {t.sheet for t in proj.ties() if t.kind == "text"} == {"Figures"}


def test_a_sheet_that_split_into_two_look_alikes_is_not_guessed(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    with Workbook(str(proj.root / "results.xlsx")) as wb:
        for name, v in (("North", 16_000_000), ("South", 3_000_000)):
            ws = wb.add_worksheet(name)
            ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
            ws.write_row(1, 0, ["Net revenue", 14_000_000, v])
    plan = proj.plan_refresh()
    assert plan.impacts == []
    assert any("needs you" in n and "2 other sheets" in n for n in plan.notes)
    assert {t.state for t in proj.ties() if t.kind == "text"} == {"confirm"}
