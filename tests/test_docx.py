import io
from pathlib import Path

import pytest

from workroom.tests.test_flagship_headless import change_source, make_workbook
from workroom.workroom_core.ooxml.docx import Doc
from workroom.workroom_core.ooxml.package import open_package, raw_unchanged
from workroom.workroom_core.ooxml.runs import EditError
from workroom.workroom_core.service import Service


def make_docx() -> bytes:
    from docx import Document

    d = Document()
    d.add_heading("Q2 results", level=1)
    p = d.add_paragraph("Revenue in Q2 was ")
    r = p.add_run("120")
    r.bold = True
    p.add_run(" and margin was 25%.")
    d.add_paragraph("Headcount reached 120 people.")
    t = d.add_table(rows=2, cols=3)
    for c, v in enumerate(["Metric", "Q1", "Q2"]):
        t.cell(0, c).text = v
    for c, v in enumerate(["Revenue", "100", "120"]):
        t.cell(1, c).text = v
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def texts(data: bytes) -> list[str]:
    from docx import Document

    d = Document(io.BytesIO(data))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            out.extend(c.text for c in row.cells)
    return out


def test_mentions_carry_their_headings_and_table_headers() -> None:
    doc = Doc(make_docx())
    ms = list(doc.mentions())
    revenue = next(m for m in ms if m.number.raw == "120" and "Revenue in Q2" in m.context[0])
    assert "Q2 results" in revenue.context
    cell = next(m for m in ms if m.cell == (1, 2))
    assert cell.number.raw == "120" and "Revenue" in cell.context and "Q2" in cell.context


def test_editing_one_number_changes_only_that_number_and_keeps_formatting() -> None:
    data = make_docx()
    doc = Doc(data)
    target = next(m for m in doc.mentions() if m.number.raw == "120" and "Revenue in Q2" in m.context[0])
    doc.edit_mention(target, "150")
    out, report = doc.serialize()
    assert report.parts_changed == ("word/document.xml",)
    t = texts(out)
    assert "Revenue in Q2 was 150 and margin was 25%." in t
    assert "Headcount reached 120 people." in t
    from docx import Document

    run = next(r for r in Document(io.BytesIO(out)).paragraphs[1].runs if r.text == "150")
    assert run.bold is True
    before, after = open_package(data), open_package(out)
    others = [n for n in before.names() if n != "word/document.xml"]
    assert raw_unchanged(before, after, others) == others


def test_a_table_cell_can_be_edited() -> None:
    doc = Doc(make_docx())
    cell = next(m for m in doc.mentions() if m.cell == (1, 2))
    doc.edit_mention(cell, "175")
    assert "175" in texts(doc.serialize()[0])


def test_deleted_tracked_text_is_not_matched_and_revisions_survive() -> None:
    data = make_docx()
    pkg = open_package(data)
    xml = pkg.read("word/document.xml").decode("utf-8")
    inject = ('<w:del w:id="9" w:author="A" w:date="2026-01-01T00:00:00Z"><w:r><w:delText>999</w:delText></w:r></w:del>'
              '<w:r><w:t xml:space="preserve"> tail 77</w:t></w:r>')
    xml = xml.replace("Headcount reached 120 people.</w:t></w:r>", "Headcount reached 120 people.</w:t></w:r>" + inject, 1)
    from workroom.workroom_core.ooxml.package import rewrite

    doc = Doc(rewrite(pkg, {"word/document.xml": xml.encode("utf-8")}))
    raws = [m.number.raw for m in doc.mentions()]
    assert "999" not in raws and "77" in raws
    m77 = next(m for m in doc.mentions() if m.number.raw == "77")
    doc.edit_mention(m77, "88")
    out = doc.serialize()[0]
    assert b"w:del" in open_package(out).read("word/document.xml") and b"999" in open_package(out).read("word/document.xml")


def test_stale_mention_is_refused() -> None:
    doc = Doc(make_docx())
    target = next(m for m in doc.mentions() if m.number.raw == "25%")
    doc.edit_mention(target, "30%")
    with pytest.raises(EditError):
        doc.edit_mention(target, "35%")  # the paragraph no longer holds 25% where it was found


def test_not_a_word_document_is_refused() -> None:
    from workroom.tests.test_flagship_headless import make_deck

    with pytest.raises(EditError):
        Doc(make_deck())


def test_no_edit_serialises_to_identical_bytes() -> None:
    data = make_docx()
    doc = Doc(data)
    list(doc.mentions())
    assert doc.serialize()[0] == data


def test_a_word_report_follows_a_workbook_through_the_service(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "report.docx").write_bytes(make_docx())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    found = svc.discover(pid)
    assert found["accepted"] >= 2
    change_source(root, "C2", 150)
    change_source(root, "C4", 0.30)
    staged = svc.stage(pid)
    assert staged["state"] == "awaiting_approval"
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    t = texts((root / "report.docx").read_bytes())
    assert "Revenue in Q2 was 150 and margin was 30%." in t
    assert "Headcount reached 120 people." in t
    assert svc.plan(pid)["changes"] == []
