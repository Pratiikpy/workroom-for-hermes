import io
import xml.etree.ElementTree as ET

from pptx import Presentation

from workroom.workroom_core.build.runner import build_scene_pptx
from workroom.workroom_core.scene.export import export_svg

SCENE = {"version": 1, "canvas": {"w": 1280, "h": 720}, "nodes": [
    {"id": "bg", "type": "rect", "x": 0, "y": 0, "w": 1280, "h": 720, "fill": "F8FAFC"},
    {"id": "card", "type": "rect", "x": 80, "y": 160, "w": 360, "h": 200, "fill": "FFFFFF", "stroke": "E5E7EB", "stroke_w": 2, "radius": 16},
    {"id": "dot", "type": "ellipse", "x": 100, "y": 180, "w": 40, "h": 40, "fill": "2563EB"},
    {"id": "rule", "type": "line", "x": 80, "y": 400, "w": 360, "h": 0, "stroke": "6B7280", "stroke_w": 2},
    {"id": "t1", "type": "text", "x": 80, "y": 60, "w": 800, "h": 60, "text": "Q2 revenue was $175", "size": 36, "color": "1F2937", "bold": True},
]}


def test_svg_is_well_formed_xml_with_one_element_per_node() -> None:
    root = ET.fromstring(export_svg(SCENE))
    assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 1280 720"
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    assert ids == ["bg", "card", "dot", "rule", "t1"]


def test_hostile_text_cannot_break_out_of_the_svg() -> None:
    hostile = "</text><script>alert(1)</script><a href=\"javascript:x\" onload=\"x()\">&\"'"
    evil = {**SCENE, "nodes": SCENE["nodes"] + [{"id": "x", "type": "text", "x": 0, "y": 0, "w": 100, "h": 20, "text": hostile, "size": 12}]}
    root = ET.fromstring(export_svg(evil))
    tags = {e.tag.split("}")[-1] for e in root.iter()}
    assert tags <= {"svg", "rect", "ellipse", "line", "text"}
    attrs = {k.split("}")[-1].lower() for e in root.iter() for k in e.attrib}
    assert not [a for a in attrs if a == "href" or a.startswith("on")]
    assert next(e for e in root.iter() if e.get("id") == "x").text == hostile, "the hostile string is carried as text, nothing more"


def test_pptx_export_uses_native_editable_shapes_named_after_nodes() -> None:
    prs = Presentation(io.BytesIO(build_scene_pptx(SCENE)))
    assert len(prs.slides) == 1
    shapes = {s.name: s for s in prs.slides[0].shapes}
    assert set(shapes) == {"bg", "card", "dot", "rule", "t1"}
    assert shapes["t1"].has_text_frame and shapes["t1"].text_frame.text == "Q2 revenue was $175"
    run = shapes["t1"].text_frame.paragraphs[0].runs[0]
    assert run.font.bold is True and round(run.font.size.pt) > 20
    scale = prs.slide_width / 1280
    assert abs(shapes["card"].left - 80 * scale) < 2 and abs(shapes["card"].width - 360 * scale) < 2


def test_html_export_is_script_free_and_carries_a_locked_down_csp() -> None:
    from html.parser import HTMLParser

    from workroom.workroom_core.scene.export import export_html

    tags, attrs = [], []

    class P(HTMLParser):
        def handle_starttag(self, tag, a):
            tags.append(tag)
            attrs.extend(k for k, _ in a)

    hostile = {**SCENE, "nodes": SCENE["nodes"] + [{"id": "x", "type": "text", "x": 0, "y": 0, "w": 100, "h": 20, "text": "<script>alert(1)</script>", "size": 12}]}
    html = export_html(hostile, title="<b>x</b>")
    P().feed(html)
    assert "script" not in tags and not [a for a in attrs if a.startswith("on") or a == "href"]
    assert "default-src 'none'" in html and "&lt;b&gt;x&lt;/b&gt;" in html
