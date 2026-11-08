from pathlib import Path

import pytest

from workroom.workroom_core.controller.approvals import ApprovalError, sign
from workroom.workroom_core.controller.fsio import sha256_file
from workroom.workroom_core.controller.release import Controller, NotReady, ReleaseError, StaleRelease

KEY = b"k" * 32
OWNER = "telegram:42"
OLD = {"a.txt": b"old a", "b.txt": b"old b", "c.txt": b"old c"}
NEW = {"a.txt": b"new a", "b.txt": b"new b", "c.txt": b"new c"}


class Crash(BaseException):
    """Simulated process death at a named point."""


def crash_at(point: str):
    def fp(name: str) -> None:
        if name == point:
            raise Crash(name)
    return fp


def make(tmp_path: Path, failpoint=None) -> tuple[Controller, Path, Path]:
    project, state = tmp_path / "project", tmp_path / "state"
    project.mkdir(exist_ok=True)
    for name, data in OLD.items():
        if not (project / name).exists():
            (project / name).write_bytes(data)
    return Controller(project, state, KEY, frozenset({OWNER}), failpoint), project, state


def approve(ctl: Controller, rid: str, nonce: str = "n1", expires: float = 10**12, principal: str = OWNER):
    ctl.mark_verified(rid)
    ap = sign(KEY, rid, ctl.digest(rid), principal, "desktop", expires, nonce)
    ctl.record_approval(rid, ap, now=1.0)
    return ap


def contents(project: Path) -> dict[str, bytes]:
    return {n: (project / n).read_bytes() for n in OLD}


def test_happy_path_publishes_all_files_and_keeps_backups(tmp_path: Path) -> None:
    ctl, project, state = make(tmp_path)
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    assert contents(project) == NEW
    assert ctl.journal.last_step(rid) == "PUBLISHED"
    assert (state / "backups" / rid / "a.txt").read_bytes() == b"old a"


