"""A person who rolls a sentence forward by hand does not lose its ties."""
from pathlib import Path

from workroom.tests.test_calculations import SENTENCE, _project, _retype, _sources


def test_a_number_retyped_to_the_next_period_follows_that_period(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $14.0 million in Q2 2026."], q2=14_000_000, q3=15_100_000)
    tie = next(t for t in proj.ties() if t.raw == "$14.0 million")
    assert tie.ref == "C2"
    _retype(proj.root, "$14.0 million in Q2 2026", "$15.1 million in Q3 2026")
    proj.discover()
    now = next(t for t in proj.ties() if t.id == tie.id)
    assert now.state == "accepted" and now.raw == "$15.1 million" and now.ref == "D2" and now.linked_value == 15_100_000
    _sources(proj.root, 14_000_000, 16_000_000)
    assert {i.old_text: i.new_text for i in proj.plan_refresh().impacts} == {"$15.1 million": "$16.0 million"}


def test_a_number_retyped_to_a_value_no_other_period_holds_is_still_held(tmp_path: Path) -> None:
    proj = _project(tmp_path, ["Net revenue reached $14.0 million in Q2 2026."])
    _retype(proj.root, "$14.0 million", "$99.9 million")
    proj.discover()
    assert next(t for t in proj.ties() if t.kind == "text").state == "held"


def test_a_calculation_rolled_by_hand_follows_its_new_cells(tmp_path: Path) -> None:
    proj = _project(tmp_path, [SENTENCE])
    proj.accept_calculation(proj.calculations().candidates[0].id)
    _sources(proj.root, 14_000_000, 15_100_000, q1=13_000_000)
    # the owner rolls the sentence back one quarter by hand: Q2 against Q1 = +7.7%
    _retype(proj.root, "$15.1 million in Q3 2026", "$14.0 million in Q2 2026")
    _retype(proj.root, "up 7.9% from $14.0 million in Q2 2026", "up 7.7% from $13.0 million in Q1 2026")
    proj.discover()
    derived = next(t for t in proj.ties() if t.kind == "derived")
    assert derived.state == "accepted" and derived.raw == "7.7%" and '"B2"' in derived.formula and '"C2"' in derived.formula
