"""The project's own policy: protected files and a human yes before bulk removal."""

from pathlib import Path

import pytest

from workroom.adapters.workspace_guard import make_workspace_guard
from workroom.tests.test_room import project
from workroom.workroom_core.service import ServiceError


def guard_for(svc):
    return make_workspace_guard(lambda: svc.projects(), lambda pid: svc.room_policy(pid))


def test_a_protected_file_cannot_be_written_or_removed(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    g = guard_for(svc)
    got = g(tool_name="write_file", args={"path": str(root / ".env"), "content": "x"})
    assert got["action"] == "block" and ".env" in got["message"]
    assert g(tool_name="terminal", args={"command": "rm secrets/server.pem", "workdir": str(root)})["action"] == "block"
    assert g(tool_name="write_file", args={"path": str(root / "notes.txt"), "content": "x"}) is None


def test_the_owner_can_protect_a_folder_and_the_agent_has_no_tool_to_change_the_policy(tmp_path: Path) -> None:
    from workroom.adapters import tools

    root, svc, pid = project(tmp_path)
    svc.room_set_policy(pid, ["final/*"], True)
    g = guard_for(svc)
    assert g(tool_name="patch", args={"path": str(root / "final" / "board.docx")})["action"] == "block"
    with pytest.raises(ServiceError):
        svc.room_set_policy(pid, ["../outside"], True)
    assert not [n for n in dir(tools) if "policy" in n]


def test_bulk_removal_needs_a_human_yes_and_a_single_file_does_not(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    (root / "old").mkdir()
    g = guard_for(svc)
    assert g(tool_name="terminal", args={"command": "rm -rf old", "workdir": str(root)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "rm *.tmp", "workdir": str(root)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "rm a.txt b.txt c.txt d.txt e.txt", "workdir": str(root)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "rm one.txt", "workdir": str(root)}) is None
    svc.room_set_policy(pid, [".env"], False)
    assert g(tool_name="terminal", args={"command": "rm -rf old", "workdir": str(root)}) is None


def test_the_guard_ignores_other_folders_and_never_raises(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    g = guard_for(svc)
    assert g(tool_name="write_file", args={"path": str(tmp_path / "elsewhere" / ".env")}) is None
    broken = make_workspace_guard(lambda: 1 / 0, lambda p: {})(tool_name="write_file", args={"path": "x"})
    assert broken["action"] == "approve" and "could not check" in broken["message"]  # a policy that cannot be read asks a person, it does not let the call through


def test_a_relative_path_with_no_known_folder_is_not_taken_to_be_inside_a_project(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    g = guard_for(svc)
    assert g(tool_name="write_file", args={"path": ".env", "content": "x"}) is None
    assert g(tool_name="write_file", args={"path": ".env", "content": "x"}, cwd=str(root))["action"] == "block"


def test_absolute_paths_and_in_place_edits_are_checked_too(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    g = guard_for(svc)
    target = (root / ".env").as_posix()
    assert g(tool_name="terminal", args={"command": f"rm {target}"})["action"] == "block"
    assert g(tool_name="terminal", args={"command": "sed -i s/a/b/ .env", "workdir": str(root)})["action"] == "block"
    assert g(tool_name="terminal", args={"command": "cp other.txt .env", "workdir": str(root)})["action"] == "block"
    assert g(tool_name="terminal", args={"command": "echo x | tee .env", "workdir": str(root)})["action"] == "block"


def test_the_workspace_guard_reads_a_bounded_part_of_a_huge_command(tmp_path: Path) -> None:
    from time import perf_counter

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.txt").write_text("x")
    g = make_workspace_guard(lambda: [{"project": "p1", "folder": str(proj)}], lambda pid: {"protected": [".env"], "confirm_delete": True})
    for unit in ("A", "rm ", "\t\n", "; cd ", "cd x\n", "f(", "> a ", "git "):
        started = perf_counter()
        g(tool_name="terminal", args={"command": unit * (300_000 // len(unit)), "workdir": str(proj)})
        assert perf_counter() - started < 0.5, unit
    assert g(tool_name="terminal", args={"command": "rm -rf .", "workdir": str(proj)})["action"] == "approve"
