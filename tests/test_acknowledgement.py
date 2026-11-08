"""A release that makes a sentence false cannot be approved until the owner says they have read it, on every approval path."""
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.adapters.commands import APPROVE, APPROVE_SEEN, CANCEL, make_approve_command
from workroom.workroom_core.meaning.decisions import Decisions
from workroom.workroom_core.service import NeedsAcknowledgement, Service

SENTENCE = "Net revenue reached $15.1 million in Q3 2026, up from $14.0 million in Q2 2026."


def _sources(root: Path, q3: float) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q2 2026", "Q3 2026"])
        ws.write_row(1, 0, ["Net revenue", 14_000_000, q3])


def _release(tmp_path: Path, q3: float):
    root = tmp_path / "proj"
    root.mkdir()
    _sources(root, 15_100_000)
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Review"
    slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(1)).text_frame.text = SENTENCE
    prs.save(str(root / "board.pptx"))
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    _sources(root, q3)
    return svc, pid, root, svc.stage(pid)


def test_the_staged_release_carries_the_flag_and_what_could_not_be_checked(tmp_path: Path) -> None:
    svc, pid, _, staged = _release(tmp_path, 13_000_000)
    assert [f["severity"] for f in staged["flags"]] == ["high"] and staged["flags"][0]["where"] == "Slide 1"
    assert staged["coverage"]["claims_read"] == 1
    view = svc.release_view(pid, staged["release_id"])
    assert view["needs_acknowledgement"] == [staged["flags"][0]["id"]]


def test_approval_without_acknowledgement_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    svc, pid, root, staged = _release(tmp_path, 13_000_000)
    before = (root / "board.pptx").read_bytes()
    with pytest.raises(NeedsAcknowledgement) as err:
        svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert err.value.flags[0]["kind"] == "claim_flip" and (root / "board.pptx").read_bytes() == before
    assert svc.release_view(pid, staged["release_id"])["state"] == "awaiting_approval"


def test_approval_with_acknowledgement_publishes_and_remembers_the_decision(tmp_path: Path) -> None:
    svc, pid, root, staged = _release(tmp_path, 13_000_000)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    proj, _ = svc._open(pid)
    assert Decisions(proj.db).get(staged["flags"][0]["id"]) == "acknowledged"
    svc._close_opened()
    texts = [sh.text_frame.text for sh in Presentation(root / "board.pptx").slides[0].shapes if sh.has_text_frame]
    assert any("$13.0 million" in t for t in texts)


def test_a_release_with_nothing_flagged_needs_no_acknowledgement(tmp_path: Path) -> None:
    svc, pid, _, staged = _release(tmp_path, 15_900_000)
    assert staged["flags"] == []
    assert svc.approve_and_publish(pid, staged["release_id"], staged["digest"])["state"] == "published"


def test_the_chat_card_shows_the_sentence_and_asks_for_the_stronger_answer(tmp_path: Path) -> None:
    svc, pid, root, staged = _release(tmp_path, 13_000_000)
    asked: list[tuple[str, list]] = []

    def ask(question, choices):
        asked.append((question, choices))
        return choices[0]

    out = make_approve_command(lambda: svc, ask, lambda: [])("", platform=None)
    assert out.startswith("Published") and asked[0][1] == [APPROVE_SEEN, CANCEL] and APPROVE not in asked[0][1]
    assert "1 sentence to read before you approve" in asked[0][0] and "up from" in asked[0][0] and "now reads:" in asked[0][0]


def test_choosing_the_plain_answer_where_the_stronger_one_is_required_does_nothing(tmp_path: Path) -> None:
    svc, pid, root, staged = _release(tmp_path, 13_000_000)
    before = (root / "board.pptx").read_bytes()
    out = make_approve_command(lambda: svc, lambda q, c: APPROVE, lambda: [])("", platform=None)
    assert out.startswith("No answer was given; nothing was changed") and (root / "board.pptx").read_bytes() == before
