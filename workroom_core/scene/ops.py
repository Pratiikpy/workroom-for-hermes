"""Edits to a scene as small patches. Applying ops never mutates the input, is all-or-nothing, and returns the exact inverse ops."""

from __future__ import annotations

import copy
from typing import Any

from .model import SceneError, validate_node, validate_scene

OPS = ("add", "update", "delete", "reorder")


def _index(nodes: list[dict], node_id: Any) -> int:
    for i, n in enumerate(nodes):
        if n["id"] == node_id:
            return i
    raise SceneError(f"no node with id {node_id!r}")


def apply_ops(scene: dict[str, Any], ops: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (new scene, inverse ops). Applying the inverse ops to the new scene gives back exactly the old one."""
    if not isinstance(ops, list) or len(ops) > 500:
        raise SceneError("ops must be a list of at most 500 operations")
    new = copy.deepcopy(scene)
    nodes = new["nodes"]
    inverse: list[dict[str, Any]] = []
    for k, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise SceneError(f"op {k}: unknown operation")
        kind = op["op"]
        if kind == "add":
            node = copy.deepcopy(op.get("node"))
            issues = validate_node(node, f"op {k}")
            if issues:
                raise SceneError(issues[0].message)
            if any(n["id"] == node["id"] for n in nodes):
                raise SceneError(f"op {k}: id {node['id']!r} already exists")
            at = op.get("index", len(nodes))
            if not isinstance(at, int) or isinstance(at, bool) or not 0 <= at <= len(nodes):
                raise SceneError(f"op {k}: index out of range")
            nodes.insert(at, node)
            inverse.append({"op": "delete", "id": node["id"]})
        elif kind == "delete":
            i = _index(nodes, op.get("id"))
            inverse.append({"op": "add", "node": copy.deepcopy(nodes[i]), "index": i})
            del nodes[i]
        elif kind == "update":
            i = _index(nodes, op.get("id"))
            changes = op.get("set", {})
            unset = op.get("unset", [])
            if not isinstance(changes, dict) or not isinstance(unset, list) or "id" in changes or "type" in changes or "id" in unset or "type" in unset:
                raise SceneError(f"op {k}: set must be an object that does not change id or type")
            node = nodes[i]
            before = {key: copy.deepcopy(node[key]) for key in changes if key in node}
            added = [key for key in changes if key not in node]
            removed = {key: copy.deepcopy(node[key]) for key in unset if key in node}
            node.update(copy.deepcopy(changes))
            for key in unset:
                node.pop(key, None)
            issues = validate_node(node, f"op {k}")
            if issues:
                raise SceneError(issues[0].message)
            inverse.append({"op": "update", "id": node["id"], "set": {**before, **removed}, **({"unset": added} if added else {})})
        else:  # reorder
            i = _index(nodes, op.get("id"))
            to = op.get("index")
            if not isinstance(to, int) or isinstance(to, bool) or not 0 <= to < len(nodes):
                raise SceneError(f"op {k}: index out of range")
            node = nodes.pop(i)
            nodes.insert(to, node)
            inverse.append({"op": "reorder", "id": node["id"], "index": i})
    issues = validate_scene(new)
    if issues:
        raise SceneError(issues[0].message)
    inverse.reverse()
    return new, inverse


def invert(scene_before: dict[str, Any], ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return apply_ops(scene_before, ops)[1]
