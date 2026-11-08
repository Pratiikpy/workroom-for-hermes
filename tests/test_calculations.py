"""Calculated numbers: found by arithmetic, accepted by the owner, kept in step, and never silently turned over."""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.project import Project


def _sources(root: Path, q2: float, q3: float, q1: float = 13_000_000) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", q1, q2, q3])
        ws.write_row(2, 0, ["Operating income", 1_850_000, 2_210_000, 2_640_000])


def _deck(root: Path, lines: list[str]) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Quarterly business review"
    for i, line in enumerate(lines):
        box = slide.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8))
        box.text_frame.text = line
    prs.save(str(root / "board.pptx"))


def _project(tmp_path: Path, lines: list[str], q2: float = 14_000_000, q3: float = 15_100_000) -> Project:
    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, q2, q3)
    _deck(root, lines)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


SENTENCE = "Net revenue reached $15.1 million in Q3 2026, up 7.9% from $14.0 million in Q2 2026."


def test_a_percent_change_is_found_with_its_formula_and_certainty(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    scan = proj.calculations()
    assert len(scan.candidates) == 1
    c = scan.candidates[0]
    assert c.raw.startswith("7.9%") and c.certainty == "certain" and c.scope == "paragraph"
    assert len(c.options) == 1 and c.options[0].op == "pct_change" and "Net revenue" in c.options[0].words()


def test_an_accepted_calculation_follows_its_sources_and_is_released_with_them(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _sources(proj.root, 14_000_000, 15_800_000)
    plan = proj.plan_refresh()
    texts = {i.old_text: i.new_text for i in plan.impacts}
    assert texts["7.9%"] == "12.9%" and texts["$15.1 million"] == "$15.8 million"
    assert "$14.0 million" not in texts, "the unchanged figure is not touched"


def test_a_change_that_turns_over_is_held_not_rewritten(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _sources(proj.root, 14_000_000, 13_000_000)
    plan = proj.plan_refresh()
    assert {i.old_text for i in plan.impacts} == {"$15.1 million"}, "the number is updated, the 'up 7.9%' is not"
    assert any("direction has turned over" in s and "7.9%" in s for s in plan.skipped)
    inbox = proj.impact()
    held = [e for c in inbox.changes for e in c.elements if e.decision == "hold" and e.text_before == "7.9%"]
    assert held and "direction" in held[0].reason


def test_two_readings_are_never_chosen_for_the_owner(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    with Workbook(str(root / "results.xlsx")) as wb:  # q3 is exactly 10% above q2 and exactly 10% above the year earlier: two baselines give 10%
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q3 2025", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 10_000_000, 10_000_000, 11_000_000])
    _deck(root, ["Net revenue reached $11.0 million in Q3 2026, up 10.0%."])
    proj = Project(root, tmp_path / "state")
    proj.discover()
    cands = proj.calculations().candidates
    assert len(cands) == 1 and cands[0].certainty == "ask" and len(cands[0].options) == 2
    assert {o.terms[1].role for o in cands[0].options} == {"previous", "year_ago"}


def test_a_figure_no_calculation_reproduces_is_reported_not_guessed(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $15.1 million in Q3 2026, up 9.4% from $14.0 million in Q2 2026."])
    scan = proj.calculations()
    assert scan.candidates == [] and scan.unexplained[0]["figure"].startswith("9.4%")


def test_a_dismissed_calculation_is_not_offered_again(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.dismiss_calculation(proj.calculations().candidates[0].id)
    scan = proj.calculations()
    assert scan.candidates == [] and scan.dismissed == 1


def test_rediscovery_keeps_an_accepted_calculation(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    before = [(t.id, t.kind, t.raw) for t in proj.ties() if t.kind == "derived"]
    proj.discover()
    assert [(t.id, t.kind, t.raw) for t in proj.ties() if t.kind == "derived"] == before


def test_a_difference_is_found(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Operating income of $2.6 million is $0.4 million above Q2 2026 ($2.2 million)."])
    figs = {c.raw: c for c in proj.calculations().candidates}
    assert any(o.op == "diff" for o in figs["$0.4 million"].options)


def test_a_calculated_figure_is_its_own_group_in_the_inbox_in_percent_not_in_cell_units(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _sources(proj.root, 14_000_000, 13_000_000)
    groups = {c.kind: c for c in proj.impact().changes}
    assert set(groups) == {"source", "calculation"}
    src, calc = groups["source"], groups["calculation"]
    assert (src.old_value, src.new_value, src.unit) == (15_100_000, 13_000_000, "")
    assert calc.unit == "%" and round(calc.old_value, 2) == 7.86 and round(calc.new_value, 2) == -7.14
    assert "Net revenue" in calc.label and [e.decision for e in calc.elements] == ["hold"]


def test_a_calculation_that_turned_over_is_reported_in_percent_words(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _sources(proj.root, 14_000_000, 13_000_000)
    findings, _ = proj.consequences(proj.plan_refresh())
    turned = [f for f in findings if f.kind == "calculated_turned_over"]
    assert len(turned) == 1 and turned[0].evidence == ("It was +7.9% and would now be -7.1%",)
