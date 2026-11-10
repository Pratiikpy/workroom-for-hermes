"""The safety net under the shell guard: a managed Office file changed by a shell tool is put back, the agent's version is kept, and the agent is told."""

import io
import subprocess
import sys
from pathlib import Path

from pptx import Presentation

from workroom.adapters import tripwire
from workroom.adapters.tripwire import make_tripwire
from workroom.tests.test_room import project


def deck(text: str) -> bytes:
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[5]).shapes.title.text = text
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def net(root: Path, svc, pid, published: bool = False):
    kept: list[tuple[str, str, bytes]] = []
    notes: list[tuple[str, str]] = []
    before, after = make_tripwire(lambda: [{"project": pid, "folder": str(root)}], lambda p, r, d: kept.append((p, r, d)), lambda p, t: published,
                                  lambda p, r, o: notes.append((r, o)))
    return before, after, kept, notes


KW = {"session_id": "s", "tool_call_id": "c1", "task_id": "t"}


def test_a_script_that_saves_the_deck_directly_is_undone_and_the_agent_is_told(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    original = deck("Q1 2025 briefing")
    (root / "briefing.pptx").write_bytes(original)
    before, after, kept, notes = net(root, svc, pid)
    before(tool_name="terminal", args={"command": "python3 edit.py"}, **KW)
    (root / "briefing.pptx").write_bytes(deck("Q2 2025 briefing, edited by hand"))  # what the agent's script did
    out = after(tool_name="terminal", args={}, result="done", **KW)
    assert (root / "briefing.pptx").read_bytes() == original
    assert out.startswith("done") and "put briefing.pptx back" in out and "workroom_stage_release" in out
    assert kept and kept[0][1] == "briefing.pptx" and "edited by hand" in Presentation(io.BytesIO(kept[0][2])).slides[0].shapes.title.text and notes == [("briefing.pptx", "restored")]


def test_a_new_office_file_is_removed_and_a_deleted_one_comes_back(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    keep = deck("kept")
    (root / "board.pptx").write_bytes(keep)
    before, after, kept, notes = net(root, svc, pid)
    before(tool_name="bash", args={}, **KW)
    (root / "board.pptx").unlink()
    (root / "sneaky.pptx").write_bytes(deck("new"))
    out = after(tool_name="bash", args={}, result="ok", **KW)
    assert (root / "board.pptx").read_bytes() == keep and not (root / "sneaky.pptx").exists()
    assert "board.pptx" in out and "sneaky.pptx" in out and {r for r, _ in notes} == {"board.pptx", "sneaky.pptx"}
    assert any(k[1] == "sneaky.pptx" for k in kept)  # the agent's new file is kept aside, not destroyed


def test_nothing_changed_other_tools_and_an_owner_release_are_left_alone(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    (root / "briefing.pptx").write_bytes(deck("a"))
    before, after, kept, notes = net(root, svc, pid)
    before(tool_name="terminal", args={}, **KW)
    assert after(tool_name="terminal", args={}, result="ls output", **KW) is None
    before(tool_name="read_file", args={}, **KW)
    (root / "briefing.pptx").write_bytes(deck("changed by a non-shell tool"))
    assert after(tool_name="read_file", args={}, result="x", **KW) is None  # the file tools have their own guard
    before2, after2, kept2, _ = net(root, svc, pid, published=True)
    before2(tool_name="terminal", args={}, **KW)
    (root / "briefing.pptx").write_bytes(deck("the owner approved a release meanwhile"))
    assert after2(tool_name="terminal", args={}, result="ok", **KW) is None and kept2 == []


def test_a_file_too_large_to_keep_is_reported_not_silently_left(tmp_path: Path, monkeypatch) -> None:
    root, svc, pid = project(tmp_path)
    (root / "big.pptx").write_bytes(deck("a"))
    monkeypatch.setattr(tripwire, "MAX_FILE", 10)
    before, after, kept, notes = net(root, svc, pid)
    before(tool_name="terminal", args={}, **KW)
    (root / "big.pptx").write_bytes(deck("b" * 50))
    out = after(tool_name="terminal", args={}, result="ok", **KW)
    assert "Could not put back big.pptx" in out and notes == [("big.pptx", "changed and could not be restored")]


def test_a_real_python_process_saving_the_deck_is_caught_end_to_end_and_reaches_the_inbox(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    original = deck("Q1 2025 briefing")
    (root / "briefing.pptx").write_bytes(original)
    before, after = make_tripwire(lambda: svc.projects(), svc.tripwire_keep, lambda p, t: svc.tripwire_published_since(p, t), svc.tripwire_note)
    before(tool_name="terminal", args={}, **KW)
    script = "from pptx import Presentation\np = Presentation('briefing.pptx')\np.slides[0].shapes.title.text = 'Q2'\np.save('briefing.pptx')\n"
    subprocess.run([sys.executable, "-c", script], cwd=str(root), check=True, timeout=60)
    assert (root / "briefing.pptx").read_bytes() != original
    out = after(tool_name="terminal", args={}, result="saved", **KW)
    assert out and (root / "briefing.pptx").read_bytes() == original
    kept = list((svc.data_dir / "projects" / pid / "rejected").glob("*briefing.pptx"))
    assert len(kept) == 1 and Presentation(str(kept[0])).slides[0].shapes.title.text == "Q2"
    assert any(i["kind"] == "bypass" and "briefing.pptx" in i["title"] for i in svc.attention()["items"])
    svc.tripwire_dismiss(pid)
    assert not any(i["kind"] == "bypass" for i in svc.attention()["items"]) and kept[0].exists()
