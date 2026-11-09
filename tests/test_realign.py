"""After a release, every link in a paragraph follows its own number, whether or not the paragraph holds numbers that were never linked."""
from pathlib import Path

from workroom.tests.test_calculations import _project, _sources


def _release(proj, q2: float, q3: float) -> list[tuple[str, str]]:
    _sources(proj.root, q2, q3)
    plan = proj.plan_refresh()
    for name, data in plan.files.items():
        (proj.root / name).write_bytes(data)
    proj.commit_snapshot(plan)
    return [(i.old_text, i.new_text) for i in plan.impacts]


def test_a_paragraph_with_unlinked_numbers_keeps_its_links_release_after_release(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $15.1 million in Q3 2026 with 7 offices open."])
    assert [(t.raw, t.state) for t in proj.ties()] == [("$15.1 million", "accepted")]
    assert _release(proj, 14_000_000, 16_000_000) == [("$15.1 million", "$16.0 million")]
    assert [(t.raw, t.state) for t in proj.ties()] == [("$16.0 million", "accepted")]
    assert _release(proj, 14_000_000, 17_500_000) == [("$16.0 million", "$17.5 million")]
    assert [(t.raw, t.state) for t in proj.ties()] == [("$17.5 million", "accepted")]


def test_a_longer_new_number_does_not_throw_the_links_after_it_off(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $9.9 million in Q3 2026, up from $14.0 million in Q2 2026."], q2=14_000_000, q3=9_900_000)
    assert {t.raw for t in proj.ties() if t.state == "accepted"} == {"$9.9 million", "$14.0 million"}
    assert _release(proj, 15_000_000, 10_500_000)
    assert {(t.raw, t.state) for t in proj.ties()} == {("$10.5 million", "accepted"), ("$15.0 million", "accepted")}
    assert {i for i in _release(proj, 15_000_000, 11_700_000)} == {("$10.5 million", "$11.7 million")}


def test_a_figure_a_person_retyped_stays_held_and_the_others_still_follow(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $15.1 million in Q3 2026, up from $14.0 million in Q2 2026."])
    from workroom.tests.test_calculations import _retype

    _retype(proj.root, "$14.0 million in Q2 2026", "$13.8 million in Q2 2026")
    proj.discover()
    held = next(t for t in proj.ties() if t.state == "held")
    assert held.raw == "$14.0 million"
    assert _release(proj, 14_000_000, 16_000_000) == [("$15.1 million", "$16.0 million")]
    assert next(t for t in proj.ties() if t.id == held.id).state == "held"
    assert next(t for t in proj.ties() if t.raw == "$16.0 million").state == "accepted"


def test_a_change_written_with_an_explicit_plus_keeps_its_link(tmp_path: Path) -> None:
    from workroom.tests.test_calculations import SENTENCE

    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    derived = next(t for t in proj.ties() if t.kind == "derived")
    _sources(proj.root, 14_000_000, 15_500_000, q1=13_000_000)
    plan = proj.plan_refresh()
    for name, data in plan.files.items():
        (proj.root / name).write_bytes(data)
    proj.commit_snapshot(plan)
    assert next(t for t in proj.ties() if t.id == derived.id).state == "accepted"
