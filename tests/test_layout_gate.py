"""The layout gate finds visible faults in a deck, and passes a clean one."""

import io

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from workroom.workroom_core.layout_gate import blocking, check_pptx, contrast


def deck(build) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    build(slide)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def box(slide, text, left=0.7, top=1.6, width=11.9, height=1.0, size=20, color="111827", name="Body", wrap=True):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tb.name = name
    tb.text_frame.word_wrap = wrap
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.name = "Calibri"
    r.font.color.rgb = RGBColor.from_string(color)
    return tb


def kinds(data: bytes) -> set[str]:
    return {f.kind for f in blocking(check_pptx(data))}


def test_a_clean_slide_passes() -> None:
    def build(s):
        box(s, "Quarterly results", top=0.5, height=0.9, size=30, name="Title")
        box(s, "Revenue rose 12% on stronger demand in the north.", top=1.6, height=0.8)
    assert blocking(check_pptx(deck(build))) == []


def test_text_too_long_for_its_box_is_an_overflow() -> None:
    def build(s):
        box(s, " ".join(["Revenue rose on stronger demand in every region we serve."] * 30), height=0.8)
    assert "overflow" in kinds(deck(build))


def test_a_long_figure_in_a_narrow_card_that_does_not_wrap_overflows() -> None:
    def build(s):
        box(s, "$12,345,678.9 million", left=1, width=2.0, height=0.8, size=40, name="KPI value", wrap=False)
    assert "overflow" in kinds(deck(build))


def test_tiny_text_is_blocked() -> None:
    def build(s):
        box(s, "Source: department workbook", size=7, height=0.5, name="Footnote")
    assert "small_text" in kinds(deck(build))


def test_a_shape_off_the_slide_is_blocked() -> None:
    def build(s):
        box(s, "Margin", left=12.5, width=2.0, height=0.5)
    assert "off_slide" in kinds(deck(build))


def test_pale_text_on_white_fails_contrast() -> None:
    def build(s):
        box(s, "Costs fell", color="D1D5DB", height=0.6)
    assert "contrast" in kinds(deck(build))
    assert round(contrast("000000", "FFFFFF"), 1) == 21.0


def test_dark_text_on_a_dark_card_fails_contrast() -> None:
    def build(s):
        card = s.shapes.add_shape(1, Inches(1), Inches(2), Inches(4), Inches(2))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor.from_string("1F2937")
        box(s, "Net margin", left=1.2, top=2.2, width=3.5, height=0.6, color="374151")
    assert "contrast" in kinds(deck(build))


def test_a_table_taller_than_the_slide_is_blocked() -> None:
    def build(s):
        gf = s.shapes.add_table(30, 3, Inches(0.7), Inches(1.6), Inches(11.9), Inches(0.4 * 30))
        gf.name = "Big table"
    assert kinds(deck(build)) & {"table_height", "off_slide"}


def test_overlapping_text_boxes_are_warned() -> None:
    def build(s):
        box(s, "First", top=2.0, height=1.0, name="A")
        box(s, "Second", top=2.3, height=1.0, name="B")
    found = check_pptx(deck(build))
    assert any(f.kind == "overlap" and f.severity == "warn" for f in found)


def test_decks_built_by_workroom_from_a_spec_pass_the_gate() -> None:
    from workroom.workroom_core.build.worker import _pptx as build

    spec = {"kind": "pptx", "path": "board.pptx", "slides": [
        {"title": "Q3 results", "blocks": [{"type": "text", "text": "Revenue rose 12% on stronger demand."},
                                           {"type": "kpis", "items": [{"label": "Revenue", "value": "$4,210m"}, {"label": "Margin", "value": "18.2%"}]}]},
        {"title": "Detail", "blocks": [{"type": "bullets", "items": ["North grew fastest", "Costs fell 3%", "Cash up $120m"]},
                                       {"type": "table", "header": ["Region", "Revenue"], "rows": [["North", "1,200"], ["South", "980"]]}]}]}
    data = build(spec)
    assert blocking(check_pptx(data)) == []


def test_a_box_that_grows_to_fit_and_then_covers_the_next_box_is_warned() -> None:
    def build(s):
        box(s, " ".join(["Revenue rose on stronger demand."] * 8), top=1.6, height=0.6, name="Grows")
        box(s, "Next paragraph", top=2.4, height=0.6, name="Below")
    found = check_pptx(deck(build))
    assert any(f.kind == "overlap" and "Grows" in f.shape for f in found)





def test_a_built_deck_goes_through_the_gate_and_its_faults_reach_the_agent(tmp_path, monkeypatch) -> None:
    from workroom.tests.test_create_flow import SPEC, _svc
    from workroom.workroom_core import layout_gate

    svc, pid, root = _svc(tmp_path)
    kpis = {"type": "kpis", "items": [{"label": "Revenue this quarter", "value": "{rev:$#,##0.00}", "note": "against plan"} for _ in range(4)]}
    spec = {**SPEC, "path": "kpis.pptx", "slides": [{"title": "Q2 at a glance", "blocks": [kpis]}]}
    clean = svc.create_from_spec(pid, spec)
    assert clean["state"] == "awaiting_approval" and not [n for n in clean["held"] if str(n).startswith("layout:")]  # four cards: no false alarm
    monkeypatch.setattr(layout_gate, "check_pptx", lambda data: [layout_gate.Finding(1, "Block 1 value 1", "overflow", "block", "the value does not fit its card")])
    refused = svc.create_from_spec(pid, {**spec, "path": "kpis2.pptx"})
    assert refused["state"] == "refused" and refused["errors"][0]["code"] == "layout" and "does not fit" in refused["errors"][0]["message"]
