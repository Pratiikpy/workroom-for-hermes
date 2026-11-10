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
    assert make_workspace_guard(lambda: 1 / 0, lambda p: {})(tool_name="write_file", args={"path": "x"}) is None
