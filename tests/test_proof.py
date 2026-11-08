"""Rendered before and after proof through the installed PowerPoint (skipped where PowerPoint is not installed)."""
import base64
from pathlib import Path

import pytest

from workroom.tests.test_create_flow import SPEC, _svc, _workbook
from workroom.workroom_core import proof

pytestmark = pytest.mark.skipif(not proof.available(), reason="PowerPoint is not installed")


def test_before_and_after_images_of_the_changed_slide(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, made["release_id"], made["digest"])
    _workbook(root, 190)
    staged = svc.stage(pid)
    live_before = (root / "reports/q2.pptx").read_bytes()
    out = svc.render_proof(pid, staged["release_id"])
    assert out["available"] is True and len(out["decks"]) == 1
    d = out["decks"][0]
    assert d["deck"] == "reports/q2.pptx" and d["slides"][0]["slide"] == 1
    before, after = (base64.b64decode(d["slides"][0][k]) for k in ("before", "after"))
    assert before[:8] == after[:8] == b"\x89PNG\r\n\x1a\n" and before != after, "the two renderings must differ where the number changed"
    assert (root / "reports/q2.pptx").read_bytes() == live_before, "proof never touches the live file"


def test_proof_says_so_when_there_is_nothing_to_render(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SPEC)
    assert svc.render_proof(pid, made["release_id"])["decks"] == [], "a create release has no before"
