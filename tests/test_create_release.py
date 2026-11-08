"""Contract C6: a create release publishes new files only after approval, and restore removes exactly what it created."""
from pathlib import Path

import pytest

from workroom.tests.test_controller import KEY, OWNER, Crash, approve, crash_at
from workroom.workroom_core.controller.release import Controller, ReleaseError, StaleRelease

FILES = {"reports/q3.pptx": b"deck bytes", "reports/q3.xlsx": b"book bytes"}


def make(tmp_path: Path, failpoint=None):
    project, state = tmp_path / "project", tmp_path / "state"
    project.mkdir(exist_ok=True)
    (project / "keep.txt").write_bytes(b"mine")
    return Controller(project, state, KEY, frozenset({OWNER}), failpoint), project, state


def test_t_rel_create_publishes_new_files_and_leaves_everything_else(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(FILES, mode="create")
    assert not (project / "reports").exists(), "staging must not touch the project"
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    assert {p: (project / p).read_bytes() for p in FILES} == FILES
    assert (project / "keep.txt").read_bytes() == b"mine"


def test_create_refuses_to_overwrite_an_existing_file_at_staging(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    with pytest.raises(ReleaseError, match="already exists"):
        ctl.stage({"keep.txt": b"x"}, mode="create")


def test_t_rel_2_a_file_that_appears_before_publishing_is_never_overwritten(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(FILES, mode="create")
    approve(ctl, rid)
    (project / "reports").mkdir()
    (project / "reports/q3.pptx").write_bytes(b"someone else's file")
    with pytest.raises(StaleRelease):
        ctl.publish(rid, now=2.0)
    assert (project / "reports/q3.pptx").read_bytes() == b"someone else's file"
    assert not (project / "reports/q3.xlsx").exists()


def test_t_rel_3_restore_deletes_exactly_what_the_release_created(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(FILES, mode="create")
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    ctl.restore(rid)
    assert not any((project / p).exists() for p in FILES)
    assert (project / "keep.txt").read_bytes() == b"mine"


def test_restore_refuses_when_a_created_file_was_edited_since(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(FILES, mode="create")
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    (project / "reports/q3.pptx").write_bytes(b"edited by a person")
    with pytest.raises(StaleRelease):
        ctl.restore(rid)
    assert (project / "reports/q3.pptx").read_bytes() == b"edited by a person"


POINTS = ["before_backup:0", "before_replace:0", "after_replace:0", "before_replace:1", "after_replace:1", "before_published"]


@pytest.mark.parametrize("point", POINTS)
def test_create_release_survives_a_crash_at_every_point(tmp_path: Path, point: str) -> None:
    ctl, project, state = make(tmp_path, crash_at(point))
    rid = ctl.stage(FILES, mode="create")
    approve(ctl, rid)
    with pytest.raises(Crash):
        ctl.publish(rid, now=2.0)
    ctl2 = Controller(project, state, KEY, frozenset({OWNER}))
    out = ctl2.recover()
    assert out.get(rid) == "published"
    assert {p: (project / p).read_bytes() for p in FILES} == FILES
    assert not list(project.rglob("*.wr-*"))
    ctl2.restore(rid)
    assert not any((project / p).exists() for p in FILES)
