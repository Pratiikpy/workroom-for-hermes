"""Editing a visual page: drafts live outside the project, ops are re-validated on the server, saving stages a normal release."""
import json
from pathlib import Path

import pytest

from workroom.tests.test_scene_flow import SPEC, _scene
from workroom.tests.test_create_flow import _svc, _workbook
from workroom.workroom_core.service import ServiceError


def _published(tmp_path: Path):
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    return svc, pid, root


def test_open_returns_the_scene_and_a_revision(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    out = svc.scene_open(pid, "pages/q2.scene.json")
    assert out["rev"] == 0 and [n["id"] for n in out["scene"]["nodes"]] == ["bg", "title", "kpi"]


def test_apply_changes_only_the_draft_never_the_project_file(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    before = (root / "pages/q2.scene.json").read_bytes()
    out = svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 120}}])
    assert out["rev"] == 1 and out["scene"]["nodes"][1]["x"] == 120
    assert (root / "pages/q2.scene.json").read_bytes() == before
    assert svc.scene_open(pid, "pages/q2.scene.json")["scene"]["nodes"][1]["x"] == 120, "the draft survives reopening"


def test_apply_rejects_bad_ops_and_stale_revisions_without_changing_the_draft(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    with pytest.raises(ServiceError):
        svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"w": -5}}])
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 1}}])
    with pytest.raises(ServiceError):
        svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 2}}])
    assert svc.scene_open(pid, "pages/q2.scene.json")["scene"]["nodes"][1]["x"] == 1


def test_only_scene_files_inside_the_project_can_be_opened(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    for bad in ("../x.scene.json", "results.xlsx", "/etc/passwd", "pages/missing.scene.json", "pages\\q2.scene.json"):
        with pytest.raises(ServiceError):
            svc.scene_open(pid, bad)


def test_save_stages_an_ordinary_update_release_that_the_owner_approves(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 200}},
                                                    {"op": "add", "node": {"id": "n9", "type": "rect", "x": 5, "y": 5, "w": 40, "h": 40, "fill": "2563EB"}}])
    staged = svc.scene_save(pid, "pages/q2.scene.json")
    assert staged["state"] == "awaiting_approval" and staged["changes"][0]["deck"] == "pages/q2.scene.json"
    assert next(n for n in _scene(root)["nodes"] if n["id"] == "title")["x"] == 80, "nothing is written before approval"
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    doc = _scene(root)
    assert next(n for n in doc["nodes"] if n["id"] == "title")["x"] == 200 and doc["nodes"][-1]["id"] == "n9"
    assert len(svc.ties(pid)) == 2, "the tied text keeps its ties through an edit release"
    _workbook(root, 190)
    assert svc.changes_inbox(pid)["changes"][0]["counts"]["auto"] == 1
    svc.restore_release(pid, staged["release_id"])
    assert next(n for n in _scene(root)["nodes"] if n["id"] == "title")["x"] == 80


def test_save_is_refused_when_the_file_changed_since_the_draft_began(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 3}}])
    doc = _scene(root)
    doc["nodes"][1]["x"] = 999
    (root / "pages/q2.scene.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ServiceError, match="changed"):
        svc.scene_save(pid, "pages/q2.scene.json")


def test_discard_drops_the_draft(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 3}}])
    svc.scene_discard(pid, "pages/q2.scene.json")
    assert svc.scene_open(pid, "pages/q2.scene.json")["scene"]["nodes"][1]["x"] == 80


@pytest.mark.parametrize("fmt,ext", [("svg", ".svg"), ("html", ".html"), ("pptx", ".pptx")])
def test_an_export_is_staged_as_a_release_and_written_only_after_approval(tmp_path: Path, fmt: str, ext: str) -> None:
    svc, pid, root = _published(tmp_path)
    staged = svc.scene_export(pid, "pages/q2.scene.json", fmt)
    target = "pages/q2" + ext
    assert staged["state"] == "awaiting_approval" and staged["changes"][0]["deck"] == target
    assert not (root / target).exists()
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    data = (root / target).read_bytes()
    assert data and (fmt != "pptx" or data[:2] == b"PK") and (fmt == "pptx" or b"Q2 revenue $175" in data)
    # exporting again after an edit updates the file in place
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"text": "Changed"}}])
    svc.scene_save_and_publish_for_test = None
    again = svc.scene_export(pid, "pages/q2.scene.json", fmt)
    assert again["state"] == "awaiting_approval"


def test_unknown_export_formats_are_refused(tmp_path: Path) -> None:
    svc, pid, root = _published(tmp_path)
    with pytest.raises(ServiceError):
        svc.scene_export(pid, "pages/q2.scene.json", "exe")
