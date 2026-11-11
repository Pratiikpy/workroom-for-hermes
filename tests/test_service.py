from pathlib import Path

import pytest

from workroom.tests.test_flagship_headless import change_source, deck_texts, make_deck, make_workbook
from workroom.workroom_core.service import Service, ServiceError


def prepared(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "deck.pptx").write_bytes(make_deck())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    return svc, pid, root


def test_end_to_end_through_the_service(tmp_path: Path) -> None:
    svc, pid, root = prepared(tmp_path)
    found = svc.discover(pid)
    assert found["accepted"] >= 2
    change_source(root, "C2", 150)
    plan = svc.plan(pid)
    assert [c["new_text"] for c in plan["changes"]] == ["150"]
    staged = svc.stage(pid)
    assert staged["state"] == "awaiting_approval"
    assert deck_texts(root / "deck.pptx")["Revenue line"].startswith("Revenue in Q2 was 120")  # nothing published yet
    done = svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert done["state"] == "published"
    assert deck_texts(root / "deck.pptx")["Revenue line"].startswith("Revenue in Q2 was 150")
    assert deck_texts(root / "deck.pptx")["Decoy"] == "Headcount reached 120 people"


def test_approving_a_different_digest_than_the_one_shown_is_refused(tmp_path: Path) -> None:
    svc, pid, root = prepared(tmp_path)
    svc.discover(pid)
    change_source(root, "C2", 150)
    staged = svc.stage(pid)
    with pytest.raises(ServiceError):
        svc.approve_and_publish(pid, staged["release_id"], "0" * 64)
    assert deck_texts(root / "deck.pptx")["Revenue line"].startswith("Revenue in Q2 was 120")


def test_nothing_to_release_is_reported(tmp_path: Path) -> None:
    svc, pid, _ = prepared(tmp_path)
    svc.discover(pid)
    with pytest.raises(ServiceError):
        svc.stage(pid)


def test_unknown_project_and_bad_folder_are_refused(tmp_path: Path) -> None:
    svc = Service(tmp_path / "data")
    with pytest.raises(ServiceError):
        svc.discover("nope")
    with pytest.raises(ServiceError):
        svc.add_project(str(tmp_path / "does-not-exist"))


def test_unsafe_broad_and_internal_project_folders_are_refused(tmp_path: Path, monkeypatch) -> None:
    hermes_home = tmp_path / "hermes-home"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    data = tmp_path / "data"
    svc = Service(data)
    for unsafe in (Path.home(), Path(tmp_path.anchor), hermes_home, data, tmp_path):
        with pytest.raises(ServiceError, match="refusing to register"):
            svc.add_project(str(unsafe))


def test_the_signing_key_persists_and_is_not_regenerated(tmp_path: Path) -> None:
    a = Service(tmp_path / "data")
    b = Service(tmp_path / "data")
    assert a._key == b._key and len(a._key) == 32


def test_confirm_makes_the_decoy_part_of_the_refresh_and_skip_removes_a_link(tmp_path: Path) -> None:
    svc, pid, root = prepared(tmp_path)
    found = svc.discover(pid)
    decoy = next(t for t in found["need_confirmation"] if t["text"] == "120")
    assert "Headcount" in decoy["sentence"]
    svc.skip(pid, decoy["id"])
    change_source(root, "C2", 150)
    assert [c["new_text"] for c in svc.plan(pid)["changes"]] == ["150"]  # the decoy is not touched, the revenue line is
    revenue = next(t for t in svc.ties(pid) if t["state"] == "accepted" and t["text"] == "120")
    svc.skip(pid, revenue["id"])
    assert svc.plan(pid)["changes"] == []  # a skipped link is left alone


def test_explain_answers_where_a_number_came_from(tmp_path: Path) -> None:
    svc, pid, root = prepared(tmp_path)
    svc.discover(pid)
    tie = next(t for t in svc.ties(pid) if t["state"] == "accepted" and t["text"] == "120")
    e = svc.explain(pid, tie["id"])
    assert e["source"]["cell"] == "C2" and e["source"]["sheet"] == "Results"
    assert "Revenue" in e["source"]["row"] and "Q2" in e["source"]["column"]
    assert e["source"]["value_now"] == 120.0 and e["source_changed_since_last_release"] is False
    change_source(root, "C2", 150)
    assert svc.explain(pid, tie["id"])["source_changed_since_last_release"] is True
    with pytest.raises(ServiceError):
        svc.explain(pid, 99999)


def test_release_view_follows_a_release_from_prepared_to_published(tmp_path: Path) -> None:
    svc, pid, root = prepared(tmp_path)
    svc.discover(pid)
    change_source(root, "C2", 150)
    st = svc.stage(pid)
    v = svc.release_view(pid, st["release_id"])
    assert v["state"] == "awaiting_approval" and v["digest"] == st["digest"]
    assert [c["new_text"] for c in v["changes"]] == ["150"]
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    assert svc.release_view(pid, st["release_id"])["state"] == "published"


def test_release_view_refuses_malformed_or_unknown_ids(tmp_path: Path) -> None:
    svc, pid, _ = prepared(tmp_path)
    for bad in ("", "x", "../../etc", "0" * 15, "0" * 16):
        with pytest.raises(ServiceError):
            svc.release_view(pid, bad)
