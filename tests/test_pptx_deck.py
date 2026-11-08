import io

import pytest

from workroom.workroom_core.ooxml.package import compare, open_package, raw_unchanged
from workroom.workroom_core.ooxml.pptx import Deck
from workroom.workroom_core.ooxml.runs import EditError


def build_deck() -> tuple[bytes, dict[str, int]]:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Revenue grew 12%"
    target = s.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1))
    target.name = "Target"
    target.text_frame.text = "Total 1,234"
    decoy = s.shapes.add_textbox(Inches(1), Inches(3), Inches(4), Inches(1))
    decoy.name = "Decoy"
    decoy.text_frame.text = "Total 1,234"
    cd = CategoryChartData()
    cd.categories = ["Q1", "Q2", "Q3"]
    cd.add_series("Revenue", (10.0, 20.0, 30.0))
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(4), Inches(4), Inches(3), cd)
    gf.name = "Chart"
    s.notes_slide.notes_text_frame.text = "Revenue grew 12% year on year"
    buf = io.BytesIO()
    prs.save(buf)
    ids = {sh.name: sh.shape_id for sh in s.shapes}
    return buf.getvalue(), ids


def test_text_edit_changes_only_the_named_shape() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    deck.edit_text(1, ids["Target"], "1,234", "1,300")
    out, report = deck.serialize()
    assert report.parts_changed == ("ppt/slides/slide1.xml",)
    from pptx import Presentation

    prs = Presentation(io.BytesIO(out))
    texts = {sh.name: sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame}
    assert texts["Target"] == "Total 1,300"
    assert texts["Decoy"] == "Total 1,234"
    before, after = open_package(data), open_package(out)
    others = [n for n in before.names() if n != "ppt/slides/slide1.xml"]
    assert raw_unchanged(before, after, others) == others


def test_title_edit_and_ambiguity() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    title_id = ids["Title 1"]
    deck.edit_text(1, title_id, "12%", "15%")
    with pytest.raises(EditError):
        deck.edit_text(1, title_id, "e", "E")  # "e" occurs several times in the title


def test_notes_edit() -> None:
    data, _ = build_deck()
    deck = Deck(data)
    deck.edit_notes(1, "12%", "15%")
    out, report = deck.serialize()
    assert any("notesSlide" in p for p in report.parts_changed)
    from pptx import Presentation

    assert "15%" in Presentation(io.BytesIO(out)).slides[0].notes_slide.notes_text_frame.text


def test_chart_update_changes_cache_and_workbook_together() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    deck.set_chart_value(1, ids["Chart"], 0, "Q2", 25.0)
    out, report = deck.serialize()
    assert len(report.parts_changed) == 2  # chart xml + embedded workbook
    from openpyxl import load_workbook
    from pptx import Presentation

    prs = Presentation(io.BytesIO(out))
    chart = next(sh for sh in prs.slides[0].shapes if sh.has_chart).chart
    assert list(chart.plots[0].series[0].values) == [10.0, 25.0, 30.0]
    wb_blob = chart.part.chart_workbook.xlsx_part.blob
    assert load_workbook(io.BytesIO(wb_blob)).active["B3"].value == 25
    before, after = open_package(data), open_package(out)
    unchanged = [n for n in before.names() if n not in report.parts_changed]
    assert raw_unchanged(before, after, unchanged) == unchanged
    assert not compare(before, after).added


def test_chart_out_of_step_with_workbook_is_refused() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    deck.set_chart_value(1, ids["Chart"], 0, "Q2", 25.0)
    out, _ = deck.serialize()
    deck2 = Deck(out)
    # corrupt the cache so it disagrees with the workbook
    cpart = [p for p in deck2.pkg.names() if p.startswith("ppt/charts/chart")][0]
    root = deck2._root(cpart)
    ns = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    root.xpath(".//c:val//c:pt[@idx='0']/c:v", namespaces=ns)[0].text = "999"
    with pytest.raises(EditError):
        deck2.set_chart_value(1, ids["Chart"], 0, "Q1", 11.0)


def test_unknown_category_and_unknown_shape_are_refused() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    with pytest.raises(EditError):
        deck.set_chart_value(1, ids["Chart"], 0, "Q9", 1.0)
    with pytest.raises(EditError):
        deck.edit_text(1, 9999, "a", "b")
    with pytest.raises(EditError):
        deck.edit_text(5, ids["Target"], "a", "b")


def test_no_edit_serialises_to_identical_bytes() -> None:
    data, ids = build_deck()
    deck = Deck(data)
    list(deck.shapes(1))
    out, report = deck.serialize()
    assert out == data
    assert report.parts_changed == ()
