"""Contract C3 (model side): the scene graph validates strictly, edits are patches, and undo and redo are exact."""
import copy
import random

import pytest

from workroom.workroom_core.scene.model import SceneError, validate_scene
from workroom.workroom_core.scene.ops import apply_ops, invert

BASE = {"version": 1, "canvas": {"w": 1280, "h": 720}, "nodes": [
    {"id": "bg", "type": "rect", "x": 0, "y": 0, "w": 1280, "h": 720, "fill": "FFFFFF"},
    {"id": "t1", "type": "text", "x": 80, "y": 80, "w": 600, "h": 60, "text": "Q2 revenue", "size": 32, "color": "1F2937", "bold": True},
]}


def test_a_valid_scene_passes_and_returns_no_errors() -> None:
    assert validate_scene(BASE) == []


@pytest.mark.parametrize("mutate,code", [
    (lambda s: s.update(version=2), "bad_scene"),
    (lambda s: s["nodes"].append({"id": "t1", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1}), "duplicate_id"),
    (lambda s: s["nodes"].append({"id": "x", "type": "script", "x": 0, "y": 0, "w": 1, "h": 1}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "rect", "x": "0", "y": 0, "w": 1, "h": 1}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "rect", "x": 0, "y": 0, "w": -5, "h": 1}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "rect", "x": 10**9, "y": 0, "w": 1, "h": 1}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1, "fill": "red"}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x y", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "text", "x": 0, "y": 0, "w": 1, "h": 1, "text": "a" * 5000}), "bad_node"),
    (lambda s: s["nodes"].append({"id": "x", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1, "onclick": "alert(1)"}), "bad_node"),
])
def test_invalid_scenes_are_refused(mutate, code) -> None:
    s = copy.deepcopy(BASE)
    mutate(s)
    assert code in [e.code for e in validate_scene(s)]


def test_too_many_nodes_are_refused() -> None:
    s = copy.deepcopy(BASE)
    s["nodes"] += [{"id": f"n{i}", "type": "rect", "x": 0, "y": 0, "w": 1, "h": 1} for i in range(2100)]
    assert "too_large" in [e.code for e in validate_scene(s)]


def test_ops_are_pure_and_each_has_an_exact_inverse() -> None:
    before = copy.deepcopy(BASE)
    new, inv = apply_ops(BASE, [{"op": "update", "id": "t1", "set": {"x": 100, "text": "Q3 revenue"}},
                                {"op": "add", "node": {"id": "r2", "type": "rect", "x": 5, "y": 5, "w": 50, "h": 20, "fill": "2563EB"}},
                                {"op": "reorder", "id": "r2", "index": 0}, {"op": "delete", "id": "bg"}])
    assert BASE == before, "apply_ops must not mutate its input"
    assert [n["id"] for n in new["nodes"]] == ["r2", "t1"] and new["nodes"][1]["x"] == 100
    back, _ = apply_ops(new, inv)
    assert back == BASE


def test_an_op_that_would_make_the_scene_invalid_is_rejected_whole() -> None:
    with pytest.raises(SceneError):
        apply_ops(BASE, [{"op": "update", "id": "t1", "set": {"x": 5}}, {"op": "update", "id": "t1", "set": {"w": -1}}])
    with pytest.raises(SceneError):
        apply_ops(BASE, [{"op": "delete", "id": "nope"}])
    with pytest.raises(SceneError):
        apply_ops(BASE, [{"op": "update", "id": "t1", "set": {"id": "other"}}])
    with pytest.raises(SceneError):
        apply_ops(BASE, [{"op": "format_disk"}])


def test_t_cnv_4_random_operation_sequences_keep_undo_and_redo_exact() -> None:
    rng = random.Random(7)
    scene = copy.deepcopy(BASE)
    history = []
    for step in range(300):
        ids = [n["id"] for n in scene["nodes"]]
        kind = rng.choice(["add", "move", "delete", "reorder", "text"])
        if kind == "add" or not ids:
            op = {"op": "add", "node": {"id": f"n{step}", "type": rng.choice(["rect", "ellipse"]), "x": rng.randint(0, 1200), "y": rng.randint(0, 700), "w": rng.randint(1, 300), "h": rng.randint(1, 300), "fill": "%06X" % rng.randint(0, 0xFFFFFF)}}
        elif kind == "move":
            op = {"op": "update", "id": rng.choice(ids), "set": {"x": rng.randint(0, 1200), "y": rng.randint(0, 700)}}
        elif kind == "delete" and len(ids) > 1:
            op = {"op": "delete", "id": rng.choice(ids)}
        elif kind == "reorder":
            op = {"op": "reorder", "id": rng.choice(ids), "index": rng.randint(0, len(ids) - 1)}
        else:
            tid = next((n["id"] for n in scene["nodes"] if n["type"] == "text"), None)
            if tid is None:
                continue
            op = {"op": "update", "id": tid, "set": {"text": "v%d" % step}}
        after, inv = apply_ops(scene, [op])
        history.append((copy.deepcopy(scene), inv, op))
        scene = after
    final = copy.deepcopy(scene)
    for prev, inv, op in reversed(history):
        scene, redo = apply_ops(scene, inv)
        assert scene == prev
    for prev, inv, op in history:
        scene, _ = apply_ops(scene, [op])
    assert scene == final
