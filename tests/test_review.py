"""The review room: pages drawn by Office with the linked figures marked, and a structural list where Office is missing."""

from pathlib import Path

import pytest

from workroom.tests.test_docx import make_docx
from workroom.tests.test_flagship_headless import change_source, make_workbook
from workroom.workroom_core import render, review
from workroom.workroom_core.service import Service, ServiceError

drawn = pytest.mark.skipif(not render.available(".docx"), reason="needs Word and pypdfium2 on this machine")


def project(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "report.docx").write_bytes(make_docx())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return root, svc, pid


def test_figures_of_the_document_are_lined_up_with_figures_of_the_page_in_order() -> None:
    doc = ["2025", "120", "120", "25%", "100", "120"]
    page = ["120", "120", "7", "25%", "100", "120"]  # the page has a page number, and the document a year the page does not show as a figure
    found = review.align(doc, page)
    assert found == {1: 0, 2: 1, 3: 3, 4: 4, 5: 5}
    assert review.align([], ["1"]) == {} and review.align(["1"], []) == {}


def test_a_document_that_cannot_be_drawn_is_listed_in_a_view_that_says_so(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    change_source(root, "C2", 150)
    view = svc.review_structural(pid, "report.docx")
    assert "not a drawing" in view["label"]
    changing = [r for r in view["rows"] if r["kind"] == "changes"]
    assert {r["text"] for r in changing} == {"120"} and {r["new_text"] for r in changing} == {"150"}
    asked = [r for r in view["rows"] if r["kind"] == "asked"]
    assert asked and asked[0]["new_text"] == ""  # the decoy is not marked as changing


def test_only_documents_of_the_project_can_be_asked_for(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    for bad in ("../results.xlsx", r"C:\Windows\win.ini", "nothing.docx", ""):
        with pytest.raises(ServiceError, match="not in the project"):
            svc.review_page(pid, bad, "before", 1)
    with pytest.raises(ServiceError, match="before or after"):
        svc.review_page(pid, "report.docx", "sideways", 1)


def test_the_overview_counts_marks_by_kind_without_touching_the_report(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    change_source(root, "C2", 150)
    before = (root / "report.docx").read_bytes()
    doc = svc.review_overview(pid)["documents"][0]
    assert doc["counts"]["changes"] == 2 and doc["counts"]["asked"] == 1 and doc["changes_in_plan"] is True
    assert (root / "report.docx").read_bytes() == before


@drawn
def test_the_real_page_is_drawn_and_the_changing_figures_are_marked_before_and_after(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    change_source(root, "C2", 150)
    now = svc.review_page(pid, "report.docx", "before", 1)
    after = svc.review_page(pid, "report.docx", "after", 1)
    assert now["drawn"] and after["drawn"] and now["width"] > 0 and len(now["png"]) > 1000
    changing_now = [m for m in now["marks"] if m["kind"] == "changes"]
    changing_after = [m for m in after["marks"] if m["kind"] == "changes"]
    assert len(changing_now) == len(changing_after) == 2
    assert {m["text"] for m in changing_now} == {"120"} and {m["text"] for m in changing_after} == {"150"}
    assert all(0 <= m["x"] <= 1 and 0 <= m["y"] <= 1 and m["w"] > 0 for m in now["marks"])
    assert not any(m["kind"] == "changes" and m["label"].startswith("Headcount") for m in now["marks"])  # the decoy is only a question


@drawn
def test_pages_with_changes_are_listed(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    change_source(root, "C2", 150)
    listing = svc.review_pages(pid, "report.docx")
    assert listing["drawn"] and listing["pages"][0]["marks"]["changes"] == 2
