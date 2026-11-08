import json
from pathlib import Path

import pytest

from workroom.tests.test_commands import staged
from workroom.workroom_core.service import Service, ServiceError
from workroom.workroom_core.store.manifest import MANIFEST_NAME


def published(tmp_path: Path):
    svc, root, pid, st = staged(tmp_path)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    return svc, root, pid


def test_a_healthy_project_reports_ok_and_accepting_is_a_no_op(tmp_path: Path) -> None:
    svc, root, pid = published(tmp_path)
    r = svc.history_review(pid)
    assert r["state"] == "ok" and set(r["counters"].values()) == {1}
    assert svc.accept_history(pid, r["counters"])["state"] == "ok"


def test_a_deleted_manifest_stops_releases_until_the_owner_accepts(tmp_path: Path) -> None:
    svc, root, pid = published(tmp_path)
    (root / MANIFEST_NAME).unlink()
    r = svc.history_review(pid)
    assert r["state"] == "recovery" and r["counters"] == {"manifest": 0, "anchor": 1, "journal": 1}
    with pytest.raises(ServiceError, match="recovery mode"):
        svc.stage(pid)
    done = svc.accept_history(pid, r["counters"])
    assert done["state"] == "ok" and set(done["counters"].values()) == {1}
    entries = json.loads((root / MANIFEST_NAME).read_text())["entries"]
    assert entries[-1]["kind"] == "recovered" and entries[-1]["data"]["seen"] == r["counters"]
    assert svc.history_review(pid)["state"] == "ok"


def test_an_altered_manifest_is_kept_aside_and_replaced(tmp_path: Path) -> None:
    svc, root, pid = published(tmp_path)
    doc = json.loads((root / MANIFEST_NAME).read_text())
    doc["entries"][0]["data"]["tampered"] = True
    (root / MANIFEST_NAME).write_text(json.dumps(doc))
    r = svc.history_review(pid)
    assert r["state"] == "recovery" and r["counters"] is None and "altered" in r["reason"]
    svc.accept_history(pid, None)
    assert list(root.glob(MANIFEST_NAME + ".damaged-*"))
    assert svc.history_review(pid)["state"] == "ok"


def test_accepting_what_the_owner_did_not_see_is_refused(tmp_path: Path) -> None:
    svc, root, pid = published(tmp_path)
    (root / MANIFEST_NAME).unlink()
    with pytest.raises(ServiceError, match="changed since you reviewed"):
        svc.accept_history(pid, {"manifest": 5, "anchor": 5, "journal": 5})
    assert svc.history_review(pid)["state"] == "recovery"


def test_the_next_release_works_after_recovery(tmp_path: Path) -> None:
    from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell

    svc, root, pid = published(tmp_path)
    (root / MANIFEST_NAME).unlink()
    svc.accept_history(pid, svc.history_review(pid)["counters"])
    src = root / "data" / "data.xlsx"
    src.write_bytes(patch_numeric_cell(src.read_bytes(), "Results", "C2", 190))
    st = svc.stage(pid)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    assert set(svc.history_review(pid)["counters"].values()) == {2}


def test_a_published_release_can_be_restored_and_released_again(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    svc, root, pid = published(tmp_path)
    assert load_workbook(root / "report.xlsx").active["C2"].value == 150
    [rel] = svc.releases(pid)
    assert rel["restored"] is False and rel["changes"] and rel["published_at"]
    out = svc.restore_release(pid, rel["release_id"])
    assert out["state"] == "restored"
    assert load_workbook(root / "report.xlsx").active["C2"].value == 120  # the file as it was before the release
    assert svc.releases(pid)[0]["restored"] is True
    assert svc.history_review(pid)["state"] == "ok"  # a restore never trips recovery mode
    again = svc.plan(pid)["changes"]
    assert [c["new_text"] for c in again] == ["150"]  # the deck is behind its source again, so the change is offered again
    st = svc.stage(pid)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    assert load_workbook(root / "report.xlsx").active["C2"].value == 150


def test_restore_is_refused_when_the_file_changed_after_the_release(tmp_path: Path) -> None:
    from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell

    svc, root, pid = published(tmp_path)
    report = root / "report.xlsx"
    report.write_bytes(patch_numeric_cell(report.read_bytes(), "Results", "B2", 999))  # someone kept working in it
    [rel] = svc.releases(pid)
    with pytest.raises(ServiceError, match="not restored"):
        svc.restore_release(pid, rel["release_id"])
    from openpyxl import load_workbook

    assert load_workbook(report).active["B2"].value == 999  # their work was not overwritten
