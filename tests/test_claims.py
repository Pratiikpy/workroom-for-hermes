"""A reply that claims a file the project does not hold gets one honest line under it; a true claim, a negated one and a reply with no claim are left alone."""

from pathlib import Path

from workroom.adapters import session_cwd
from workroom.adapters.claims import claimed_kinds, make_claim_check

REPLY = "I have researched the market and created a 6-slide board deck with comprehensive sourcing. Slide 1 shows the total."


def check_for(root: Path, staged: list[str]):
    return make_claim_check(lambda: [{"project": "p1", "folder": str(root)}], lambda pid: staged)


def run(check, root: Path, text: str):
    session_cwd.use(lambda: str(root))
    try:
        return check(response_text=text, session_id="s")
    finally:
        session_cwd.use(None)


def test_claims_are_read_from_plain_sentences_and_negations_are_not_claims() -> None:
    assert claimed_kinds(REPLY) == ["deck"]
    assert claimed_kinds("I made the spreadsheet and wrote the report.") == ["report", "workbook"]
    assert claimed_kinds("I could not create the deck because the source was missing.") == []
    assert claimed_kinds("Here is what I found about the market.") == []


def test_a_deck_that_does_not_exist_is_said_not_to_exist_and_what_is_waiting_is_named(tmp_path: Path) -> None:
    out = run(check_for(tmp_path, ["data.xlsx", "sources.xlsx"]), tmp_path, REPLY)
    assert out.startswith(REPLY) and "no deck exists in your folder or is waiting for approval" in out and "data.xlsx, sources.xlsx" in out
    assert "_Workroom:" in out.splitlines()[-1]


def test_a_deck_that_is_only_staged_is_said_not_to_be_written_yet(tmp_path: Path) -> None:
    out = run(check_for(tmp_path, ["board.pptx"]), tmp_path, REPLY)
    assert "board.pptx is waiting for your approval" in out and "nothing is written until you approve" in out


def test_a_true_claim_and_replies_outside_a_project_are_left_alone(tmp_path: Path) -> None:
    (tmp_path / "board.pptx").write_bytes(b"PK")
    assert run(check_for(tmp_path, []), tmp_path, REPLY) is None
    other = tmp_path.parent / (tmp_path.name + "_other")
    other.mkdir()
    assert run(check_for(tmp_path, []), other, REPLY) is None
    assert run(check_for(tmp_path, []), tmp_path, "Short.") is None
