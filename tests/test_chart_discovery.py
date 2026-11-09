"""Charts that already sit in a deck are linked to the workbook behind them, and follow it."""
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.project import Project

QUARTERS = ["Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"]
REVENUE = [12.5, 14.0, 15.1, 16.2]
COSTS = [8.1, 8.9, 9.4, 9.9]


def _workbook(root: Path, revenue=REVENUE, costs=COSTS) -> None:
    with Workbook(str(root / "model.xlsx")) as wb:
        ws = wb.add_worksheet("Model")
        ws.write_row(0, 0, ["Quarter", "Revenue", "Operating costs"])
        for i, q in enumerate(QUARTERS, 1):
            ws.write_row(i, 0, [q, revenue[i - 1], costs[i - 1]])


def _deck(root: Path, title: str = "Revenue and costs by quarter") -> None:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title
    data = CategoryChartData()
    data.categories = QUARTERS
    data.add_series("Revenue", REVENUE)
    data.add_series("Operating costs", COSTS)
    slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(1.5), Inches(8), Inches(4.5), data)
    prs.save(str(root / "board.pptx"))


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root)
    _deck(root)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj


def _values(root: Path) -> dict[str, list[float]]:
    chart = next(sh.chart for sh in Presentation(str(root / "board.pptx")).slides[0].shapes if sh.has_chart)
    return {s.name: list(s.values) for s in chart.plots[0].series}


def test_the_points_of_an_existing_chart_are_linked_to_their_cells(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    charts = [t for t in proj.ties() if t.kind == "chart"]
    assert len(charts) == 8
    assert all(t.state == "accepted" for t in charts)
    refs = {(t.chart and __import__("json").loads(t.chart)["series"], __import__("json").loads(t.chart)["category"]): t.ref for t in charts}
    assert refs[(0, "Q3 2026")] == "B4" and refs[(1, "Q1 2026")] == "C2"


def test_a_changed_source_value_reaches_the_chart_and_its_workbook(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    _workbook(proj.root, revenue=[12.5, 14.0, 15.9, 16.2])
    plan = proj.plan_refresh()
    assert [(i.old_text, i.new_text) for i in plan.impacts] == [("15.1", "15.9")]
    assert plan.files and not plan.skipped
    (proj.root / "board.pptx").write_bytes(plan.files["board.pptx"])
    assert _values(proj.root) == {"Revenue": [12.5, 14.0, 15.9, 16.2], "Operating costs": COSTS}
    proj.commit_snapshot(plan)
    again = Project(proj.root, tmp_path / "state")
    again.discover()
    assert again.plan_refresh().impacts == []


def test_a_chart_point_nothing_names_is_not_linked(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    with Workbook(str(root / "model.xlsx")) as wb:  # the same numbers, but nothing says which are revenue
        ws = wb.add_worksheet("Sheet1")
        for i, (a, b) in enumerate(zip(REVENUE, COSTS)):
            ws.write_row(i, 0, [a, b])
    _deck(root)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    assert [t for t in proj.ties() if t.kind == "chart" and t.state == "accepted"] == []


def test_a_chart_the_person_edited_is_left_alone(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    prs = Presentation(str(proj.root / "board.pptx"))
    chart = next(sh.chart for sh in prs.slides[0].shapes if sh.has_chart)
    data = CategoryChartData()
    data.categories = QUARTERS
    data.add_series("Revenue", [12.5, 14.0, 99.0, 16.2])
    data.add_series("Operating costs", COSTS)
    chart.replace_data(data)
    prs.save(str(proj.root / "board.pptx"))
    _workbook(proj.root, revenue=[12.5, 14.0, 15.9, 16.2])
    plan = proj.plan_refresh()
    assert all(i.new_text != "15.9" for i in plan.impacts)


def test_a_value_with_many_decimals_is_not_blocked_by_the_label_rounding(tmp_path: Path) -> None:
    from workroom.workroom_core.service import Service

    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root)
    _deck(root)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    _workbook(root, revenue=[12.5, 14.0, 15.123456789012345, 16.2])
    svc.discover(pid)
    staged = svc.stage(pid)
    assert staged["state"] == "awaiting_approval" and staged["digest"]
