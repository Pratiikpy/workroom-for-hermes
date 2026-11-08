"""Numbers in places the editor does not rewrite, and charts whose axes would clip a new value."""
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.meaning.surfaces import clipped_charts
from workroom.workroom_core.project import Plan, Project


def _sources(root: Path, q3: float) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, q3])


def _deck_with_hidden_numbers(root: Path) -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = "Net revenue was $15.1 million in Q3 2026."
    slide.notes_slide.notes_text_frame.text = "Say: net revenue hit $15.1 million this quarter, our best result."
    pic = slide.shapes.add_textbox(Inches(0.5), Inches(3), Inches(2), Inches(1))
    pic._element.nvSpPr.cNvPr.set("descr", "Headcount grew to 241 people")
    prs.save(str(root / "board.pptx"))


def test_a_number_in_the_speaker_notes_that_matches_the_old_value_is_reported_not_rewritten(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, 15_100_000)
    _deck_with_hidden_numbers(root)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    _sources(root, 13_000_000)
    plan = proj.plan_refresh()
    findings, _ = proj.consequences(plan)
    stale = [f for f in findings if f.kind == "stale_mention"]
    assert len(stale) == 1 and stale[0].severity == "medium" and "speaker notes" in stale[0].summary and "$15.1 million" in stale[0].summary
    assert "Net revenue" in stale[0].summary or "revenue" in stale[0].summary.lower()
    assert not any("241" in f.summary for f in findings), "a number that matches no changed cell is left alone"


def test_nothing_is_reported_when_the_hidden_number_already_shows_the_new_value(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, 15_100_000)
    _deck_with_hidden_numbers(root)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    _sources(root, 15_100_000)
    assert [f for f in proj.consequences(proj.plan_refresh())[0] if f.kind == "stale_mention"] == []


def _chart_deck(top: float | None, value: float) -> bytes:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    data = CategoryChartData()
    data.categories = ["Q2 2026", "Q3 2026"]
    data.add_series("Net revenue", (14.0, value))
    chart = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1.5), Inches(6), Inches(4), data).chart
    if top is not None:
        chart.value_axis.maximum_scale = top
    path = Path(__file__).parent / "_axis_tmp.pptx"
    prs.save(str(path))
    try:
        return path.read_bytes()
    finally:
        path.unlink()


def test_a_fixed_axis_that_a_new_value_would_exceed_is_a_high_finding(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    proj = Project(root, tmp_path / "state")
    findings = clipped_charts(proj, Plan(files={"c.pptx": _chart_deck(15.0, 15.8)}))
    assert len(findings) == 1 and findings[0].kind == "chart_axis_clipped" and findings[0].severity == "high"
    assert "maximum 15" in findings[0].summary and "Q3 2026" in findings[0].summary


def test_an_automatic_axis_or_a_value_inside_the_limit_raises_nothing(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    proj = Project(root, tmp_path / "state")
    assert clipped_charts(proj, Plan(files={"c.pptx": _chart_deck(None, 99.0)})) == []
    assert clipped_charts(proj, Plan(files={"c.pptx": _chart_deck(20.0, 15.8)})) == []


def test_a_stale_note_stays_reported_every_cycle_until_the_owner_changes_it(tmp_path: Path) -> None:
    from workroom.workroom_core.service import NeedsAcknowledgement, Service

    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, 15_100_000)
    _deck_with_hidden_numbers(root)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)

    def release(q3: float) -> list[dict]:
        _sources(root, q3)
        staged = svc.stage(pid)
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
        return [f for f in staged["flags"] if f["kind"] == "stale_mention"]

    assert len(release(13_000_000)) == 1
    again = release(12_000_000)  # the note still says $15.1 million, which is not the value that just changed
    assert len(again) == 1 and "$15.1 million" in again[0]["summary"], "the open item carries forward"
    prs = Presentation(root / "board.pptx")
    prs.slides[0].notes_slide.notes_text_frame.text = "Say: net revenue was $12.0 million this quarter."
    prs.save(str(root / "board.pptx"))
    svc.discover(pid)
    after = release(11_000_000)
    assert all("$15.1 million" not in f["summary"] for f in after), "once the owner changes the note, the old item is no longer reported"
    assert len(after) == 1 and "$12.0 million" in after[0]["summary"], "the note now holds the value that has just been superseded, which is its own new finding"
