from pathlib import Path

from workroom.adapters.guard import make_guard


def test_office_writes_inside_a_project_are_blocked_and_others_pass(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    g = make_guard(lambda: [str(proj)])
    blocked = g(tool_name="write_file", args={"path": str(proj / "deck.pptx"), "content": "x"})
    assert blocked and blocked["action"] == "block" and "workroom_stage_release" in blocked["message"]
    assert g(tool_name="patch", args={"path": str(proj / "sub" / ".." / "r.docx")})
    assert g(tool_name="patch", args={"patch": f"*** Update File: {proj / 'a.xlsx'}\n@@\n-1\n+2\n"})
    assert g(tool_name="write_file", args={"path": str(proj / "notes.md")}) is None
    assert g(tool_name="write_file", args={"path": str(tmp_path / "other" / "deck.pptx")}) is None
    assert g(tool_name="read_file", args={"path": str(proj / "deck.pptx")}) is None
    assert make_guard(lambda: [])(tool_name="write_file", args={"path": str(proj / "deck.pptx")}) is None


def test_shell_commands_that_write_a_managed_file_ask_the_human(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"x")
    g = make_guard(lambda: [str(proj)])
    r = g(tool_name="terminal", args={"command": f"cp other.pptx {proj / 'deck.pptx'}"})
    assert r and r["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "python -c \"open('deck.pptx','wb')\""})
    assert g(tool_name="terminal", args={"command": f"unzip -l {proj / 'deck.pptx'}"}) is None
    assert g(tool_name="terminal", args={"command": f"cat {proj / 'notes.md'} > out.txt"}) is None
    assert g(tool_name="terminal", args={"command": "cp a.pptx b.pptx"}) is None
