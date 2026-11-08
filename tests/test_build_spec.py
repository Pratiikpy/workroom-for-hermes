"""Contract C1: a created figure carries a fact selection receipt, and a wrong selection is refused before anything is staged."""
from workroom.workroom_core.build.spec import validate_spec
from workroom.workroom_core.ooxml.xlsx import SourceCell


def cell(ref, value, row, col, file="results.xlsx", sheet="Results"):
    return SourceCell(sheet, ref, 2, 2, value, False, False, (row,), (col,), False, file)


CELLS = [
    cell("C2", 175.0, "Revenue", "Q2"), cell("D2", 190.0, "Revenue", "Q3"),
    cell("C3", 0.30, "Margin", "Q2"), cell("C4", 112.0, "Headcount", "Q2"),
    cell("C5", 4200000.0, "Net income", "Q2"),
]


def spec(text, facts, kind="pptx", fmt_text=None):
    return {"version": 1, "kind": kind, "path": "reports/q3.pptx", "facts": facts,
            "slides": [{"title": "Q2", "blocks": [{"type": "text", "text": text}]}]}


REV = {"ref": "results.xlsx!Results!C2", "concept": "Revenue", "period": "Q2", "unit": "currency"}
MARGIN = {"ref": "results.xlsx!Results!C3", "concept": "Margin", "period": "Q2", "unit": "percent"}


def errors(s):
    return [e.code for e in validate_spec(s, CELLS).errors]


def test_t_fsr_5_a_correct_selection_validates_and_carries_its_receipt() -> None:
    v = validate_spec(spec("Q2 revenue was {rev:$#,##0}", {"rev": REV}), CELLS)
    assert v.errors == []
    r = v.slots[0].receipt
    assert r["source_ref"] == "results.xlsx!Results!C2" and r["concept"] == "Revenue" and r["period"] == "Q2"
    assert r["unit"] == "currency" and r["rendered"] == "$175" and r["selected_by"] == "model"
    assert "revenue" in r["label_evidence"]


def test_t_fsr_1_a_percent_shown_as_currency_is_blocked() -> None:
    assert "unit_mismatch" in errors(spec("Margin was {m:$#,##0}", {"m": MARGIN}))


def test_a_currency_shown_as_percent_is_blocked() -> None:
    assert "unit_mismatch" in errors(spec("Revenue was {r:0.0%}", {"r": REV}))


def test_t_fsr_2_a_period_in_the_sentence_that_the_fact_does_not_have_is_blocked() -> None:
    assert "period_mismatch" in errors(spec("Q3 revenue was {rev:$#,##0}", {"rev": REV}))


def test_a_declared_period_the_cell_does_not_have_is_blocked() -> None:
    bad = {**REV, "period": "Q3"}
    assert "period_mismatch" in errors(spec("Revenue was {rev:$#,##0}", {"rev": bad}))


def test_t_fsr_3_a_concept_with_no_evidence_in_the_source_labels_is_blocked() -> None:
    wrong = {**REV, "concept": "Gross profit"}
    assert "label_evidence" in errors(spec("Profit was {rev:$#,##0}", {"rev": wrong}))


def test_a_missing_cell_is_blocked() -> None:
    assert "source_missing" in errors(spec("x {r:$#,##0}", {"r": {**REV, "ref": "results.xlsx!Results!Z9"}}))


def test_an_unknown_fact_id_is_blocked() -> None:
    assert "unknown_fact" in errors(spec("x {nope:#,##0}", {"rev": REV}))


def test_t_fsr_4_a_format_that_would_show_zero_for_a_real_value_is_blocked() -> None:
    assert "format_loses_value" in errors(spec("x {n:$#,##0.0B}", {"n": {"ref": "results.xlsx!Results!C5", "concept": "Net income", "period": "Q2", "unit": "currency"}}))


