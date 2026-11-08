"""A document that is not in the folder for a moment keeps its links: nothing the owner decided about it is thrown away."""
from pathlib import Path

from workroom.tests.test_calculations import _project, _sources


def _deck(proj) -> Path:
    return next(p for p in proj.root.iterdir() if p.suffix == ".pptx")


def test_links_of_a_missing_document_are_kept_and_it_is_reported(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $14.0 million in Q2 2026."])
    before = [(t.id, t.state, t.raw) for t in proj.ties()]
    deck = _deck(proj)
    held = deck.read_bytes()
    deck.rename(deck.with_suffix(".away"))
    found = proj.discover()
    assert found.missing == (deck.name,)
    assert [(t.id, t.state, t.raw) for t in proj.ties()] == before
    deck.with_suffix(".away").rename(deck)
    assert deck.read_bytes() == held
    again = proj.discover()
    assert again.missing == ()
    assert [(t.id, t.state, t.raw) for t in proj.ties()] == before


def test_an_owner_decision_about_a_link_survives_the_absence(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $14.0 million in Q2 2026."])
    tie = next(t for t in proj.ties() if t.kind == "text")
    proj.skip(tie.id)
    deck = _deck(proj)
    deck.rename(deck.with_suffix(".away"))
    proj.discover()
    deck.with_suffix(".away").rename(deck)
    proj.discover()
    assert next(t for t in proj.ties() if t.id == tie.id).state == "skipped"


def test_a_refresh_with_the_document_missing_says_so_instead_of_failing(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $14.0 million in Q2 2026."])
    deck = _deck(proj)
    deck.rename(deck.with_suffix(".away"))
    _sources(proj.root, 15_000_000, 16_000_000)
    plan = proj.plan_refresh()
    assert not plan.impacts
    assert any("missing" in s and deck.name in s for s in plan.skipped)


def test_the_service_names_the_missing_document(tmp_path: Path) -> None:
    from workroom.workroom_core.service import Service, ServiceError

    tmp_path.joinpath("p").mkdir()
    proj = _project(tmp_path / "p", ["Net revenue reached $14.0 million in Q2 2026."])
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(proj.root))["project"]
    svc.discover(pid)
    deck = _deck(proj)
    deck.rename(deck.with_suffix(".away"))
    assert svc.discover(pid)["missing"] == [deck.name]
    _sources(proj.root, 15_000_000, 16_000_000)
    try:
        svc.stage(pid)
    except ServiceError as exc:
        assert "missing from the folder" in str(exc) and deck.name in str(exc)
    else:
        raise AssertionError("a release with its only document missing must be refused")


def test_the_newest_waiting_release_is_chosen_across_projects_by_time(tmp_path: Path) -> None:
    from workroom.workroom_core.service import Service

    svc = Service(tmp_path / "state")
    ids = []
    for name in ("busy", "fresh"):
        (tmp_path / name).mkdir()
        proj = _project(tmp_path / name, ["Net revenue reached $14.0 million in Q2 2026."])
        pid = svc.add_project(str(proj.root))["project"]
        svc.discover(pid)
        ids.append((pid, proj))
    (busy, bproj), (fresh, fproj) = ids
    for step in range(3):  # the busy project has a long journal: staged and released more than once
        _sources(bproj.root, 14_000_000 + step * 1_000_000 + 1_000_000, 16_000_000)
        svc.discover(busy)
        staged = svc.stage(busy)
        if step < 2:
            svc.approve_and_publish(busy, staged["release_id"], staged["digest"])
    _sources(fproj.root, 15_000_000, 16_000_000)
    svc.discover(fresh)
    newest = svc.stage(fresh)
    assert svc.latest_awaiting() == (fresh, newest["release_id"])
