"""Contract C7: the impact engine groups a refresh by source change and decides auto / hold / blocked for every element."""
from pathlib import Path

from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from workroom.workroom_core.project import Project


def _save_workbook(root: Path, revenue: float, headcount: float) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2", "Q3"])
    ws.append(["Revenue", 130, revenue, 190])
    ws.append(["Margin", 0.40, 0.30, 0.33])
    ws.append(["Headcount", 100, 112, headcount])
    wb.save(root / "results.xlsx")


def _make(tmp_path: Path) -> tuple[Project, Path]:
    root = tmp_path / "p"
    root.mkdir()
    _save_workbook(root, 175, 120)
    prs = Presentation()
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(blank)
    s1.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text_frame.text = "Revenue in Q2 was 175 and margin was 30%"
    s2 = prs.slides.add_slide(blank)
    s2.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text_frame.text = "Q2 revenue stands at 175"
    s3 = prs.slides.add_slide(blank)
    s3.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text_frame.text = "Headcount reached 120 people"
    prs.save(root / "deck.pptx")
    proj = Project(root, tmp_path / "state")
    proj.discover()
    proj.db.execute("UPDATE ties SET state='confirmed' WHERE state IN ('accepted','confirm')")
    return proj, root


def test_t_imp_nothing_changed_means_an_empty_inbox(tmp_path: Path) -> None:
    proj, _ = _make(tmp_path)
    assert proj.impact().changes == []


def test_t_imp_4_one_source_change_groups_every_place_it_appears(tmp_path: Path) -> None:
    proj, root = _make(tmp_path)
    _save_workbook(root, 190, 120)
    inbox = proj.impact()
    assert len(inbox.changes) == 1
    ch = inbox.changes[0]
    assert ch.src.endswith("!Results!C2")
    assert (ch.old_value, ch.new_value) == (175, 190)
    assert round(ch.delta_pct, 1) == 8.6
    assert "Revenue" in ch.label
    assert len(ch.elements) == 2 and {e.decision for e in ch.elements} == {"auto"}
    assert sorted(e.slide for e in ch.elements) == [1, 2]
    assert all(e.text_after == "190" and e.text_before == "175" for e in ch.elements)


def test_t_imp_4b_the_inbox_is_sorted_by_consequence(tmp_path: Path) -> None:
    proj, root = _make(tmp_path)
    _save_workbook(root, 176, 180)  # revenue +0.6%, headcount +50%
    inbox = proj.impact()
    assert [c.src.split("!")[-1] for c in inbox.changes] == ["D4", "C2"]


def test_t_imp_1_a_human_edited_element_is_held_and_never_overwritten(tmp_path: Path) -> None:
    proj, root = _make(tmp_path)
    prs = Presentation(root / "deck.pptx")
    for sh in prs.slides[2].shapes:
        if sh.has_text_frame:
            sh.text_frame.paragraphs[0].runs[0].text = "Headcount reached 121 people"
    prs.save(root / "deck.pptx")
    proj.discover()
    _save_workbook(root, 175, 130)
    inbox = proj.impact()
    el = [e for c in inbox.changes for e in c.elements if e.slide == 3][0]
    assert el.decision == "hold" and "by hand" in el.reason
    assert not any(i.new_text == "130" for i in proj.plan_refresh().impacts)


def test_t_imp_blocked_when_the_source_cell_is_gone(tmp_path: Path) -> None:
    proj, root = _make(tmp_path)
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1"])
    ws.append(["Revenue", 130])
    wb.save(root / "results.xlsx")
    inbox = proj.impact()
    assert inbox.blocked, "tied elements whose source disappeared must be listed as blocked"
    assert all(b.decision == "blocked" and "missing" in b.reason for b in inbox.blocked)


def test_t_imp_3_a_release_changes_only_the_affected_numbers(tmp_path: Path) -> None:
    proj, root = _make(tmp_path)
    _save_workbook(root, 190, 120)
    plan = proj.plan_refresh()
    assert plan.files
    out = Presentation(__import__("io").BytesIO(plan.files["deck.pptx"]))
    texts = [sh.text_frame.text for s in out.slides for sh in s.shapes if sh.has_text_frame]
    assert texts == ["Revenue in Q2 was 190 and margin was 30%", "Q2 revenue stands at 190", "Headcount reached 120 people"]


def test_t_imp_service_returns_a_json_ready_inbox_with_plain_locations(tmp_path: Path) -> None:
    import json

    from workroom.workroom_core.service import Service

    proj, root = _make(tmp_path)
    proj.db.close()
    svc = Service(tmp_path / "svc")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    for t in svc.ties(pid):
        if t["state"] == "confirm":
            svc.confirm(pid, t["id"])
    _save_workbook(root, 190, 120)
    inbox = svc.changes_inbox(pid)
    json.dumps(inbox)
    assert len(inbox["changes"]) == 1 and inbox["changes"][0]["counts"]["auto"] == 2
    assert all(e["where"] for e in inbox["changes"][0]["elements"])
    assert inbox["blocked"] == []
