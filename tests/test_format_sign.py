"""A rewritten number keeps the sign style it was written in, including a plus that stands outside the number."""
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.match.numbers import format_like, parse_numbers
from workroom.workroom_core.project import Project


@pytest.mark.parametrize("old,value,transform,expected", [
    ("-3.0%", 0.012, "fraction_to_percent", "+1.2%"), ("-3.0%", -0.025, "fraction_to_percent", "-2.5%"), ("1.2%", 0.034, "fraction_to_percent", "3.4%"),
    ("1.2%", -0.034, "fraction_to_percent", "-3.4%"), ("(3.0%)", 0.012, "fraction_to_percent", "1.2%"), ("(3.0%)", -0.025, "fraction_to_percent", "(2.5%)"),
    ("-$1.2M", 2_500_000, "millions", "+$2.5M"), ("-$1.2M", -2_500_000, "millions", "-$2.5M"), ("-3.0%", 0.00001, "fraction_to_percent", "0.0%"),
])
def test_sign_style(old: str, value: float, transform: str, expected: str) -> None:
    assert format_like(parse_numbers(old)[0], value, transform) == expected


def _growth_project(tmp_path: Path, shown: str) -> Project:
    root = tmp_path / "proj"
    root.mkdir()
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Revenue growth", 0.05, 0.079])
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = f"Revenue growth in Q3 2026 was {shown} against the plan."
    prs.save(str(root / "board.pptx"))
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


def _set_growth(proj: Project, value: float) -> None:
    with Workbook(str(proj.root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Revenue growth", 0.05, value])


def test_a_plus_that_stands_outside_the_number_goes_with_it_when_the_value_turns_negative(tmp_path: Path) -> None:
    proj = _growth_project(tmp_path, "+7.9%")
    assert [t.raw for t in proj.ties()] == ["7.9%"]
    _set_growth(proj, -0.031)
    plan = proj.plan_refresh()
    assert [(i.old_text, i.new_text) for i in plan.impacts] == [("7.9%", "-3.1%")]
    data = plan.files["board.pptx"]
    text = " ".join(sh.text_frame.text for sh in Presentation(__import__("io").BytesIO(data)).slides[0].shapes if sh.has_text_frame)
    assert "was -3.1% against" in text and "+-" not in text


def test_a_plus_stays_when_the_value_stays_positive(tmp_path: Path) -> None:
    proj = _growth_project(tmp_path, "+7.9%")
    _set_growth(proj, 0.034)
    data = proj.plan_refresh().files["board.pptx"]
    text = " ".join(sh.text_frame.text for sh in Presentation(__import__("io").BytesIO(data)).slides[0].shapes if sh.has_text_frame)
    assert "was +3.4% against" in text
