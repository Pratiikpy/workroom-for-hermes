import io
import zipfile

from workroom.workroom_core.ooxml.docx import Doc
from workroom.workroom_core.ooxml.package import open_package, raw_unchanged

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def build() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f"<w:document {NS}><w:body>{para('Revenue was 1,200 in Q1')}</w:body></w:document>")
        z.writestr("word/header1.xml", f"<w:hdr {NS}>{para('Revenue 1,200 Q1 summary')}</w:hdr>")
        z.writestr("word/footer1.xml", f"<w:ftr {NS}>{para('Page footer')}</w:ftr>")
        z.writestr("word/footnotes.xml", f"<w:footnotes {NS}><w:footnote>{para('Note: revenue 1,200 in Q1')}</w:footnote></w:footnotes>")
        z.writestr("word/comments.xml", f"<w:comments {NS}><w:comment>{para('Reviewer: 1,200 is wrong')}</w:comment></w:comments>")
    return buf.getvalue()


def test_header_and_footnote_numbers_are_found_and_edited_but_comments_are_not() -> None:
    data = build()
    doc = Doc(data)
    ms = [m for m in doc.mentions() if m.number.raw == "1,200"]
    assert {doc.slide_parts()[m.slide - 1] for m in ms} == {"word/document.xml", "word/header1.xml", "word/footnotes.xml"}
    for m in ms:
        doc.edit_mention(m, "1,500")
    out, report = doc.serialize()
    assert set(report.parts_changed) == {"word/document.xml", "word/header1.xml", "word/footnotes.xml"}
    after = open_package(out)
    assert b"1,200" not in after.read("word/header1.xml") and b"1,200" in after.read("word/comments.xml")
    before = open_package(data)
    assert raw_unchanged(before, after, ["word/footer1.xml", "word/comments.xml"]) == ["word/footer1.xml", "word/comments.xml"]


def test_corrupt_compressed_data_is_a_clean_refusal() -> None:
    import pytest

    from workroom.workroom_core.ooxml.package import PackageError

    data = bytearray(build())
    i = data.index(b"word/document.xml") + len(b"word/document.xml")
    for k in range(i, i + 12):
        data[k] ^= 0xFF
    with pytest.raises(PackageError):
        list(Doc(bytes(data)).mentions())
