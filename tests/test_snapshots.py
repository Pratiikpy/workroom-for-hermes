"""Before-images: every file a tool is about to change can be put back, and a restore can itself be undone."""

from pathlib import Path

import pytest

from workroom.workroom_core.snapshots import SnapshotError, SnapshotStore


def store(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    return root, SnapshotStore(tmp_path / "state", root)


def test_a_changed_file_is_put_back_exactly(tmp_path: Path) -> None:
    root, s = store(tmp_path)
    f = root / "notes.txt"
    f.write_bytes(b"first\r\nsecond")
    sid = s.take(f, "write_file")
    f.write_bytes(b"overwritten")
    assert s.list()[0]["now"] == "changed"
    s.restore(sid)
    assert f.read_bytes() == b"first\r\nsecond" and s.list()[0]["restored"]


def test_a_restore_keeps_what_was_there_so_it_can_be_undone(tmp_path: Path) -> None:
    root, s = store(tmp_path)
    f = root / "a.txt"
    f.write_text("v1")
    sid = s.take(f, "patch")
    f.write_text("v2 by the agent")
    s.restore(sid)
    kept = list((tmp_path / "state" / "snapshots" / "recovery").rglob("a.txt"))
    assert len(kept) == 1 and kept[0].read_text() == "v2 by the agent"


def test_a_file_the_tool_created_is_moved_aside_on_restore_not_deleted(tmp_path: Path) -> None:
    root, s = store(tmp_path)
    f = root / "new.txt"
    sid = s.take(f, "write_file")
    f.write_text("made by the agent")
    s.restore(sid)
    assert not f.exists() and list((tmp_path / "state" / "snapshots" / "recovery").rglob("new.txt"))


def test_identical_content_is_stored_once(tmp_path: Path) -> None:
    root, s = store(tmp_path)
    for name in ("a.txt", "b.txt"):
        (root / name).write_text("same")
        s.take(root / name, "write_file")
    assert len(list((tmp_path / "state" / "snapshots" / "objects").iterdir())) == 1


def test_paths_outside_the_project_and_folders_are_not_recorded(tmp_path: Path) -> None:
    root, s = store(tmp_path)
    (tmp_path / "outside.txt").write_text("x")
    (root / "sub").mkdir()
    assert s.take(tmp_path / "outside.txt", "write_file") is None and s.take(root / "sub", "write_file") is None
    assert s.take(root / ".." / "outside.txt", "write_file") is None and s.list() == []


def test_an_unknown_snapshot_is_refused(tmp_path: Path) -> None:
    _, s = store(tmp_path)
    with pytest.raises(SnapshotError):
        s.restore(99)


def test_the_hook_keeps_a_copy_before_a_file_tool_or_a_shell_command_changes_a_project_file(tmp_path: Path) -> None:
    from workroom.adapters.snapshotter import make_snapshotter, shell_targets
    from workroom.tests.test_room import project

    root, svc, pid = project(tmp_path)
    (root / "notes.txt").write_text("keep me")
    (root / "old.txt").write_text("old")
    hook = make_snapshotter(lambda: svc.projects(), lambda p, path, tool: svc.snapshot_take(p, path, tool))
    hook(tool_name="write_file", args={"path": str(root / "notes.txt"), "content": "x"})
    hook(tool_name="terminal", args={"command": "rm old.txt && echo hi > made.txt", "workdir": str(root)})
    hook(tool_name="write_file", args={"path": str(tmp_path / "outside.txt"), "content": "x"})
    got = {s["path"]: s["state"] for s in svc.snapshots(pid)}
    assert got == {"notes.txt": "saved", "old.txt": "saved", "made.txt": "created"}
    (root / "notes.txt").write_text("overwritten")
    sid = next(s["id"] for s in svc.snapshots(pid) if s["path"] == "notes.txt")
    svc.snapshot_restore(pid, sid)
    assert (root / "notes.txt").read_text() == "keep me"
    assert shell_targets('rm -rf build; del "a b.txt" && cat x > y.log') == ["build", "a b.txt", "y.log"]


def test_the_hook_never_raises_or_blocks(tmp_path: Path) -> None:
    from workroom.adapters.snapshotter import make_snapshotter

    hook = make_snapshotter(lambda: 1 / 0, lambda *a: None)
    assert hook(tool_name="write_file", args={"path": "x"}) is None and hook(tool_name="read_file", args=None) is None
