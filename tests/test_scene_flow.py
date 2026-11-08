"""A visual page created from a spec carries tied text, follows its sources through a release, and restores like any other file."""
import json
from pathlib import Path

from workroom.tests.test_create_flow import _svc, _workbook
from workroom.workroom_core.scene.model import validate_scene

SPEC = {
    "version": 1, "kind": "scene", "path": "pages/q2.scene.json",
    "facts": {
        "rev": {"ref": "results.xlsx!Results!C2", "concept": "Revenue", "period": "Q2", "unit": "currency"},
        "mar": {"ref": "results.xlsx!Results!C3", "concept": "Margin", "period": "Q2", "unit": "percent"},
    },
    "scene": {"version": 1, "canvas": {"w": 1280, "h": 720}, "nodes": [
        {"id": "bg", "type": "rect", "x": 0, "y": 0, "w": 1280, "h": 720, "fill": "F8FAFC"},
        {"id": "title", "type": "text", "x": 80, "y": 60, "w": 900, "h": 60, "text": "Q2 results", "size": 36, "bold": True},
        {"id": "kpi", "type": "text", "x": 80, "y": 200, "w": 500, "h": 100, "text": "Q2 revenue {rev:$#,##0} at a {mar:0.0%} margin", "size": 28},
    ]},
}


def _scene(root: Path) -> dict:
    return json.loads((root / "pages/q2.scene.json").read_text(encoding="utf-8"))


def test_a_scene_is_created_with_tied_text_and_follows_the_source(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, SPEC)
    assert staged["state"] == "awaiting_approval", staged
    assert len(staged["figures"]) == 2 and not (root / "pages").exists()
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    doc = _scene(root)
    assert validate_scene(doc) == []
    kpi = next(n for n in doc["nodes"] if n["id"] == "kpi")
    assert kpi["text"] == "Q2 revenue $175 at a 30.0% margin" and "{rev" in kpi["template"]
    assert len(svc.ties(pid)) == 2

    _workbook(root, 190)
    inbox = svc.changes_inbox(pid)
    assert inbox["changes"][0]["counts"]["auto"] == 1 and "kpi" in inbox["changes"][0]["elements"][0]["where"]
    upd = svc.stage(pid)
    assert upd["state"] == "awaiting_approval", upd
    svc.approve_and_publish(pid, upd["release_id"], upd["digest"])
    doc = _scene(root)
    assert next(n for n in doc["nodes"] if n["id"] == "kpi")["text"] == "Q2 revenue $190 at a 30.0% margin"
    assert next(n for n in doc["nodes"] if n["id"] == "title")["text"] == "Q2 results"
    assert [n["id"] for n in doc["nodes"]] == ["bg", "title", "kpi"]
    assert svc.plan(pid)["changes"] == []
    svc.discover(pid)
    assert len(svc.ties(pid)) == 2, "finding links again must keep the scene ties"

    svc.restore_release(pid, upd["release_id"])
    assert next(n for n in _scene(root)["nodes"] if n["id"] == "kpi")["text"] == "Q2 revenue $175 at a 30.0% margin"
    svc.restore_release(pid, staged["release_id"])
    assert not (root / "pages/q2.scene.json").exists() and svc.ties(pid) == []


def test_a_scene_text_that_was_edited_by_hand_is_held(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    doc = _scene(root)
    for n in doc["nodes"]:
        if n["id"] == "kpi":
            n["text"] = "Q2 revenue $175 at a 30.0% margin, which we are proud of"
    (root / "pages/q2.scene.json").write_text(json.dumps(doc), encoding="utf-8")
    _workbook(root, 190)
    el = svc.changes_inbox(pid)["changes"][0]["elements"][0]
    assert el["decision"] == "hold" and "by hand" in el["reason"]


def test_an_invalid_scene_in_a_spec_is_refused(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    bad = json.loads(json.dumps(SPEC))
    bad["scene"]["nodes"].append({"id": "x", "type": "script", "x": 0, "y": 0, "w": 1, "h": 1})
    out = svc.create_from_spec(pid, bad)
    assert out["state"] == "refused" and out["errors"][0]["code"] == "bad_node"
    assert not (root / "pages").exists()
