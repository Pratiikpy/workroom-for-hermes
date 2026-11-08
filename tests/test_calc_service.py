"""The owner's view of calculated numbers and findings through the service."""
from pathlib import Path

import pytest

from workroom.tests.test_acknowledgement import _release
from workroom.tests.test_calculations import SENTENCE, _deck, _sources
from workroom.workroom_core.service import Service, ServiceError


def _service_project(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, 14_000_000, 15_100_000)
    _deck(root, [SENTENCE])
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, pid, root


def test_calculations_are_listed_with_the_formula_and_its_values(tmp_path: Path) -> None:
    svc, pid, _ = _service_project(tmp_path)
    out = svc.calculations(pid)
    c = out["candidates"][0]
    assert c["where"] == "Slide 1" and c["certainty"] == "certain" and c["figure"].startswith("7.9%")
    assert "Net revenue" in c["options"][0]["words"] and "= 7.857" in c["options"][0]["values"]
    assert out["dismissed"] == 0


def test_accepting_every_certain_calculation_is_one_call_and_leaves_the_uncertain_ones(tmp_path: Path) -> None:
    svc, pid, _ = _service_project(tmp_path)
    assert svc.accept_certain_calculations(pid) == {"accepted": 1}
    assert svc.calculations(pid)["candidates"] == [], "an accepted calculation is a tie now and is not offered again"


def test_dismissing_is_remembered(tmp_path: Path) -> None:
    svc, pid, _ = _service_project(tmp_path)
    cid = svc.calculations(pid)["candidates"][0]["id"]
    svc.dismiss_calculation(pid, cid)
    out = svc.calculations(pid)
    assert out["candidates"] == [] and out["dismissed"] == 1


def test_accepting_a_stale_candidate_is_a_clear_refusal(tmp_path: Path) -> None:
    svc, pid, _ = _service_project(tmp_path)
    with pytest.raises(ServiceError):
        svc.accept_calculation(pid, "0" * 20)


def test_a_dismissed_finding_disappears_from_the_inbox_and_bad_decisions_are_refused(tmp_path: Path) -> None:
    svc, pid, root, staged = _release(tmp_path, 13_000_000)
    inbox = svc.changes_inbox(pid)
    assert [f["severity"] for f in inbox["flags"]] == ["high"]
    svc.decide_finding(pid, inbox["flags"][0]["id"], "dismissed")
    assert svc.changes_inbox(pid)["flags"] == []
    with pytest.raises(ServiceError):
        svc.decide_finding(pid, inbox["flags"][0]["id"], "approved")
    with pytest.raises(ServiceError):
        svc.decide_finding(pid, "not-an-id", "dismissed")
