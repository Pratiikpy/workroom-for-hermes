"""Deliverables: what the agent produced or changed, shown, compared with the version before, and approved as exact bytes by the owner."""

import io
from pathlib import Path

import pytest

from workroom.tests.test_room import project
from workroom.workroom_core.deliverables import diff, excel_grid, kind_of, preview, text_of
from workroom.workroom_core.service import ServiceError


def test_each_kind_of_file_is_recognised() -> None:
    assert [kind_of(x) for x in ("a.md", "b.PNG", "c.pdf", "d.docx", "e.pptx", "f.xlsx", "g.bin")] == ["text", "image", "pdf", "word", "powerpoint", "excel", "other"]


def test_a_text_file_changed_by_the_agent_is_listed_previewed_compared_and_approved(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    f = root / "brief.md"
    f.write_text("# Brief\nRevenue rose.\n")
    svc.snapshot_take(pid, str(f), "write_file")
    f.write_text("# Brief\nRevenue rose 20%.\nCosts fell.\n")
    item = next(d for d in svc.deliverables(pid) if d["path"] == "brief.md")
    assert item["kind"] == "text" and item["status"] == "not reviewed" and len(item["versions"]) == 1
    assert "Costs fell." in svc.deliverable_preview(pid, "brief.md")["text"]
    before = svc.deliverable_preview(pid, "brief.md", item["versions"][0]["id"])["text"]
    assert "Revenue rose." in before and "20%" not in before
    d = svc.deliverable_diff(pid, "brief.md", item["versions"][0]["id"])
    assert d["added"] == 2 and d["removed"] == 1 and "+Costs fell." in d["diff"]
    svc.deliverable_approve(pid, "brief.md")
    assert next(x for x in svc.deliverables(pid) if x["path"] == "brief.md")["status"] == "approved"
    f.write_text("changed again")
    assert next(x for x in svc.deliverables(pid) if x["path"] == "brief.md")["status"] == "changed since approval"


def test_the_agent_can_register_a_file_it_made_with_a_script_but_cannot_approve_it(tmp_path: Path) -> None:
    from workroom.adapters import tools

    root, svc, pid = project(tmp_path)
    (root / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    svc.deliverable_register(pid, "chart.png", "made by plot.py")
    item = next(d for d in svc.deliverables(pid) if d["path"] == "chart.png")
    assert item["registered"]["registered_by"] == "agent" and item["kind"] == "image"
    assert svc.deliverable_preview(pid, "chart.png")["kind"] == "image"
    assert not [n for n in dir(tools) if "approve" in n and "deliverable" in n]
    with pytest.raises(ServiceError):
        svc.deliverable_register(pid, "../outside.png")


def test_a_workbook_is_shown_as_a_grid_with_its_text_and_numbers(tmp_path: Path) -> None:
    from xlsxwriter import Workbook

    buf = io.BytesIO()
    with Workbook(buf) as wb:
        ws = wb.add_worksheet("Results")
        ws.write_row(0, 0, ["Metric", "Q1", "Q2"])
        ws.write_row(1, 0, ["Revenue", 100, 120])
    g = excel_grid(buf.getvalue())
    assert g["sheet"] == "Results" and g["rows"][0] == ["Metric", "Q1", "Q2"] and g["rows"][1][0] == "Revenue" and g["rows"][1][2] in ("120", "120.0")


def test_word_and_powerpoint_compare_by_their_text() -> None:
    from docx import Document

    def word(text: str) -> bytes:
        d = Document()
        d.add_paragraph(text)
        b = io.BytesIO()
        d.save(b)
        return b.getvalue()

    got = diff(word("Revenue was 120."), word("Revenue was 150."), "word", "a", "b")
    assert got["added"] == 1 and got["removed"] == 1 and "+Revenue was 150." in got["diff"]
    assert preview(word("Hello"), "word", "x.docx")["blocks"][0]["text"] == "Hello"


def test_files_without_text_say_so_instead_of_pretending() -> None:
    assert diff(b"\x00\x01", b"\x00\x02", "other", "a", "b")["kind"] == "none"
    assert text_of(b"not a zip", "word") is None
    assert preview(b"x" * 10, "other", "x.bin")["kind"] == "none"


def test_a_version_from_before_the_file_existed_is_explained(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    svc.snapshot_take(pid, str(root / "new.md"), "write_file")
    (root / "new.md").write_text("made")
    sid = svc.snapshots(pid)[0]["id"]
    assert svc.deliverable_preview(pid, "new.md", sid)["kind"] == "none"


def test_one_inbox_lists_what_waits_for_the_owner_in_every_project(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    pid2 = svc.add_project(str(other))["project"]
    svc.room_propose_memory(pid, "Round to thousands", "preference", "chat")
    (other / "memo.md").write_text("draft")
    svc.deliverable_register(pid2, "memo.md", "made by a script")
    att = svc.attention()
    kinds = {(i["project"], i["kind"]) for i in att["items"]}
    assert (pid, "memory") in kinds and (pid2, "deliverable") in kinds and att["could_not_check"] == []
    assert att["counts"]["memory"] == 1 and att["total"] == len(att["items"])
    svc.deliverable_approve(pid2, "memo.md")
    assert (pid2, "deliverable") not in {(i["project"], i["kind"]) for i in svc.attention()["items"]}


def test_a_deck_and_a_report_are_drawn_structurally_without_any_office_program() -> None:
    import io as _io

    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    sl = prs.slides.add_slide(prs.slide_layouts[6])
    tb = sl.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = "Revenue <b>rose</b> 12% & margin held"
    r.font.size = Pt(28)
    buf = _io.BytesIO()
    prs.save(buf)
    got = preview(buf.getvalue(), "powerpoint", "d.pptx")
    assert got["kind"] == "slides" and got["structural"] and "Revenue &lt;b&gt;rose&lt;/b&gt; 12% &amp; margin held" in got["slides"][0]["svg"] and "<b>" not in got["slides"][0]["svg"]
    d = Document()
    d.add_heading("Q2 review", 1)
    d.add_paragraph("Revenue rose 12%.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Metric", "Q2"
    b2 = _io.BytesIO()
    d.save(b2)
    blocks = preview(b2.getvalue(), "word", "r.docx")["blocks"]
    assert [x["type"] for x in blocks] == ["heading", "paragraph", "table"] and blocks[2]["rows"] == [["Metric", "Q2"]]
