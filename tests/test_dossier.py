"""The release dossier is built from Workroom's own records and says what it cannot prove."""

from pathlib import Path

import pytest

from workroom.tests.test_docx import make_docx
from workroom.tests.test_flagship_headless import change_source, make_workbook
from workroom.workroom_core.service import Service, ServiceError


def published(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "report.docx").write_bytes(make_docx())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    change_source(root, "C2", 150)
    staged = svc.stage(pid)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    return root, svc, pid, staged["release_id"]


def test_the_record_lists_every_change_the_files_the_approval_and_the_limits(tmp_path: Path) -> None:
    root, svc, pid, rid = published(tmp_path)
    record = svc.release_record(pid, rid)
    text, data = record["text"], record["data"]
    assert "120 -> 150" in text and "results.xlsx!Results!C2" in text
    assert data["approved_by"] == "desktop:local-session" and data["channel"] == "desktop" and len(data["digest"]) == 64
    assert data["files"][0]["file"] == "report.docx" and data["files"][0]["before"] != data["files"][0]["after"]
    assert "What this record does not prove" in text and "Restoring" in text
    assert text.count("120 -> 150") == data["changes_total"]


def test_a_restored_release_says_so(tmp_path: Path) -> None:
    root, svc, pid, rid = published(tmp_path)
    svc.restore_release(pid, rid)
    assert svc.release_record(pid, rid)["data"]["restored_at"] is not None
    assert "Restored:" in svc.release_record(pid, rid)["text"]


def test_a_release_that_was_never_published_or_is_not_an_id_has_no_record(tmp_path: Path) -> None:
    root, svc, pid, rid = published(tmp_path)
    change_source(root, "C4", 0.9)
    pending = svc.stage(pid)
    with pytest.raises(ServiceError, match="not published"):
        svc.release_record(pid, pending["release_id"])
    for bad in ("../x", "", "ZZZZZZZZZZZZZZZZ"):
        with pytest.raises(ServiceError, match="not a release id"):
            svc.release_record(pid, bad)


def test_the_record_is_read_only_for_agents() -> None:
    from workroom import TOOLS

    assert {t[4] for t in TOOLS if t[0] == "workroom_release_record"} == {"workroom_ro"}



def test_the_record_carries_restated_figures_and_dashes_that_may_now_hold_a_figure(tmp_path: Path) -> None:
    import json

    root, svc, pid, rid = published(tmp_path)
    meta_path = svc.data_dir / "projects" / pid / "meta" / f"{rid}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["rolled"] = {"restated": ["report.docx slide 1: '12' becomes FY2024, which this report already gave as '15'"]}
    meta["nil_cells"] = ["report.docx: the '-' beside 'Grants' may now hold a figure: 40"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    record = svc.release_record(pid, rid)
    assert "already gave as '15'" in record["text"] and "beside 'Grants'" in record["text"]
    assert record["data"]["restated"] and record["data"]["nil_cells"]
