"""Roll a report forward one period: figures re-pointed, period words advanced, one release, restorable, refused when incomplete."""
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.adapters.commands import make_approve_command
from workroom.workroom_core.service import NeedsAcknowledgement, Service, ServiceError

HEADER = ["Metric", "Q1 2026", "Q2 2026", "Q3 2026", "Q4 2026"]
ROWS = [["Net revenue", 13_000_000, 14_000_000, 15_100_000, 16_400_000], ["Operating income", 1_850_000, 2_210_000, 2_640_000, 2_900_000]]
BODY = ["Net revenue reached $15.1 million in Q3 2026, up from $14.0 million in Q2 2026.", "Operating income was $2.6 million in Q3 2026."]


def _book(root: Path, header=HEADER, rows=ROWS) -> None:
    with Workbook(str(root / "results.xlsx")) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, header)
        for i, r in enumerate(rows, 1):
            ws.write_row(i, 0, r)


def _deck(root: Path, title: str, body: list[str]) -> None:
    prs = Presentation()
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = title
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Quarterly results"
    for i, line in enumerate(body):
        slide.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8)).text_frame.text = line
    prs.save(str(root / "board.pptx"))


def _texts(root: Path) -> list[str]:
    return [sh.text_frame.text for s in Presentation(root / "board.pptx").slides for sh in s.shapes if sh.has_text_frame]


def _setup(tmp_path: Path, body=None, title="Q3 2026 Board Update", **book):
    root = tmp_path / "proj"
    root.mkdir()
    _book(root, **book)
    _deck(root, title, body or BODY)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, pid, root


def test_a_roll_moves_every_figure_and_every_period_word_in_one_release(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path)
    staged = svc.stage_rollforward(pid)
    assert staged["state"] == "awaiting_approval" and staged["figures"] == 3 and staged["period_words"] == 4
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    texts = _texts(root)
    assert "Q4 2026 Board Update" in texts, "a title slide with no figures follows the deck"
    assert "Net revenue reached $16.4 million in Q4 2026, up from $15.1 million in Q3 2026." in texts
    assert "Operating income was $2.9 million in Q4 2026." in texts


def test_the_ties_follow_the_roll_so_the_next_source_change_updates_the_right_cell(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path)
    staged = svc.stage_rollforward(pid)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    _book(root, rows=[["Net revenue", 13_000_000, 14_000_000, 15_100_000, 17_000_000], ROWS[1]])
    nxt = svc.stage(pid)
    assert {c["old_text"]: c["new_text"] for c in nxt["changes"]} == {"$16.4 million": "$17.0 million"}


def test_restore_undoes_the_whole_roll_including_the_ties(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path)
    before = (root / "board.pptx").read_bytes()
    staged = svc.stage_rollforward(pid)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    assert (root / "board.pptx").read_bytes() != before
    svc.restore_release(pid, staged["release_id"])
    assert (root / "board.pptx").read_bytes() == before
    assert svc.changes_inbox(pid)["changes"] == [], "after a restore the ties point at the old period again, so nothing looks stale"
    assert svc.stage_rollforward(pid)["state"] == "awaiting_approval", "and the roll can be done again"


def test_a_roll_is_refused_naming_every_figure_that_has_no_next_period(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path, header=["Metric", "Q1 2026", "Q2 2026", "Q3 2026"],
                            rows=[["Net revenue", 13_000_000, 14_000_000, 15_100_000], ["Operating income", 1_850_000, 2_210_000, 2_640_000]])
    before = (root / "board.pptx").read_bytes()
    with pytest.raises(ServiceError) as err:
        svc.stage_rollforward(pid)
    assert "Q4 2026" in str(err.value) and "Nothing was changed" in str(err.value)
    assert (root / "board.pptx").read_bytes() == before


def test_a_period_word_without_a_matching_figure_is_left_alone(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path, body=["Net revenue reached $15.1 million in Q3 2026.", "Last year Q2 2026 looked different."])
    staged = svc.stage_rollforward(pid)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    after = _texts(root)
    assert "Last year Q2 2026 looked different." in after and "Net revenue reached $16.4 million in Q4 2026." in after


def test_a_roll_that_makes_a_comparison_false_is_flagged_before_approval(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path, rows=[["Net revenue", 13_000_000, 14_000_000, 15_100_000, 12_000_000], ROWS[1]])
    staged = svc.stage_rollforward(pid)
    assert [f["kind"] for f in staged["flags"]] == ["claim_flip"] and staged["flags"][0]["severity"] == "high"
    with pytest.raises(NeedsAcknowledgement):
        svc.approve_and_publish(pid, staged["release_id"], staged["digest"])


def test_the_chat_card_describes_a_roll(tmp_path: Path) -> None:
    svc, pid, root = _setup(tmp_path)
    svc.stage_rollforward(pid)
    asked: list[str] = []

    def ask(question, choices):
        asked.append(question)
        return choices[0]

    out = make_approve_command(lambda: svc, ask, lambda: [])("", platform=None)
    assert out.startswith("Published") and "rolls your documents forward 1 period" in asked[0] and "Restore undoes the whole roll" in asked[0]


def test_a_roll_that_makes_two_figures_read_the_same_does_not_call_a_true_comparison_false(tmp_path: Path) -> None:
    rows = [["Net revenue", 13_000_000, 14_000_000, 15_000_000, 15_040_000], ROWS[1]]  # Q4 is above Q3 on the source values, yet both will read $15.0 million
    svc, pid, root = _setup(tmp_path, body=["Net revenue reached $15.0 million in Q3 2026, up from $14.0 million in Q2 2026."], rows=rows)
    staged = svc.stage_rollforward(pid)
    assert staged["state"] == "awaiting_approval" and all(f["kind"] != "claim_flip" for f in staged["flags"]), staged["flags"]
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    assert "Net revenue reached $15.0 million in Q4 2026, up from $15.0 million in Q3 2026." in _texts(root)