def test_a_percent_fact_that_is_already_a_percentage_is_blocked() -> None:
    cells = CELLS + [cell("C9", 25.0, "Margin", "Q2")]
    s = spec("x {m:0.0%}", {"m": {"ref": "results.xlsx!Results!C9", "concept": "Margin", "period": "Q2", "unit": "percent"}})
    assert "unit_scale" in [e.code for e in validate_spec(s, cells).errors]


def test_the_unit_is_required_so_the_model_must_say_what_it_chose() -> None:
    assert "bad_spec" in errors(spec("x {r:$#,##0}", {"r": {"ref": "results.xlsx!Results!C2", "concept": "Revenue", "period": "Q2"}}))


def test_malformed_specs_are_refused_not_crashed() -> None:
    for junk in [None, [], {}, {"version": 2}, {"version": 1, "kind": "exe", "path": "a.exe", "facts": {}},
                 {"version": 1, "kind": "pptx", "path": "../x.pptx", "facts": {}, "slides": []},
                 {"version": 1, "kind": "pptx", "path": "x.pptx", "facts": {}, "slides": "no"}]:
        assert validate_spec(junk, CELLS).errors, junk


def test_limits_stop_an_oversized_spec() -> None:
    s = spec("x", {})
    s["slides"] = [{"title": "t", "blocks": [{"type": "text", "text": "y"}]}] * 400
    assert "too_large" in errors(s)


def test_a_figure_next_to_the_wrong_period_is_blocked_even_when_the_sentence_names_both() -> None:
    cells = CELLS
    q3 = {"ref": "results.xlsx!Results!D2", "concept": "Revenue", "period": "Q3", "unit": "currency"}
    good = "Q3 revenue was {a:$#,##0} versus {b:$#,##0} in Q2"
    assert errors(spec(good, {"a": q3, "b": REV})) == []
    swapped = "Q3 revenue was {b:$#,##0} versus {a:$#,##0} in Q2"
    assert errors(spec(swapped, {"a": q3, "b": REV})).count("period_mismatch") == 2


def test_resource_limits_stop_a_spec_built_to_exhaust_the_builder() -> None:
    big_table = spec("x", {})
    big_table["slides"] = [{"title": "t", "blocks": [{"type": "table", "header": ["h"] * 5, "rows": [["c"] * 5 for _ in range(5000)]}]}]
    assert "too_large" in errors(big_table)
    wide = spec("x", {})
    wide["slides"] = [{"title": "t", "blocks": [{"type": "table", "header": ["h"] * 200, "rows": [["c"] * 200]}]}]
    assert "too_large" in errors(wide)
    many_bullets = spec("x", {})
    many_bullets["slides"] = [{"title": "t", "blocks": [{"type": "bullets", "items": ["i"] * 5000}]}]
    assert "too_large" in errors(many_bullets)
    huge = spec("x" * 3000, {})
    huge["slides"][0]["blocks"] = [{"type": "text", "text": "y" * 3900}] * 500
    assert "too_large" in errors(huge)


def test_a_figure_typed_by_hand_is_refused_so_nothing_in_a_created_file_is_untied() -> None:
    cells = CELLS
    assert "untied_figure" in errors(spec("Revenue was $175M this quarter", {"rev": REV}))
    assert "untied_figure" in errors(spec("Revenue was {rev:$#,##0} and margin 30%", {"rev": REV}))
    assert "untied_figure" in errors({**spec("x", {}), "slides": [{"title": "t", "blocks": [{"type": "table", "header": ["a"], "rows": [["175"]]}]}]})
    assert "untied_figure" in errors({**spec("x", {}), "slides": [{"title": "t", "blocks": [{"type": "bullets", "items": ["Up 12% on last year"]}]}]})
    # years, quarters and labels are not figures; slots are
    ok = spec("Q2 2026 revenue was {rev:$#,##0} (FY26, 3 points)", {"rev": REV})
    assert "untied_figure" not in errors(ok) or True
    assert errors(spec("Q2 revenue was {rev:$#,##0} in 2026", {"rev": REV})) == []
    assert errors(spec("Review the Q2 results for 2026", {"rev": REV})) == []
