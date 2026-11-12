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
    assert "1 of 3 figures are not verified" in line and "31.4%" in line
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
    assert "all 1 figures are supported" in written(tool_name="write_file", args={"path": str(out)}, result="{}", session_id="s2")


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


def test_the_deliverables_list_carries_the_proof_and_each_figure_says_where_it_came_from(tmp_path: Path) -> None:
    from workroom.adapters.proof_hooks import make_proof_hooks
    from workroom.tests.test_room import project

    root, svc, pid = project(tmp_path)
    capture, _o, written, _v, _r = make_proof_hooks(lambda: EvidenceStore(svc.data_dir / "evidence.db"))
    capture(tool_name="web_extract", args={"url": "https://example.org/q3"}, result='{"content": "Revenue for the quarter was $4,210 million."}', session_id="s5")
    brief = root / "brief.md"
    svc.snapshot_take(pid, str(brief), "write_file")
    brief.write_text("Revenue for the quarter was $4,210 million. The market will grow 37.5% a year.")
    written(tool_name="write_file", args={"path": str(brief)}, result="{}", session_id="s5")
    item = next(d for d in svc.deliverables(pid) if d["path"] == "brief.md")
    assert item["proof"]["figures"] == 2 and item["proof"]["unsourced"] == 1 and not item["proof"]["stale"]
    got = svc.deliverable_proof(pid, "brief.md")
    states = {f["raw"]: f["state"] for f in got["figures"]}
    assert states["37.5%"] == "unsourced" and states["$4,210 million"] in ("sourced", "candidate") and got["marks_align"]
    src = next(f for f in got["figures"] if f["raw"] == "$4,210 million")
    assert src["ref"] == "https://example.org/q3" and "4,210" in src["excerpt"]
    brief.write_text("changed by hand")
    assert next(d for d in svc.deliverables(pid) if d["path"] == "brief.md")["proof"]["stale"]


def test_a_web_search_result_in_its_real_shape_becomes_evidence_that_supports_a_figure(tmp_path) -> None:
    """The real agent run lost every web search: the result is JSON whose snippets sit in one repr line, which the line reader skipped as page-sized."""
    import json

    from workroom.workroom_core.figure_proof import EvidenceStore, check_text, result_text

    snippet = "Australia's electric vehicle market reached new highs in 2025, with annual sales rising 38 per cent. " + "Filler sentence about the market. " * 40
    result = json.dumps({"success": True, "data": {"web": [{"url": "https://example.org/ev", "title": "EV sales 2025", "description": snippet + "Total EV sales were 157,000 vehicles in 2025."}]}})
    text = result_text(result)
    assert max(len(line) for line in text.split(chr(10))) <= 700 and "157,000" in text
    st = EvidenceStore(tmp_path / "e.db")
    try:
        assert st.add("s1", "web_search", "Australia EV sales 2025", text) is not None
        proofs = check_text("Total EV sales were 157,000 vehicles in 2025, up 38%.", st.items("s1"))
    finally:
        st.close()
    states = {p.raw: p.state for p in proofs}
    assert states.get("157,000") == "sourced" and states.get("38%") != "unsourced"  # "38 per cent" in the source is the same value written differently: not called fabricated


def test_a_figure_printed_in_a_sentence_the_agent_read_is_supported_and_one_printed_elsewhere_is_not() -> None:
    from workroom.workroom_core.figure_proof import Evidence, check_text

    read = ("Tesla remained the top seller of electric vehicles in Australia, reporting 28,856 registrations in 2025 according to the sales data.\n"
            "A football match in Melbourne drew 28,856 spectators on Saturday night.\n")
    items = [Evidence(1, "web_search", "q", 0.0, read, "tool")]
    states = {p.raw: p.state for p in check_text("Tesla was the top seller of electric vehicles in Australia with 28,856 units in 2025.", items)}
    assert states["28,856"] == "sourced"
    unrelated = [Evidence(1, "web_search", "q", 0.0, "A football match in Melbourne drew 28,856 spectators on Saturday night.\n", "tool")]
    states = {p.raw: p.state for p in check_text("Tesla was the top seller of electric vehicles in Australia with 28,856 units in 2025.", unrelated)}
    assert states["28,856"] != "sourced"


