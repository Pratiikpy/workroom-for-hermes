"""The scene graph of a visual page: a flat, ordered list of simple nodes with strict, closed validation.

A scene is data. It never carries code, markup or links: text is plain text, colours are six hex digits, and every field is checked here
before anything renders or saves it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_NODES = 2000
MAX_TEXT = 2000
COORD = (-5000.0, 20000.0)
SIZE = (0.0, 20000.0)
ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
TYPES = ("rect", "ellipse", "text", "line")
COMMON = {"id", "type", "x", "y", "w", "h", "rotate", "fill", "stroke", "stroke_w", "opacity"}
EXTRA = {"rect": {"radius"}, "ellipse": set(), "line": set(), "text": {"text", "template", "size", "color", "bold", "align"}}
SCENE_KEYS = {"version", "canvas", "nodes", "facts", "cache", "theme"}


class SceneError(ValueError):
    pass


@dataclass(frozen=True)
class Issue:
    code: str
    where: str
    message: str


def _num(v: Any, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= float(v) <= hi and float(v) == float(v)


def validate_node(n: Any, where: str) -> list[Issue]:
    bad = lambda msg: [Issue("bad_node", where, msg)]  # noqa: E731
    if not isinstance(n, dict):
        return bad("a node is an object")
    if not isinstance(n.get("id"), str) or not ID.match(n["id"]):
        return bad("id must be 1 to 40 letters, digits, - or _")
    if n.get("type") not in TYPES:
        return bad(f"type must be one of {', '.join(TYPES)}")
    allowed = COMMON | EXTRA[n["type"]]
    extra = sorted(set(n) - allowed)
    if extra:
        return bad(f"unknown fields: {', '.join(extra)}")
    for k in ("x", "y"):
        if not _num(n.get(k), *COORD):
            return bad(f"{k} must be a number between {COORD[0]:g} and {COORD[1]:g}")
    for k in ("w", "h"):
        if not _num(n.get(k), *SIZE):
            return bad(f"{k} must be a number between 0 and {SIZE[1]:g}")
    if "rotate" in n and not _num(n["rotate"], -360, 360):
        return bad("rotate must be between -360 and 360")
    if "opacity" in n and not _num(n["opacity"], 0, 1):
        return bad("opacity must be between 0 and 1")
    if "stroke_w" in n and not _num(n["stroke_w"], 0, 100):
        return bad("stroke_w must be between 0 and 100")
    for k in ("fill", "stroke", "color"):
        if k in n and not (isinstance(n[k], str) and HEX.match(n[k])):
            return bad(f"{k} must be six hex digits such as 2563EB")
    if n["type"] == "rect" and "radius" in n and not _num(n["radius"], 0, 5000):
        return bad("radius must be a number")
    if n["type"] == "text":
        if "text" in n and not (isinstance(n["text"], str) and len(n["text"]) <= MAX_TEXT):
            return [Issue("bad_node", where, f"text must be plain text of at most {MAX_TEXT} characters")]
        if "size" in n and not _num(n["size"], 4, 400):
            return bad("size must be between 4 and 400")
        if "bold" in n and not isinstance(n["bold"], bool):
            return bad("bold must be true or false")
        if "align" in n and n["align"] not in ("left", "center", "right"):
            return bad("align must be left, center or right")
        if "template" in n and not (isinstance(n["template"], str) and len(n["template"]) <= MAX_TEXT):
            return bad("template must be text with {fact:format} slots")
    return []


def validate_scene(scene: Any) -> list[Issue]:
    if not isinstance(scene, dict) or scene.get("version") != 1:
        return [Issue("bad_scene", "", "a scene is an object with version 1")]
    extra = sorted(set(scene) - SCENE_KEYS)
    if extra:
        return [Issue("bad_scene", "", f"unknown scene fields: {', '.join(extra)}")]
    c = scene.get("canvas")
    if not (isinstance(c, dict) and _num(c.get("w"), 100, 20000) and _num(c.get("h"), 100, 20000)):
        return [Issue("bad_scene", "canvas", "canvas needs w and h between 100 and 20000")]
    nodes = scene.get("nodes")
    if not isinstance(nodes, list):
        return [Issue("bad_scene", "nodes", "nodes must be a list")]
    if len(nodes) > MAX_NODES:
        return [Issue("too_large", "nodes", f"at most {MAX_NODES} nodes")]
    issues: list[Issue] = []
    seen: set[str] = set()
    for i, n in enumerate(nodes):
        issues += validate_node(n, f"nodes[{i}]")
        if isinstance(n, dict) and isinstance(n.get("id"), str):
            if n["id"] in seen:
                issues.append(Issue("duplicate_id", f"nodes[{i}]", f"id {n['id']!r} is used twice"))
            seen.add(n["id"])
    return issues
