"""Read-only side questions: where is a source cell used, and what would each place say if it had another value."""
from pathlib import Path

import pytest

from workroom.tests.test_create_flow import SPEC, _svc
from workroom.workroom_core.service import ServiceError


def _ready(tmp_path: Path):
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    return svc, pid, root


def test_where_used_lists_every_place_with_its_sentence(tmp_path: Path) -> None:
    svc, pid, root = _ready(tmp_path)
    out = svc.where_used(pid, "results.xlsx!Results!C2")
    assert out["value"] == 175 and len(out["places"]) == 2
    assert all(p["deck"] == "reports/q2.pptx" and p["text"] == "$175" and p["sentence"] for p in out["places"])
    assert svc.where_used(pid, "results.xlsx!Results!B3")["places"] == []


def test_what_if_shows_the_new_text_without_changing_anything(tmp_path: Path) -> None:
    svc, pid, root = _ready(tmp_path)
    before = (root / "reports/q2.pptx").read_bytes()
    out = svc.what_if(pid, "results.xlsx!Results!C2", 1250.0)
    assert [p["would_say"] for p in out["places"]] == ["$1250", "$1250"] and {p["decision"] for p in out["places"]} == {"auto"}
    assert (root / "reports/q2.pptx").read_bytes() == before and svc.plan(pid)["changes"] == [], "a what-if never changes anything"
    assert svc.what_if(pid, "results.xlsx!Results!C3", 0.456)["places"][0]["would_say"] == "45.6%"


def test_what_if_rejects_bad_input(tmp_path: Path) -> None:
    svc, pid, root = _ready(tmp_path)
    for bad in ("abc", float("inf"), True, None):
        with pytest.raises(ServiceError):
            svc.what_if(pid, "results.xlsx!Results!C2", bad)
    with pytest.raises(ServiceError):
        svc.what_if(pid, "results.xlsx!Results!Z99", 5)
    with pytest.raises(ServiceError):
        svc.where_used(pid, "not a ref")
