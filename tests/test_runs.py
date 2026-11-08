import pytest
from lxml import etree

from workroom.workroom_core.ooxml.runs import DRAWING, WORD, EditError, find_all, paragraph_text, replace_once

A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def a_par(*runs: str) -> etree._Element:
    body = "".join(f"<a:r>{rp}<a:t>{t}</a:t></a:r>" for rp, t in runs)
    return etree.fromstring(f"<a:p {A}>{body}</a:p>")


def texts(p: etree._Element) -> list[str]:
    return [t.text for t in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")]


def test_single_run_replace_keeps_surroundings() -> None:
    p = a_par(('<a:rPr b="1"/>', "Revenue grew 12% this year"))
    r = replace_once(p, "12%", "15%", DRAWING)
    assert texts(p) == ["Revenue grew 15% this year"]
    assert r.formats_merged is False
    assert p.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}rPr").get("b") == "1"


def test_match_split_across_runs_keeps_first_run_format() -> None:
    p = a_par(('<a:rPr b="1"/>', "Revenue grew 1"), ("<a:rPr i=\"1\"/>", "2% this year"))
    r = replace_once(p, "12%", "15%", DRAWING)
    assert "".join(texts(p)) == "Revenue grew 15% this year"
    assert r.formats_merged is True
    assert len(texts(p)) == 2  # the second run keeps its tail


def test_emptied_run_is_removed() -> None:
    p = a_par(("", "Total "), ("", "1,234"))
    replace_once(p, "Total 1,234", "Total 1,300", DRAWING)
    assert "".join(texts(p)) == "Total 1,300"


def test_ambiguous_match_is_refused_unless_chosen() -> None:
    p = a_par(("", "12% and then 12% again"))
    with pytest.raises(EditError):
        replace_once(p, "12%", "15%", DRAWING)
    replace_once(p, "12%", "15%", DRAWING, occurrence=1)
    assert texts(p) == ["12% and then 15% again"]


def test_missing_text_is_refused() -> None:
    with pytest.raises(EditError):
        replace_once(a_par(("", "abc")), "zzz", "y", DRAWING)


def test_empty_search_is_refused() -> None:
    with pytest.raises(EditError):
        replace_once(a_par(("", "abc")), "", "y", DRAWING)


def test_match_never_spans_a_line_break() -> None:
    p = etree.fromstring(f"<a:p {A}><a:r><a:t>Total 1</a:t></a:r><a:br/><a:r><a:t>234</a:t></a:r></a:p>")
    assert find_all(p, "1234", DRAWING) == []


def test_word_deleted_text_is_not_matched() -> None:
    p = etree.fromstring(
        f"<w:p {W}><w:r><w:t>Sales </w:t></w:r><w:del><w:r><w:delText>12%</w:delText></w:r></w:del><w:r><w:t>15%</w:t></w:r></w:p>"
    )
    assert paragraph_text(p, WORD) == "Sales 15%"
    assert find_all(p, "12%", WORD) == []


def test_word_replacement_sets_space_preserve_when_needed() -> None:
    p = etree.fromstring(f"<w:p {W}><w:r><w:t>A 12%</w:t></w:r></w:p>")
    replace_once(p, "12%", " ", WORD)
    t = p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
    assert t.text == "A  "
    assert t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"


def test_word_bookmark_between_runs_does_not_split_a_match() -> None:
    p = etree.fromstring(
        f"<w:p {W}><w:r><w:t>Rev 1</w:t></w:r><w:bookmarkStart w:id=\"1\" w:name=\"b\"/><w:r><w:t>2%</w:t></w:r></w:p>"
    )
    replace_once(p, "12%", "15%", WORD)
    assert paragraph_text(p, WORD) == "Rev 15%"
