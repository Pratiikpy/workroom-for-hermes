"""Journey J1 at the service level: create from a spec, approve, change the source, update, restore. Real files, real releases."""
import io
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation

from workroom.workroom_core.service import Service

SPEC = {
    "version": 1, "kind": "pptx", "path": "reports/q2.pptx",
    "facts": {
        "rev": {"ref": "results.xlsx!Results!C2", "concept": "Revenue", "period": "Q2", "unit": "currency"},
        "mar": {"ref": "results.xlsx!Results!C3", "concept": "Margin", "period": "Q2", "unit": "percent"},
        "q1": {"ref": "results.xlsx!Results!B2", "concept": "Revenue", "period": "Q1", "unit": "currency"},
    },
    "slides": [
        {"title": "Q2 review", "blocks": [
            {"type": "text", "text": "Q2 revenue was {rev:$#,##0} and margin {mar:0.0%}."},
            {"type": "table", "header": ["Metric", "Q1", "Q2"], "rows": [["Revenue", "{q1:$#,##0}", "{rev:$#,##0}"]]},
        ]},
    ],
}


def _workbook(root: Path, q2: float) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2"])
    ws.append(["Revenue", 130, q2])
    ws.append(["Margin", 0.40, 0.30])
    wb.save(root / "results.xlsx")


def _svc(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root, 175)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    return svc, pid, root


def _texts(path: Path) -> list[str]:
    prs = Presentation(path)
    out = []
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if sh.has_table:
                out += [sh.table.cell(r, c).text for r in range(len(sh.table.rows)) for c in range(len(sh.table.columns))]
    return out


def test_j1_create_approve_update_restore(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, SPEC)
    assert staged["state"] == "awaiting_approval", staged
    assert len(staged["figures"]) == 4 and not (root / "reports").exists()
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert "Q2 revenue was $175 and margin 30.0%." in _texts(root / "reports/q2.pptx")

    ties = svc.ties(pid)
    assert len(ties) == 4 and {t["state"] for t in ties} == {"confirmed"}
    assert svc.plan(pid)["changes"] == []

    _workbook(root, 190)
    inbox = svc.changes_inbox(pid)
    assert len(inbox["changes"]) == 1 and inbox["changes"][0]["counts"]["auto"] == 2
    upd = svc.stage(pid)
    svc.approve_and_publish(pid, upd["release_id"], upd["digest"])
    texts = _texts(root / "reports/q2.pptx")
    assert "Q2 revenue was $190 and margin 30.0%." in texts and "$190" in texts and "$130" in texts and "$175" not in texts

    svc.restore_release(pid, upd["release_id"])
    assert "Q2 revenue was $175 and margin 30.0%." in _texts(root / "reports/q2.pptx")
    svc.restore_release(pid, staged["release_id"])
    assert not (root / "reports/q2.pptx").exists()
    assert svc.ties(pid) == []


