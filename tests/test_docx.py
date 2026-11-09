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


def _with_second_body(data: bytes) -> bytes:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            blob = src.read(info.filename)
            if info.filename == "word/document.xml":
                extra = b'<w:body><w:p><w:r><w:t>Revenue in Q2 was 999</w:t></w:r></w:p></w:body>'
                blob = blob.replace(b"</w:document>", extra + b"</w:document>")
            dst.writestr(info, blob)
    return out.getvalue()


def test_a_document_with_a_second_body_element_is_refused_because_word_would_not_show_edits_to_it() -> None:
    from docx import Document

    broken = _with_second_body(make_docx())
    assert Document(io.BytesIO(broken)).paragraphs  # python-docx still opens it, which is why it is not enough to rely on it
    with pytest.raises(EditError, match="2 body elements"):
        Doc(broken)


def test_a_document_without_a_body_is_refused_too() -> None:
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(make_docx())) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            blob = src.read(info.filename)
            if info.filename == "word/document.xml":
                import re

                blob = re.sub(rb"<w:body>.*</w:body>", b"", blob, flags=re.S)
            dst.writestr(info, blob)
    with pytest.raises(EditError, match="0 body elements"):
        Doc(out.getvalue())


def test_the_section_number_that_opens_a_heading_is_not_a_figure_but_the_same_text_in_a_body_paragraph_is() -> None:
    from docx import Document

    d = Document()
    d.add_heading("4.1 Property, plant and equipment", level=2)
    d.add_paragraph("4.1 percent more equipment was bought than planned")
    buf = io.BytesIO()
    d.save(buf)
    raws = [(m.para, m.number.raw) for m in Doc(buf.getvalue()).mentions()]
    assert raws == [(1, "4.1")], raws


def test_a_formatted_heading_number_and_a_notes_column_are_not_figures() -> None:
    from docx import Document

    d = Document()
    d.add_paragraph("4.1 Property, plant and equipment")
    d.add_paragraph("4.2 Million people use the service")
    d.add_paragraph("6.5 percent of staff left")
    t = d.add_table(rows=3, cols=3)
    for c, v in enumerate(["Item", "Notes", "2021"]):
        t.cell(0, c).text = v
    for c, v in enumerate(["Property, plant and equipment", "4.1", "224,609"]):
        t.cell(1, c).text = v
    for c, v in enumerate(["Intangible assets", "4.2", "2,238,270"]):
        t.cell(2, c).text = v
    buf = io.BytesIO()
    d.save(buf)
    nums = [m.number for m in Doc(buf.getvalue()).mentions()]
    raws = [n.raw for n in nums]
    assert "4.1" not in raws and "6.5%" in " ".join(raws) + "%" or "6.5" in raws
    assert any(n.value == 4.2 and n.scale == 1e6 for n in nums), "a number that reads as an amount keeps its place even when the paragraph starts with it"
    assert "224,609" in raws and "2,238,270" in raws
    assert raws.count("4.2") == 0, "the notes column's 4.2 is a reference"
