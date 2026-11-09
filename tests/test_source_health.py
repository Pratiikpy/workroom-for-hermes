"""Source health: a workbook that lost part of itself, or a cell that moved by orders of magnitude, is raised before a release can be approved."""
from pathlib import Path

from xlsxwriter import Workbook

from workroom.tests.test_calculations import _deck, _project
from workroom.workroom_core.project import Project

LINES = ["Net revenue was $14.0 million in Q2 2026.", "Operating income was $2.2 million in Q2 2026."]


def _workbook(root: Path, revenue: float, income: float | None = 2_210_000) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1 2026", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 13_000_000, revenue, 15_100_000])
        if income is not None:
            ws.write_row(2, 0, ["Operating income", 1_850_000, income, 2_640_000])


def _kinds(proj: Project) -> dict[str, list]:
    found, _ = proj.consequences(proj.plan_refresh())
    out: dict[str, list] = {}
    for f in found:
        out.setdefault(f.kind, []).append(f)
    return out


def test_a_figure_that_lost_its_cell_while_others_update_is_raised_as_an_incomplete_source(tmp_path: Path) -> None:
    proj = _project(tmp_path, LINES)
    assert len([t for t in proj.ties() if t.state in ("accepted", "confirmed")]) == 2
    _workbook(proj.root, 15_000_000, income=None)
    found = _kinds(proj)["source_incomplete"]
    assert len(found) == 1 and found[0].severity == "high"
    assert "1 of 2 figures" in found[0].summary and "results.xlsx" in found[0].summary
    assert any("Operating income" in x or "$2.2 million" in x for x in found[0].evidence)
    assert "mix new and old numbers" in found[0].suggestion


def test_an_untouched_complete_source_raises_nothing(tmp_path: Path) -> None:
    proj = _project(tmp_path, LINES)
    _workbook(proj.root, 15_000_000)
    kinds = _kinds(proj)
    assert "source_incomplete" not in kinds and "source_implausible" not in kinds


def test_a_cell_that_moves_by_two_orders_of_magnitude_is_raised(tmp_path: Path) -> None:
    proj = _project(tmp_path, LINES)
    _workbook(proj.root, 14_000_000_000)  # a thousand times: the classic unit slip
    found = _kinds(proj)["source_implausible"]
    assert len(found) == 1 and found[0].severity == "high" and "factor of 1,000" in found[0].summary


def test_a_cell_that_becomes_zero_is_raised_but_a_modest_move_is_not(tmp_path: Path) -> None:
    proj = _project(tmp_path, LINES)
    _workbook(proj.root, 0)
    assert "became zero" in _kinds(proj)["source_implausible"][0].summary
    _workbook(proj.root, 20_000_000)
    assert "source_implausible" not in _kinds(proj)


def test_a_high_source_finding_must_be_acknowledged_before_the_release_is_approved(tmp_path: Path) -> None:
    from workroom.workroom_core.service import NeedsAcknowledgement, Service

    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root, 14_000_000)
    _deck(root, LINES)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    _workbook(root, 14_000_000_000)
    staged = svc.stage(pid)
    assert [f["kind"] for f in staged["flags"]] == ["source_implausible"]
    assert svc.release_view(pid, staged["release_id"])["needs_acknowledgement"] == [staged["flags"][0]["id"]]
    try:
        svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    except NeedsAcknowledgement as exc:
        assert any(f["kind"] == "source_implausible" for f in exc.flags)
    else:
        raise AssertionError("the release was approved without the owner acknowledging the source finding")
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
