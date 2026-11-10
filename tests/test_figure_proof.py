"""Proof of figures: each figure in a text the agent wrote is sourced, calculated, stated by the owner, or unsourced, judged from what the tools returned."""

from pathlib import Path

from workroom.workroom_core.figure_proof import EvidenceStore, check_text, plain_text, summary


def store(tmp_path: Path, *items: tuple[str, str, str, str]) -> list:
    st = EvidenceStore(tmp_path / "ev.db")
    for tool, ref, text, kind in items:
        st.add("s1", tool, ref, text, kind)
    return st.items("s1")


def states(text: str, items) -> dict[str, str]:
    return {p.raw: p.state for p in check_text(text, items)}


def test_a_figure_read_from_a_page_is_sourced_and_names_where_it_came_from(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "https://example.org/q3", "Revenue for the quarter was $4,210 million, up from $3,980 million.", "tool"))
    proofs = check_text("Revenue reached $4,210 million this quarter.", items)
    assert [(p.raw, p.state, p.ref) for p in proofs] == [("$4,210 million", "sourced", "https://example.org/q3")]
    assert "4,210" in proofs[0].excerpt


def test_rounding_and_scale_words_written_by_the_agent_still_match(tmp_path: Path) -> None:
    items = store(tmp_path, ("read_file", "data.csv", "region,revenue\nNorth,4210000\nSouth,0.473", "tool"))
    got = states("North brought in $4.21 million and South's margin was 47.3%.", items)
    assert got == {"$4.21 million": "sourced", "47.3%": "sourced"}


def test_an_invented_figure_is_unsourced(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "https://example.org", "Revenue was $4,210 million.", "tool"))
    got = states("Revenue was $4,210 million and the market grew 37.5% a year.", items)
    assert got["37.5%"] == "unsourced" and got["$4,210 million"] == "sourced"


def test_a_figure_derived_from_two_read_figures_is_calculated(tmp_path: Path) -> None:
    items = store(tmp_path, ("read_file", "results.md", "Revenue 2025: 5,280. Revenue 2024: 4,800.", "tool"))
    proofs = {p.raw: p for p in check_text("Revenue grew 10.0% to 5,280, an increase of 480.", items)}
    assert proofs["10.0%"].state == "calculated" and "change from" in proofs["10.0%"].how
    assert proofs["480"].state == "calculated" and proofs["5,280"].state in ("sourced", "candidate")  # the sentence does not say which year; the reader may ask


def test_a_figure_the_owner_gave_in_chat_is_stated(tmp_path: Path) -> None:
    items = store(tmp_path, ("owner", "chat", "Use a budget of 125,000 for the launch.", "owner"))
    assert states("The launch budget is 125,000.", items) == {"125,000": "stated"}


def test_years_list_markers_and_heading_numbers_are_not_figures(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "u", "Sales were 812 units.", "tool"))
    text = "## 2. Results for 2025\n1. Sales were 812 units in 2025.\n3) Next steps"
    assert states(text, items) == {"812": "sourced"}


def test_small_round_numbers_are_marked_weak(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "u", "There are 3 offices and 40 staff.", "tool"))
    proofs = {p.raw: p for p in check_text("We run 3 offices with 40 staff.", items)}
    assert proofs["3"].weak and proofs["40"].weak and proofs["3"].state == "sourced"


def test_html_is_checked_on_its_visible_text(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "u", "Margin was 12.5%.", "tool"))
    text = plain_text('<html><style>.x{width:900px}</style><p class="m2">Margin was <b>12.5%</b></p></html>', ".html")
    assert states(text, items) == {"12.5%": "sourced"}


def test_evidence_is_capped_deduplicated_and_skips_text_without_figures(tmp_path: Path) -> None:
    st = EvidenceStore(tmp_path / "ev.db")
    assert st.add("s1", "web_extract", "u", "no numbers here", "tool") is None
    first = st.add("s1", "web_extract", "u", "Revenue 4,210", "tool")
    assert first is not None and st.add("s1", "web_extract", "u", "Revenue 4,210", "tool") is None
    assert len(st.items("s1")) == 1 and st.items("other") == []
    assert st.forget("s1") == 1