def test_tags_are_removed_in_one_pass_even_when_they_never_close() -> None:
    from time import perf_counter

    for html in ("<script" * 43_000, "<" * 300_000, "<style" * 50_000, "<a " * 100_000, "</script " * 33_000, "<script>" + "x" * 300_000, "<b>" * 100_000):
        started = perf_counter()
        plain_text(html, ".html")
        assert perf_counter() - started < 0.1, html[:10]
    assert plain_text("<p>Revenue was <b>$4.2 million</b>.</p><script>var x = 99;</script><style>p{margin:7px}</style>", ".html").split() == ["Revenue", "was", "$4.2", "million", "."]
    assert "99" not in plain_text("<p>ok</p><script>var x = 99;", ".html")


def test_many_figures_in_one_text_are_placed_without_rewalking_it() -> None:
    from time import perf_counter

    from workroom.workroom_core.figure_proof import _Sentences, _sentence

    text = "Revenue was 4.2 million. Costs fell to 3.1 million; margin 12.5%.\nHeadcount 241"
    for start, end in ((12, 15), (40, 43), (60, 64), (text.index("241"), len(text))):
        assert _Sentences(text).around(start, end)[0] == _sentence(text, start, end)
    assert _sentence(text, 12, 15) == "Revenue was 4.2 million"
    assert _sentence(text, text.index("241"), len(text)) == "Headcount 241"
    for big in ("7,", "7 ", "7\n", "1.5 ", "9;"):
        blob = big * (300_000 // len(big))
        started = perf_counter()
        sentences = _Sentences(blob)
        for at in range(0, len(blob) - 2, 97):
            sentences.around(at, at + 1)
        assert perf_counter() - started < 0.5, big
        assert len(sentences.around(150_000, 150_001)[0]) <= 4_001


def test_the_number_reader_costs_no_more_than_the_length_of_a_line() -> None:
    from time import perf_counter

    from workroom.workroom_core.match.numbers import parse_numbers

    for unit in ("1 ", "1,", "(1) ", "f(1) ", "Note 4 ", "1" + " " * 40, "a"):
        took = []
        for size in (40_000, 160_000):
            started = perf_counter()
            parse_numbers(unit * (size // len(unit)))
            took.append(perf_counter() - started)
        assert took[1] < 0.2 or took[1] < took[0] * 10, (unit, took)
    assert [n.raw for n in parse_numbers("see Note 4 and Table 12; revenue was 4,210 (5%) and f(2, 3)")] == ["4,210", "(5%)"]


def test_a_large_numeric_text_is_checked_within_its_limits() -> None:
    from time import perf_counter

    from workroom.workroom_core import figure_proof as fp

    evidence = [fp.Evidence(i, "read_file", f"f{i}", 0.0, "\n".join(f"Item {j} total: {j * 7 + i}" for j in range(2000))) for i in range(1, 12)]
    evidence.append(fp.Evidence(99, "owner", "chat", 0.0, "use 4210 and 17 percent", "owner"))
    for unit in ("7\n", "1 ", "12.5% ", "Total was 4,210 in 2026. "):
        text = unit * (300_000 // len(unit))
        started = perf_counter()
        out = fp.check_text(text, evidence)
        assert perf_counter() - started < 8, unit
        assert len(out) <= fp.MAX_LISTED + fp.MAX_LINE
        late = [p for p in out[fp.MAX_FIGURES:]]
        assert late and all(p.state == "unsourced" and p.how.startswith("not checked") for p in late), unit
    stated = fp.check_text("We will use 4,210 as the base.", evidence)
    assert [p.state for p in stated] == ["stated"]
    idx = fp._Index(evidence, 500)
    assert idx.truncated and len(idx.values) <= 500 + 2000
    assert not fp.build_index(evidence).truncated
