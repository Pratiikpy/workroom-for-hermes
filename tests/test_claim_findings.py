"""What an update means for the sentences around the numbers."""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.project import Project


def _sources(root: Path, **cells: float) -> None:
    values = {"q1": 13_000_000, "q2": 14_000_000, "q3": 15_100_000, "q4": 12_000_000, **cells}
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026", "Q4 2025"])
        ws.write_row(1, 0, ["Net revenue", values["q1"], values["q2"], values["q3"], values["q4"]])


def _project(tmp_path: Path, sentence: str, **start: float) -> Project:
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    _sources(root, **start)
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = sentence
    prs.save(str(root / "board.pptx"))
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


UP_FROM = "Net revenue reached $15.1 million in Q3 2026, up from $14.0 million in Q2 2026."


def test_a_comparison_that_stops_being_true_is_a_high_finding(tmp_path: Path) -> None:
    proj = _project(tmp_path, UP_FROM)
    _sources(proj.root, q3=13_000_000)
    findings, cov = proj.consequences(proj.plan_refresh())
    assert [f.kind for f in findings] == ["claim_flip"] and findings[0].severity == "high"
    assert "$13.0 million" in findings[0].sentence_after and "up from" in findings[0].summary
    assert findings[0].suggestion.endswith('"down" in place of "up".') and cov.claims_read == 1
    assert findings[0].summary == '"$15.1 million in Q3 2026, up from $14.0 million" was true and is not true after this update', "the owner's own words, never the internal token form"
    assert not any(ch in findings[0].summary + "".join(findings[0].evidence) for ch in "⟦⟧⟪⟫")


def test_a_comparison_that_still_holds_raises_nothing(tmp_path: Path) -> None:
    proj = _project(tmp_path, UP_FROM)
    _sources(proj.root, q3=15_900_000)
    findings, _ = proj.consequences(proj.plan_refresh())
    assert findings == []


def test_a_record_that_a_restated_earlier_period_breaks_is_found_even_though_the_sentence_did_not_change(tmp_path: Path) -> None:
    proj = _project(tmp_path, "Record net revenue of $15.1 million in Q3 2026.")
    _sources(proj.root, q2=15_500_000)  # an earlier quarter is restated above this one; the sentence's own number is unchanged
    plan = proj.plan_refresh()
    findings, _ = proj.consequences(plan)
    assert [f.kind for f in findings] == ["record_flip"] and findings[0].severity == "high"
    assert "Q2 2026 Net revenue 15,500,000" in " ".join(findings[0].evidence) and "Q3 2026 Net revenue: 15,100,000" in " ".join(findings[0].evidence)


def _two_baselines(tmp_path: Path, q3: float) -> Project:
    root = tmp_path / "proj"
    root.mkdir(parents=True)
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q3 2025", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, 13_000_000, q3])
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = "Net revenue grew to $15.1 million in Q3 2026."
    prs.save(str(root / "board.pptx"))
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


def test_a_direction_against_an_unnamed_baseline_is_flagged_only_when_every_baseline_disagrees(tmp_path: Path) -> None:
    both_fail = _two_baselines(tmp_path / "a", 15_100_000)
    with Workbook(str(both_fail.root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q3 2025", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, 13_000_000, 12_000_000])
    findings, _ = both_fail.consequences(both_fail.plan_refresh())
    assert [f.kind for f in findings] == ["baseline_flip"] and findings[0].severity == "medium"
    assert "Q2 2026" in " ".join(findings[0].evidence) and "Q3 2025" in " ".join(findings[0].evidence)

    one_holds = _two_baselines(tmp_path / "b", 15_100_000)
    with Workbook(str(one_holds.root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q3 2025", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, 13_000_000, 13_500_000])  # below the year earlier, above the previous quarter
    assert one_holds.consequences(one_holds.plan_refresh())[0] == [], "a claim that holds against one plausible baseline is not flagged"


def test_a_claim_about_a_figure_with_no_source_is_reported_as_not_checked(tmp_path: Path) -> None:
    proj = _project(tmp_path, "Net revenue reached $15.1 million in Q3 2026. Headcount grew to 241.")
    _sources(proj.root, q3=13_000_000)
    findings, cov = proj.consequences(proj.plan_refresh())
    assert [f.kind for f in findings] == ["untied_figure"] and "241" in findings[0].summary and findings[0].severity == "medium"
    assert [n for n in cov.not_checked if "241" in n and "not tied to a source cell" in n], cov.not_checked


def test_loss_wording_is_declined_not_guessed(tmp_path: Path) -> None:
    proj = _project(tmp_path, "Net revenue reached $15.1 million, up from a loss-making $14.0 million in Q2 2026.")
    _sources(proj.root, q3=13_000_000)
    findings, cov = proj.consequences(proj.plan_refresh())
    assert findings == [] and any("loss" in n for n in cov.not_checked)


def test_finding_ids_are_stable_for_the_same_sentence_and_outcome(tmp_path: Path) -> None:
    a = _project(tmp_path / "a", UP_FROM)
    _sources(a.root, q3=13_000_000)
    b = _project(tmp_path / "b", UP_FROM)
    _sources(b.root, q3=13_000_000)
    assert a.consequences(a.plan_refresh())[0][0].id == b.consequences(b.plan_refresh())[0][0].id