def test_the_summary_counts_each_state(tmp_path: Path) -> None:
    items = store(tmp_path, ("web_extract", "u", "Revenue 4,210", "tool"))
    s = summary(check_text("Revenue 4,210 and growth 77.7%.", items))
    assert s["figures"] == 2 and s["sourced"] == 1 and s["unsourced"] == 1 and s["unsourced_figures"] == ["77.7%"]


def test_the_hooks_capture_reading_check_the_written_file_and_ask_once(tmp_path: Path) -> None:
    from workroom.adapters.proof_hooks import make_proof_hooks

    db = tmp_path / "ev.db"
    capture, owner, written, verify, _reply = make_proof_hooks(lambda: EvidenceStore(db))
    folder = tmp_path / "work"
    folder.mkdir()
    capture(tool_name="web_extract", args={"url": "https://example.org/q3"}, result='{"content": "Revenue was $4,210 million in Q3."}', session_id="s9")
    owner(user_message="Assume a budget of 125,000.", session_id="s9")
    brief = folder / "brief.md"
    brief.write_text("# Brief\nRevenue was $4,210 million. Budget 125,000. Market share 31.4%.\n")
    line = written(tool_name="write_file", args={"path": str(brief), "content": "..."}, result='{"ok": true}', session_id="s9")
    assert "1 of 3 figures have no source" in line and "31.4%" in line
    st = EvidenceStore(db)
    rec = st.proof(str(brief.resolve()))
    st.close()
    assert rec["summary"]["sourced"] + rec["summary"]["candidate"] == 1 and rec["summary"]["stated"] == 1 and rec["summary"]["unsourced"] == 1
    again = verify(session_id="s9", attempt=0, changed_paths=[str(brief)])
    assert again["action"] == "continue" and "31.4%" in again["message"]
    assert verify(session_id="s9", attempt=1, changed_paths=[str(brief)]) is None  # asks once
    assert written(tool_name="write_file", args={"path": str(folder / "data.bin")}, result="{}", session_id="s9") is None
    assert capture(tool_name="web_extract", args=None, result=None) is None  # never raises


def test_a_workbook_read_with_read_file_counts_as_evidence(tmp_path: Path) -> None:
    from xlsxwriter import Workbook

    from workroom.adapters.proof_hooks import make_proof_hooks

    db = tmp_path / "ev.db"
    capture, _owner, written, _verify, _reply = make_proof_hooks(lambda: EvidenceStore(db))
    book = tmp_path / "results.xlsx"
    with Workbook(str(book)) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q3"])
        ws.write_row(1, 0, ["Revenue", 4210.5])
    capture(tool_name="read_file", args={"path": str(book)}, result='{"error": "binary file"}', session_id="s2")
    out = tmp_path / "summary.md"
    out.write_text("Q3 revenue was 4,210.5.")
    assert "all 1 figures trace" in written(tool_name="write_file", args={"path": str(out)}, result="{}", session_id="s2")


def test_a_reply_with_an_unsourced_figure_gets_one_line_and_is_otherwise_unchanged(tmp_path: Path) -> None:
    from workroom.adapters.proof_hooks import make_proof_hooks

    db = tmp_path / "ev.db"
    capture, _owner, _written, _verify, reply = make_proof_hooks(lambda: EvidenceStore(db))
    capture(tool_name="web_extract", args={"url": "https://example.org"}, result='{"content": "Revenue for Q3 was $4,210 million."}', session_id="s3")
    text = "Revenue for Q3 was $4,210 million and the market grows 37.5% a year."
    out = reply(response_text=text, session_id="s3")
    assert out.startswith(text) and "37.5%" in out.split(text, 1)[1] and "$4,210" not in out.split(text, 1)[1]
    assert reply(response_text="Here are 3 options.", session_id="s3") is None  # small counts are not flagged
    assert reply(response_text="Revenue for Q3 was $4,210 million.", session_id="s3") is None
