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


def test_writes_the_first_version_missed_now_ask_the_human(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"x")
    g = make_guard(lambda: [str(proj)])
    asks = [
        ("terminal", {"command": f"python -c \"import os; os.remove(r'{proj / 'deck.pptx'}')\""}),
        ("terminal", {"command": f"python -c \"import os; os.unlink(r'{proj / 'deck.pptx'}')\""}),
        ("terminal", {"command": f"cd {proj} && python -c \"import glob,os; [os.remove(f) for f in glob.glob('*.pptx')]\""}),
        ("terminal", {"command": "rm -f *.pptx", "workdir": str(proj)}),
        ("terminal", {"command": f"del {proj}\\*.docx"}),
        ("execute_code", {"code": f"from pathlib import Path; Path(r'{proj / 'deck.pptx'}').write_bytes(b'x')"}),
        ("terminal", {"command": "node -e \"require('fs').writeFileSync('deck.pptx','x')\"", "cwd": str(proj)}),
        ("terminal", {"command": f"git -C {proj} checkout -- ."}),
        ("terminal", {"command": f"powershell -c \"[IO.File]::Delete('{proj / 'deck.pptx'}')\""}),
    ]
    for tool, args in asks:
        got = g(tool_name=tool, args=args)
        assert got and got["action"] == "approve", (tool, args)
    reads = [
        ("terminal", {"command": f"python -c \"print(open(r'{proj / 'deck.pptx'}','rb').read(4))\""}),
        ("terminal", {"command": "ls *.pptx", "workdir": str(proj)}),
        ("terminal", {"command": f"unzip -l {proj / 'deck.pptx'}"}),
        ("terminal", {"command": "rm -f *.log", "workdir": str(tmp_path)}),
    ]
    for tool, args in reads:
        assert g(tool_name=tool, args=args) is None, (tool, args)


def test_the_chat_card_shows_one_line_for_the_same_change_in_several_places() -> None:
    from workroom.adapters.commands import _card

    change = {"old_text": "$30.2 trillion", "new_text": "$30.6 trillion", "deck": "briefing.pptx", "slide": 2, "where": "Slide 2"}
    view = {"release_id": "r1", "digest": "d" * 64, "changes": [change, dict(change), dict(change), {**change, "old_text": "1.5%", "new_text": "1.8%"}], "flags": []}
    card = _card(view)
    assert card.count("$30.2 trillion -> $30.6 trillion") == 1 and "3 places" in card and "1.5% -> 1.8%" in card
