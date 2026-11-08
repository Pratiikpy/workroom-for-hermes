"""First run: a sample project shows the whole loop without touching the user's files."""
from pathlib import Path

from openpyxl import load_workbook
from pptx import Presentation

from workroom.workroom_core.service import Service


def test_the_sample_creates_a_project_inside_workroom_own_data_and_stages_a_deck(tmp_path: Path) -> None:
    svc = Service(tmp_path / "state")
    out = svc.create_sample()
    assert out["state"] == "awaiting_approval" and out["figures"]
    folder = Path(svc.projects()[0]["folder"])
    assert (tmp_path / "state") in folder.parents, "the sample lives in Workroom's own storage, never in the user's folders"
    assert (folder / "results.xlsx").is_file() and not (folder / "board-update.pptx").exists()
    svc.approve_and_publish(out["project"], out["release_id"], out["digest"])
    assert (folder / "board-update.pptx").is_file()
    prs = Presentation(folder / "board-update.pptx")
    assert any("Revenue" in sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)


def test_the_sample_can_simulate_a_new_quarter_and_the_inbox_shows_it(tmp_path: Path) -> None:
    svc = Service(tmp_path / "state")
    out = svc.create_sample()
    svc.approve_and_publish(out["project"], out["release_id"], out["digest"])
    assert svc.changes_inbox(out["project"])["changes"] == []
    svc.sample_next_quarter(out["project"])
    inbox = svc.changes_inbox(out["project"])
    assert inbox["changes"] and inbox["changes"][0]["counts"]["auto"] >= 1
    upd = svc.stage(out["project"])
    svc.approve_and_publish(out["project"], upd["release_id"], upd["digest"])
    assert svc.changes_inbox(out["project"])["changes"] == []


def test_the_sample_is_idempotent_and_the_simulation_refuses_other_projects(tmp_path: Path) -> None:
    import pytest

    from workroom.workroom_core.service import ServiceError

    svc = Service(tmp_path / "state")
    a = svc.create_sample()
    svc.approve_and_publish(a["project"], a["release_id"], a["digest"])
    b = svc.create_sample()
    assert b["project"] == a["project"] and b["state"] in ("exists", "awaiting_approval")
    other = tmp_path / "mine"
    other.mkdir()
    pid = svc.add_project(str(other))["project"]
    with pytest.raises(ServiceError):
        svc.sample_next_quarter(pid)
