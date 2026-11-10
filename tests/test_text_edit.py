"""Point-to-edit: one scoped text change in a deck or report, staged for approval, with every other part of the file byte-identical."""

import zipfile
from pathlib import Path

import pytest

from workroom.tests.test_flagship_headless import make_workbook
from workroom.workroom_core.service import Service, ServiceError


def project(tmp_path: Path):
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches

    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    tb.text_frame.text = "Our results were strong this quarter."
    tb2 = s.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1))
    tb2.text_frame.text = "Revenue was 120 in Q2."
    prs.save(str(root / "deck.pptx"))
    d = Document()
    d.add_paragraph("Introduction")
    d.add_paragraph("The board met on Tuesday and approved the plan.")
    d.save(str(root / "report.docx"))
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return root, svc, pid


def parts(path: Path) -> dict[str, bytes]:
    z = zipfile.ZipFile(path)
    return {n: z.read(n) for n in z.namelist()}


def test_a_deck_edit_changes_one_shape_and_only_one_part_of_the_file(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    where = svc.find_text(pid, "deck.pptx", "strong this quarter")["matches"]
    assert len(where) == 1
    staged = svc.stage_text_edit(pid, "deck.pptx", where[0]["locator"], "strong this quarter", "ahead of plan")
    assert staged["state"] == "awaiting_approval" and staged["other_parts_identical"] and staged["part_changed"].startswith("ppt/slides/slide")
    before = parts(root / "deck.pptx")
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    after = parts(root / "deck.pptx")
    assert [n for n in before if before[n] != after[n]] == [staged["part_changed"]]
    assert b"ahead of plan" in after[staged["part_changed"]] and b"strong this quarter" not in after[staged["part_changed"]]


def test_a_report_edit_changes_one_paragraph(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    where = svc.find_text(pid, "report.docx", "met on Tuesday")["matches"][0]
    staged = svc.stage_text_edit(pid, "report.docx", where["locator"], "on Tuesday", "on Thursday")
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    from docx import Document

    assert [p.text for p in Document(str(root / "report.docx")).paragraphs] == ["Introduction", "The board met on Thursday and approved the plan."]


def test_nothing_is_written_until_the_owner_approves_and_a_restore_brings_it_back(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    original = (root / "deck.pptx").read_bytes()
    loc = svc.find_text(pid, "deck.pptx", "strong")["matches"][0]["locator"]
    staged = svc.stage_text_edit(pid, "deck.pptx", loc, "strong", "weak")
    assert (root / "deck.pptx").read_bytes() == original
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    assert (root / "deck.pptx").read_bytes() != original
    svc.restore_release(pid, staged["release_id"])
    assert (root / "deck.pptx").read_bytes() == original


def test_wrong_text_wrong_place_and_unsafe_requests_are_refused(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    loc = svc.find_text(pid, "deck.pptx", "strong")["matches"][0]["locator"]
    for old in ("not in the slide", ""):
        with pytest.raises(ServiceError):
            svc.stage_text_edit(pid, "deck.pptx", loc, old, "x")
    with pytest.raises(ServiceError):
        svc.stage_text_edit(pid, "deck.pptx", {"slide": 9, "shape": 99}, "strong", "weak")
    with pytest.raises(ServiceError):
        svc.stage_text_edit(pid, "../outside.pptx", loc, "strong", "weak")
    with pytest.raises(ServiceError):
        svc.stage_text_edit(pid, "results.xlsx", loc, "a", "b")


def test_a_linked_figure_is_not_edited_here(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    svc.discover(pid)
    ties = [t for t in svc.ties(pid) if t["deck"] == "deck.pptx" and t["state"] in ("accepted", "confirmed")]
    if not ties:
        pytest.skip("this sample links no figure in the deck")
    loc = svc.find_text(pid, "deck.pptx", "Revenue was")["matches"][0]["locator"]
    with pytest.raises(ServiceError, match="linked"):
        svc.stage_text_edit(pid, "deck.pptx", loc, ties[0]["text"], "999")
