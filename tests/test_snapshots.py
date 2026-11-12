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


def test_the_shell_reader_names_the_files_a_command_changes() -> None:
    from workroom.adapters.snapshotter import shell_targets

    assert shell_targets("rm /home/u/proj/report.docx") == ["/home/u/proj/report.docx"]
    assert shell_targets("cp new.xlsx model.xlsx") == ["model.xlsx"]
    assert shell_targets("sed -i s/a/b/ notes.txt") == ["notes.txt"]
    assert shell_targets("truncate -s 0 data.csv") == ["data.csv"]
    assert shell_targets("echo x | tee out.txt") == ["out.txt"]
    assert shell_targets("del /q /s old.txt") == ["old.txt"]
    assert shell_targets("dd if=/dev/zero of=disk.img") == ["disk.img"]
    assert shell_targets("ls > /dev/null") == [] and shell_targets("rm *.tmp") == []


def test_a_relative_write_with_no_known_folder_is_not_recorded(tmp_path: Path) -> None:
    from workroom.adapters.snapshotter import make_snapshotter
    from workroom.tests.test_room import project

    root, svc, pid = project(tmp_path)
    (root / "notes.txt").write_text("x")
    hook = make_snapshotter(lambda: svc.projects(), lambda p, path, tool: svc.snapshot_take(p, path, tool))
    hook(tool_name="write_file", args={"path": "notes.txt", "content": "y"})
    assert svc.snapshots(pid) == []
    hook(tool_name="write_file", args={"path": "notes.txt", "content": "y"}, cwd=str(root))
    assert [s["path"] for s in svc.snapshots(pid)] == ["notes.txt"]


def test_the_cd_reader_is_fast_on_hostile_text_and_still_follows_a_cd(tmp_path: Path) -> None:
    from time import perf_counter

    from workroom.adapters.snapshotter import _after_cd

    for text in ("\n" * 300_000, "\n\n " * 100_000, "; cd " * 60_000, " " * 300_000, "cd " + "x" * 300_000, 'cd "' + "y" * 300_000, "\t\n" * 150_000):
        started = perf_counter()
        _after_cd(text, str(tmp_path))
        assert perf_counter() - started < 0.1, text[:8]
    sub = tmp_path / "reports"
    sub.mkdir()
    assert _after_cd("cd reports && mv a b", str(tmp_path)) == str(sub.resolve())
    assert _after_cd("echo hi\ncd reports; rm x", str(tmp_path)) == str(sub.resolve())
    assert _after_cd('pushd "reports"', str(tmp_path)) == str(sub.resolve())
    assert _after_cd("echo cd", str(tmp_path)) == str(tmp_path)


def test_a_command_naming_thousands_of_files_is_read_in_bounded_time(tmp_path: Path) -> None:
    from time import perf_counter

    from workroom.adapters.snapshotter import MAX_TARGETS, make_snapshotter, shell_targets

    assert shell_targets("rm a.txt a.txt b.txt") == ["a.txt", "b.txt"]
    assert len(shell_targets("rm " + " ".join(f"f{i}.txt" for i in range(5000)))) == MAX_TARGETS
    assert shell_targets("rm x; " + "y" * 70_000) == []
    proj = tmp_path / "proj"
    proj.mkdir()
    taken: list[str] = []
    hook = make_snapshotter(lambda: [{"project": "p1", "folder": str(proj)}], lambda pid, path, tool: taken.append(path))
    for command in ("rm " * 20_000, "rm " + " ".join(f"f{i}.txt" for i in range(8000)), "mv a b\n" * 8000):
        started = perf_counter()
        hook(tool_name="terminal", args={"command": command, "workdir": str(proj)})
        assert perf_counter() - started < 2, command[:12]