def test_a_wrong_selection_is_refused_and_nothing_is_staged(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    bad = {**SPEC, "slides": [{"title": "t", "blocks": [{"type": "text", "text": "Margin was {mar:$#,##0}"}]}]}
    out = svc.create_from_spec(pid, bad)
    assert out["state"] == "refused" and out["errors"][0]["code"] == "unit_mismatch"
    assert not (root / "reports").exists() and svc.releases(pid) == []


def test_creating_over_an_existing_file_is_refused(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    (root / "reports").mkdir()
    (root / "reports/q2.pptx").write_bytes(b"mine")
    out = svc.create_from_spec(pid, SPEC)
    assert out["state"] == "refused" and out["errors"][0]["code"] == "exists"
    assert (root / "reports/q2.pptx").read_bytes() == b"mine"


def test_a_docx_report_is_created_with_born_ties_too(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    spec = {"version": 1, "kind": "docx", "path": "q2.docx", "facts": SPEC["facts"], "blocks": [
        {"type": "heading", "level": 1, "text": "Q2 review"},
        {"type": "paragraph", "text": "Q2 revenue was {rev:$#,##0}."},
        {"type": "table", "header": ["Metric", "Q2"], "rows": [["Margin", "{mar:0.0%}"]]},
    ]}
    staged = svc.create_from_spec(pid, spec)
    assert staged["state"] == "awaiting_approval", staged
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    _workbook(root, 200)
    upd = svc.stage(pid)
    svc.approve_and_publish(pid, upd["release_id"], upd["digest"])
    doc = Document(root / "q2.docx")
    assert "Q2 revenue was $200." in [p.text for p in doc.paragraphs]


def test_the_agent_can_find_cells_by_label(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    out = svc.source_cells(pid, "margin q2")
    assert out["cells"][0]["ref"] == "results.xlsx!Results!C3" and out["cells"][0]["value"] == 0.30
    assert svc.source_cells(pid, "nothing like this")["cells"] == []
    assert svc.source_cells(pid, "", limit=2)["shown"] == 2


def test_a_staged_create_release_is_listed_for_the_owner_with_its_figures(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    assert svc.awaiting(pid) == []
    staged = svc.create_from_spec(pid, SPEC)
    waiting = svc.awaiting(pid)
    assert [w["release_id"] for w in waiting] == [staged["release_id"]]
    assert waiting[0]["created"] is True and len(waiting[0]["figures"]) == 4
    assert waiting[0]["figures"][0]["source"].startswith("results.xlsx!Results!")
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert svc.awaiting(pid) == []


CHART_SPEC = {
    "version": 1, "kind": "pptx", "path": "reports/trend.pptx",
    "facts": SPEC["facts"],
    "slides": [{"title": "Revenue trend", "blocks": [
        {"type": "chart", "kind": "bar", "title": "Revenue", "categories": ["Q1", "Q2"], "series": [{"name": "Revenue", "facts": ["q1", "rev"]}]}]}],
}


def _chart_values(path: Path) -> list[float]:
    prs = Presentation(path)
    ch = next(s.chart for s in prs.slides[0].shapes if s.has_chart)
    return list(ch.plots[0].series[0].values)


def test_chart_points_are_tied_and_follow_the_source(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    staged = svc.create_from_spec(pid, CHART_SPEC)
    assert staged["state"] == "awaiting_approval", staged
    assert len(staged["figures"]) == 2 and all(f["where"].endswith(("points[0]", "points[1]")) or "chart" in f["where"] for f in staged["figures"])
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert _chart_values(root / "reports/trend.pptx") == [130.0, 175.0]
    assert len(svc.ties(pid)) == 2

    _workbook(root, 190)
    inbox = svc.changes_inbox(pid)
    assert inbox["changes"][0]["counts"]["auto"] == 1
    upd = svc.stage(pid)
    svc.approve_and_publish(pid, upd["release_id"], upd["digest"])
    assert _chart_values(root / "reports/trend.pptx") == [130.0, 190.0]
    assert svc.plan(pid)["changes"] == []
    svc.discover(pid)
    assert len(svc.ties(pid)) == 2, "re-finding links must not drop or duplicate chart ties"
    svc.restore_release(pid, upd["release_id"])
    assert _chart_values(root / "reports/trend.pptx") == [130.0, 175.0]


def test_a_chart_with_a_missing_or_repeated_category_is_refused(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    bad = {**CHART_SPEC, "slides": [{"title": "t", "blocks": [{"type": "chart", "kind": "bar", "categories": ["Q1", "Q1"], "series": [{"name": "R", "facts": ["q1", "rev"]}]}]}]}
    assert svc.create_from_spec(pid, bad)["errors"][0]["code"] == "bad_spec"
    short = {**CHART_SPEC, "slides": [{"title": "t", "blocks": [{"type": "chart", "kind": "bar", "categories": ["Q1", "Q2"], "series": [{"name": "R", "facts": ["q1"]}]}]}]}
    assert svc.create_from_spec(pid, short)["errors"][0]["code"] == "bad_spec"


def test_a_project_brand_file_themes_created_decks_unless_the_spec_sets_its_own(tmp_path: Path) -> None:
    import json

    svc, pid, root = _svc(tmp_path)
    (root / "brand.json").write_text(json.dumps({"accent": "7C3AED", "font": "Arial"}), encoding="utf-8")
    staged = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    prs = Presentation(root / "reports/q2.pptx")
    title = next(s for s in prs.slides[0].shapes if s.name == "Title")
    assert title.text_frame.paragraphs[0].runs[0].font.name == "Arial"
    rule = next(s for s in prs.slides[0].shapes if s.name == "Title rule")
    assert str(rule.fill.fore_color.rgb) == "7C3AED"
    own = {**SPEC, "path": "reports/own.pptx", "theme": {"accent": "0F766E"}}
    st2 = svc.create_from_spec(pid, own)
    svc.approve_and_publish(pid, st2["release_id"], st2["digest"])
    rule2 = next(s for s in Presentation(root / "reports/own.pptx").slides[0].shapes if s.name == "Title rule")
    assert str(rule2.fill.fore_color.rgb) == "0F766E"


def test_an_invalid_brand_file_is_reported_and_ignored(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    (root / "brand.json").write_text('{"accent": "red", "evil": 1}', encoding="utf-8")
    out = svc.create_from_spec(pid, SPEC)
    assert out["state"] == "awaiting_approval" and any("brand.json" in n for n in out["held"])