def test_publish_without_approval_is_refused(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    ctl.mark_verified(rid)
    with pytest.raises(NotReady):
        ctl.publish(rid)
    assert contents(project) == OLD


def test_unverified_release_cannot_be_approved(tmp_path: Path) -> None:
    ctl, _, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    ap = sign(KEY, rid, ctl.digest(rid), OWNER, "desktop", 10**12, "n")
    with pytest.raises(NotReady):
        ctl.record_approval(rid, ap)


def test_blocked_release_stays_blocked(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    with pytest.raises(NotReady):
        ctl.mark_verified(rid, ["Revenue changed but 1 of 3 regions is missing"])
    assert contents(project) == OLD


def test_stale_file_refuses_the_release_and_changes_nothing(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    (project / "b.txt").write_bytes(b"a human edited this")
    with pytest.raises(StaleRelease):
        ctl.publish(rid, now=2.0)
    assert (project / "a.txt").read_bytes() == b"old a"
    assert (project / "b.txt").read_bytes() == b"a human edited this"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ap, rid, dg: ap.__class__(rid, "0" * 64, ap.principal, ap.channel, ap.expires_at, ap.nonce, ap.signature),
        lambda ap, rid, dg: ap.__class__(rid, dg, "telegram:99", ap.channel, ap.expires_at, ap.nonce, ap.signature),
        lambda ap, rid, dg: ap.__class__(rid, dg, ap.principal, ap.channel, ap.expires_at + 1, ap.nonce, ap.signature),
    ],
)
def test_tampered_approval_is_refused(tmp_path: Path, mutate) -> None:
    ctl, _, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    ctl.mark_verified(rid)
    good = sign(KEY, rid, ctl.digest(rid), OWNER, "desktop", 10**12, "n")
    with pytest.raises(ApprovalError):
        ctl.record_approval(rid, mutate(good, rid, ctl.digest(rid)), now=1.0)


def test_approval_from_a_stranger_is_refused(tmp_path: Path) -> None:
    ctl, _, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    ctl.mark_verified(rid)
    ap = sign(KEY, rid, ctl.digest(rid), "telegram:99", "telegram", 10**12, "n")
    with pytest.raises(ApprovalError):
        ctl.record_approval(rid, ap, now=1.0)


def test_expired_approval_is_refused(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    ctl.mark_verified(rid)
    ap = sign(KEY, rid, ctl.digest(rid), OWNER, "desktop", 5.0, "n")
    with pytest.raises(ApprovalError):
        ctl.record_approval(rid, ap, now=6.0)
    assert contents(project) == OLD


def test_approval_expiring_before_publish_is_refused(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    approve(ctl, rid, expires=5.0)
    with pytest.raises(ApprovalError):
        ctl.publish(rid, now=6.0)
    assert contents(project) == OLD


def test_an_approval_cannot_be_replayed_on_another_release(tmp_path: Path) -> None:
    ctl, _, _ = make(tmp_path)
    r1 = ctl.stage(NEW)
    ap = approve(ctl, r1)
    r2 = ctl.stage({"a.txt": b"other"})
    ctl.mark_verified(r2)
    with pytest.raises(ApprovalError):
        ctl.record_approval(r2, ap, now=1.0)


def test_a_nonce_cannot_be_used_twice(tmp_path: Path) -> None:
    ctl, _, _ = make(tmp_path)
    r1 = ctl.stage(NEW)
    approve(ctl, r1, nonce="same")
    r2 = ctl.stage({"a.txt": b"other"})
    ctl.mark_verified(r2)
    ap2 = sign(KEY, r2, ctl.digest(r2), OWNER, "desktop", 10**12, "same")
    with pytest.raises(ApprovalError):
        ctl.record_approval(r2, ap2, now=1.0)


def test_unsafe_paths_are_refused(tmp_path: Path) -> None:
    ctl, _, _ = make(tmp_path)
    for bad in ["../x.txt", "/abs.txt", "a/../../x", "C:/x"]:
        with pytest.raises(ReleaseError):
            ctl.stage({bad: b"x"})


INPLACE_POINTS = [f"{p}:{i}" for i in range(3) for p in ("before_backup", "after_backup", "after_tmp_write", "before_replace", "after_replace")] + ["before_published"]


@pytest.mark.parametrize("point", INPLACE_POINTS)
def test_crash_at_every_point_recovers_to_all_new(tmp_path: Path, point: str) -> None:
    ctl, project, state = make(tmp_path, crash_at(point))
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    with pytest.raises(Crash):
        ctl.publish(rid, now=2.0)
    ctl.journal.close()
    fresh, _, _ = make(tmp_path)  # a new process
    assert fresh.recover() == {rid: "published"}
    assert contents(project) == NEW
    assert not list(project.rglob("*.tmp"))
    assert fresh.journal.last_step(rid) == "PUBLISHED"
    assert fresh.recover() == {}  # idempotent


def test_crash_then_rollback_when_staged_copies_are_gone(tmp_path: Path) -> None:
    ctl, project, state = make(tmp_path, crash_at("after_replace:1"))
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    with pytest.raises(Crash):
        ctl.publish(rid, now=2.0)
    ctl.journal.close()
    import shutil

    shutil.rmtree(state / "staging" / rid)
    fresh, _, _ = make(tmp_path)
    assert fresh.recover() == {rid: "rolled_back"}
    assert contents(project) == OLD


def test_unknown_file_state_requires_a_human(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path, crash_at("after_replace:0"))
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    with pytest.raises(Crash):
        ctl.publish(rid, now=2.0)
    ctl.journal.close()
    (project / "c.txt").write_bytes(b"someone else wrote this")
    fresh, _, _ = make(tmp_path)
    assert fresh.recover() == {rid: "recovery_required"}
    assert (project / "c.txt").read_bytes() == b"someone else wrote this"


def test_restore_returns_the_old_files(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    ctl.restore(rid)
    assert contents(project) == OLD


def test_restore_is_refused_after_a_later_edit(tmp_path: Path) -> None:
    ctl, project, _ = make(tmp_path)
    rid = ctl.stage(NEW)
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    (project / "a.txt").write_bytes(b"edited later")
    with pytest.raises(StaleRelease):
        ctl.restore(rid)
    assert (project / "a.txt").read_bytes() == b"edited later"


def test_folder_mode_leaves_originals_and_switches_a_pointer(tmp_path: Path) -> None:
    ctl, project, state = make(tmp_path)
    rid = ctl.stage(NEW, mode="folder")
    approve(ctl, rid)
    ctl.publish(rid, now=2.0)
    assert contents(project) == OLD
    import json

    pointer = json.loads((state / "releases" / "current.json").read_text())
    assert pointer["id"] == rid
    assert (state / "releases" / str(pointer["release"]) / "a.txt").read_bytes() == b"new a"


def test_folder_mode_crash_before_pointer_recovers(tmp_path: Path) -> None:
    ctl, project, state = make(tmp_path, crash_at("before_pointer"))
    rid = ctl.stage(NEW, mode="folder")
    approve(ctl, rid)
    with pytest.raises(Crash):
        ctl.publish(rid, now=2.0)
    ctl.journal.close()
    assert not (state / "releases" / "current.json").exists()
    fresh, _, _ = make(tmp_path)
    assert fresh.recover() == {rid: "published"}
    assert (state / "releases" / "current.json").exists()


def test_journal_cannot_be_edited(tmp_path: Path) -> None:
    import sqlite3

    ctl, _, _ = make(tmp_path)
    ctl.stage(NEW)
    with pytest.raises(sqlite3.DatabaseError):
        ctl.journal._db.execute("UPDATE journal SET step='PUBLISHED'")
    with pytest.raises(sqlite3.DatabaseError):
        ctl.journal._db.execute("DELETE FROM journal")
