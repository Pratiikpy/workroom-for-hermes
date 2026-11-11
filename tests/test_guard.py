from pathlib import Path
from time import perf_counter

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


def test_a_script_that_writes_a_managed_file_is_judged_by_what_it_contains_not_by_its_command_line(tmp_path: Path) -> None:
    """A real Gemini model, told to skip the approval step, wrote a Python script outside the project and ran it by name; the command line alone showed nothing."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "briefing.pptx").write_bytes(b"x")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    g = make_guard(lambda: [str(proj)])
    sneaky = scratch / "update_pptx.py"
    sneaky.write_text(f"from pptx import Presentation\nprs = Presentation(r'{proj / 'briefing.pptx'}')\nprs.save(r'{proj / 'briefing.pptx'}')\n", encoding="utf-8")
    r = g(tool_name="terminal", args={"command": f"python3 {sneaky}"})
    assert r and r["action"] == "approve" and "briefing.pptx" in r["message"]
    relative = scratch / "fix.py"
    relative.write_text("from pptx import Presentation\nPresentation('briefing.pptx').save('briefing.pptx')\n", encoding="utf-8")
    assert g(tool_name="terminal", args={"command": f"python3 {relative}", "workdir": str(proj)})
    assert g(tool_name="terminal", args={"command": f"cd {proj} && node {scratch / 'go.js'}"}) is None, "a script that does not exist says nothing"
    harmless = scratch / "look.py"
    harmless.write_text(f"from pptx import Presentation\nprint(len(Presentation(r'{proj / 'briefing.pptx'}').slides))\n", encoding="utf-8")
    assert g(tool_name="terminal", args={"command": f"python3 {harmless}"}) is None, "reading a managed file is not asking for approval"
    elsewhere = scratch / "other.py"
    elsewhere.write_text("open('notes.txt', 'w').write('hi')\n", encoding="utf-8")
    assert g(tool_name="terminal", args={"command": f"python3 {elsewhere}"}) is None


def test_a_large_single_token_script_is_scanned_with_a_bounded_cost(tmp_path: Path) -> None:
    """A hostile blob must not delay every shell or code invocation."""
    proj = tmp_path / "proj"
    proj.mkdir()
    script = tmp_path / "blob.py"
    script.write_text("write=" + "x" * 300_000, encoding="utf-8")
    g = make_guard(lambda: [str(proj)])

    started = perf_counter()
    assert g(tool_name="terminal", args={"command": f"python {script}"})["action"] == "approve"
    assert perf_counter() - started < 0.1


def test_script_budget_is_total_and_late_writes_need_approval(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"x")
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("#" + "x" * 40_000, encoding="utf-8")
    second.write_text("#" + "x" * 30_000 + "\nopen('deck.pptx','wb')", encoding="utf-8")
    g = make_guard(lambda: [str(proj)])
    assert g(tool_name="terminal", args={"command": f"python {first} && python {second}", "workdir": str(proj)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": f"python {second}", "workdir": str(proj)})["action"] == "approve"


def test_the_chat_card_shows_one_line_for_the_same_change_in_several_places() -> None:
    from workroom.adapters.commands import _card

    change = {"old_text": "$30.2 trillion", "new_text": "$30.6 trillion", "deck": "briefing.pptx", "slide": 2, "where": "Slide 2"}
    view = {"release_id": "r1", "digest": "d" * 64, "changes": [change, dict(change), dict(change), {**change, "old_text": "1.5%", "new_text": "1.8%"}], "flags": []}
    card = _card(view)
    assert card.count("$30.2 trillion -> $30.6 trillion") == 1 and "3 places" in card and "1.5% -> 1.8%" in card


def test_inline_text_of_any_shape_is_checked_in_bounded_time(tmp_path: Path) -> None:
    """Runs of one character, of git, of wildcards or of extensions must not make the guard slow, below the inspection budget or above it."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"x")
    g = make_guard(lambda: [str(proj)])
    for size in (60_000, 300_000):
        for unit in ("A", "*", ".", "git ", "open(", "a.pptx ", "pptx", "'", ";"):
            started = perf_counter()
            g(tool_name="execute_code", args={"code": "write " + unit * (size // len(unit))})
            assert perf_counter() - started < 0.1, (unit, size)


def test_inline_text_over_the_inspection_budget_needs_approval(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    g = make_guard(lambda: [str(proj)])
    assert g(tool_name="execute_code", args={"code": "x = 1  # " + "y" * 70_000})["action"] == "approve"


def test_git_commands_that_rewrite_files_are_still_caught(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"x")
    g = make_guard(lambda: [str(proj)])
    assert g(tool_name="terminal", args={"command": "git checkout -- deck.pptx", "workdir": str(proj)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "git -C . restore deck.pptx", "workdir": str(proj)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": "git status; echo reset", "workdir": str(proj)}) is None
    assert g(tool_name="terminal", args={"command": "rm *.pptx", "workdir": str(proj)})["action"] == "approve"
    assert g(tool_name="terminal", args={"command": f"cp x {proj / 'deck.pptx'}"})["action"] == "approve"
