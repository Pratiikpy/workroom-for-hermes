"""A workbook created from a spec carries tied number cells, keeps its own formulas, and follows the source workbook through a release."""
from pathlib import Path

from openpyxl import load_workbook

from workroom.tests.test_create_flow import SPEC, _svc, _workbook
from workroom.workroom_core.build.spec import validate_spec
from workroom.workroom_core.ooxml.xlsx import SourceCell

XSPEC = {
    "version": 1, "kind": "xlsx", "path": "summary.xlsx", "facts": SPEC["facts"],
    "sheets": [{"name": "Summary", "rows": [
        ["Metric", "Q2"],
        ["Revenue", {"fact": "rev", "format": "$#,##0"}],
        ["Margin", {"fact": "mar", "format": "0.0%"}],
        ["Revenue doubled", {"formula": "=B2*2"}],
    ]}],
}


def test_t_bld_xlsx_validation_rules() -> None:
    cells = [SourceCell("Results", "C2", 2, 3, 175.0, False, False, ("Revenue",), ("Q2",), False, "results.xlsx"),
             SourceCell("Results", "C3", 3, 3, 0.3, False, False, ("Margin",), ("Q2",), False, "results.xlsx"),
             SourceCell("Results", "B2", 2, 2, 130.0, False, False, ("Revenue",), ("Q1",), False, "results.xlsx")]
    assert validate_spec(XSPEC, cells).errors == []
    scaled = {**XSPEC, "sheets": [{"name": "S", "rows": [[{"fact": "rev", "format": "$#,##0.0M"}]]}]}
    assert "bad_format" in [e.code for e in validate_spec(scaled, cells).errors]
    wrong = {**XSPEC, "sheets": [{"name": "S", "rows": [[{"fact": "mar", "format": "$#,##0"}]]}]}
    assert "unit_mismatch" in [e.code for e in validate_spec(wrong, cells).errors]
    inline = {**XSPEC, "sheets": [{"name": "S", "rows": [["Revenue {rev:$#,##0}"]]}]}
    assert "bad_spec" in [e.code for e in validate_spec(inline, cells).errors]
    for bad in ({"name": "a/b", "rows": []}, {"name": "x", "rows": [[None]]}, {"name": "x", "rows": [[{"formula": "SUM(A1)"}]]}):
        assert validate_spec({**XSPEC, "sheets": [bad]}, cells).errors


def test_a_created_workbook_follows_the_source_and_keeps_its_formulas(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, XSPEC)
    assert staged["state"] == "awaiting_approval", staged
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    ws = load_workbook(root / "summary.xlsx")["Summary"]
    assert ws["B2"].value == 175 and ws["B3"].value == 0.3 and ws["B4"].value == "=B2*2"
    assert ws["B2"].number_format == '"$"#,##0' and ws["B3"].number_format == "0.0%" and ws["A1"].font.bold
    ties = [t for t in svc.ties(pid) if t["deck"] == "summary.xlsx"]
    assert len(ties) == 2 and {t["state"] for t in ties} == {"confirmed"}

    _workbook(root, 190)
    upd = svc.stage(pid)
    assert upd["state"] == "awaiting_approval", upd
    svc.approve_and_publish(pid, upd["release_id"], upd["digest"])
    ws = load_workbook(root / "summary.xlsx")["Summary"]
    assert ws["B2"].value == 190 and ws["B3"].value == 0.3 and ws["B4"].value == "=B2*2"
    assert svc.plan(pid)["changes"] == []
    svc.restore_release(pid, upd["release_id"])
    assert load_workbook(root / "summary.xlsx")["Summary"]["B2"].value == 175


def test_a_created_workbook_never_becomes_a_source_and_is_forgotten_on_restore(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, XSPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert all(not c["ref"].startswith("summary.xlsx") for c in svc.source_cells(pid, "")["cells"])
    svc.discover(pid)
    assert len([t for t in svc.ties(pid) if t["deck"] == "summary.xlsx"]) == 2, "finding links must keep the born ties of the created workbook"
    svc.restore_release(pid, staged["release_id"])
    assert not (root / "summary.xlsx").exists() and svc.ties(pid) == []


def test_a_number_typed_into_a_workbook_is_refused_unless_declared_as_an_input(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    typed = {**XSPEC, "path": "typed.xlsx", "sheets": [{"name": "S", "rows": [["Revenue", 999000000]]}]}
    out = svc.create_from_spec(pid, typed)
    assert out["state"] == "refused" and out["errors"][0]["code"] == "untied_figure" and "example" in out
    declared = {**XSPEC, "path": "typed.xlsx", "sheets": [{"name": "S", "rows": [["Growth assumption", {"input": 0.05}]]}]}
    ok = svc.create_from_spec(pid, declared)
    assert ok["state"] == "awaiting_approval"
    assert any("hand-entered" in n for n in ok["held"]) and "hand-entered" in ok["changes"][0]["new_text"]
    svc.approve_and_publish(pid, ok["release_id"], ok["digest"])
    assert load_workbook(root / "typed.xlsx")["S"]["B1"].value == 0.05
