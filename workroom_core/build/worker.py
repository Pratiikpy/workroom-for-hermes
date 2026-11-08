"""The builder. Runs in its own process: reads one JSON request on stdin, writes one JSON reply on stdout.

It lays out plain text that the parent has already resolved; it never sees fact ids, formats, paths of the project or the network.
Only python-pptx and python-docx are imported here, never the rest of Workroom.
"""

from __future__ import annotations

import base64
import io
import json
import sys

INK, ACCENT, MUTED, RULE = "1F2937", "2563EB", "6B7280", "E5E7EB"
SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN = 0.7
BODY_TOP, BODY_BOTTOM = 1.55, 7.0


class LayoutError(Exception):
    pass


def _pptx(spec: dict) -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Inches, Pt

    def rgb(h: str) -> RGBColor:
        return RGBColor.from_string(h)

    theme = spec.get("theme", {})
    ink, accent, muted = theme.get("ink", INK), theme.get("accent", ACCENT), theme.get("muted", MUTED)
    font = theme.get("font", "Calibri")

    def style(run, size, color, bold=False):
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, font
        run.font.color.rgb = rgb(color)

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    blank = prs.slide_layouts[6]
    width = SLIDE_W - 2 * MARGIN
    for si, slide_spec in enumerate(spec["slides"]):
        slide = prs.slides.add_slide(blank)
        if slide_spec.get("title"):
            tb = slide.shapes.add_textbox(Inches(MARGIN), Inches(0.5), Inches(width), Inches(0.9))
            tb.name = "Title"
            tf = tb.text_frame
            tf.word_wrap = True
            run = tf.paragraphs[0].add_run()
            run.text = slide_spec["title"]
            style(run, 30, ink, True)
            bar = slide.shapes.add_shape(1, Inches(MARGIN + 0.08), Inches(1.28), Inches(0.9), Inches(0.06))
            bar.name = "Title rule"
            bar.fill.solid()
            bar.fill.fore_color.rgb = rgb(accent)
            bar.line.fill.background()
        y = BODY_TOP
        for bi, b in enumerate(slide_spec.get("blocks", [])):
            kind = b["type"]
            name = f"Block {bi + 1}"
            if kind == "text":
                lines = max(1, -(-len(b["text"]) // 95))
                h = 0.45 * lines + 0.1
                tb = slide.shapes.add_textbox(Inches(MARGIN), Inches(y), Inches(width), Inches(h))
                tb.name = name
                tb.text_frame.word_wrap = True
                r = tb.text_frame.paragraphs[0].add_run()
                r.text = b["text"]
                style(r, 20, ink)
            elif kind == "bullets":
                h = 0.5 * len(b["items"]) + 0.1
                tb = slide.shapes.add_textbox(Inches(MARGIN), Inches(y), Inches(width), Inches(h))
                tb.name = name
                tf = tb.text_frame
                tf.word_wrap = True
                for ii, item in enumerate(b["items"]):
                    para = tf.paragraphs[0] if ii == 0 else tf.add_paragraph()
                    r = para.add_run()
                    r.text = item
                    style(r, 20, ink)
                    para.space_after = Pt(6)
            elif kind == "kpis":
                items = b["items"]
                h = 1.9
                gap = 0.25
                card_w = (width - gap * (len(items) - 1)) / len(items)
                for ci, item in enumerate(items):
                    x = MARGIN + ci * (card_w + gap)
                    card = slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(card_w), Inches(h))
                    card.name = f"{name} card {ci + 1}"
                    card.fill.solid()
                    card.fill.fore_color.rgb = rgb("F3F4F6")
                    card.line.fill.background()
                    for part, top, size, color, bold, txt in (("label", 0.15, 14, muted, False, item["label"]), ("value", 0.55, 40, accent, True, item["value"]),
                                                              ("note", 1.4, 12, muted, False, item.get("note", ""))):
                        if not txt:
                            continue
                        box = slide.shapes.add_textbox(Inches(x + 0.15), Inches(y + top), Inches(card_w - 0.3), Inches(0.5 if part != "value" else 0.8))
                        box.name = f"{name} {part} {ci + 1}"
                        box.text_frame.word_wrap = True
                        style(box.text_frame.paragraphs[0].add_run(), size, color, bold)
                        box.text_frame.paragraphs[0].runs[0].text = txt
            elif kind == "table":
                rows = [b["header"]] + b["rows"]
                cols = max(len(r) for r in rows)
                h = 0.5 * len(rows)
                gf = slide.shapes.add_table(len(rows), cols, Inches(MARGIN), Inches(y), Inches(width), Inches(h))
                gf.name = name
                for ri, row in enumerate(rows):
                    for ci in range(cols):
                        cell = gf.table.cell(ri, ci)
                        cell.text = row[ci] if ci < len(row) else ""
                        for para in cell.text_frame.paragraphs:
                            for r in para.runs:
                                r.font.size = Pt(16)
                                r.font.bold = ri == 0
            elif kind == "chart":
                h = min(3.6, BODY_BOTTOM - y)  # shrink to the room left on the slide; refuse only when it would be unreadably small
                if h < 2.4:
                    raise LayoutError(f"slide {si + 1} has no room left for a chart; move it to its own slide")
                data = CategoryChartData()
                data.categories = b["categories"]
                for s in b["series"]:
                    data.add_series(s["name"], s["values"])
                ctype = XL_CHART_TYPE.COLUMN_CLUSTERED if b["kind"] == "bar" else XL_CHART_TYPE.LINE_MARKERS
                gf = slide.shapes.add_chart(ctype, Inches(MARGIN), Inches(y), Inches(width), Inches(h), data)
                gf.name = name
                chart = gf.chart
                chart.plots[0].vary_by_categories = False
                for ser in chart.plots[0].series:
                    ser.format.fill.solid()
                    ser.format.fill.fore_color.rgb = rgb(accent)
                chart.value_axis.major_gridlines.format.line.color.rgb = rgb(RULE)
                chart.has_legend = len(b["series"]) > 1
                if chart.has_legend:
                    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
                    chart.legend.include_in_layout = False
                if b.get("title"):
                    chart.has_title = True
                    chart.chart_title.text_frame.text = b["title"]
            y += h + 0.2
            if y > BODY_BOTTOM + 0.2:
                raise LayoutError(f"slide {si + 1} has more content than fits; split it across slides")
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _scene_pptx(scene: dict) -> bytes:
    """One slide of native, editable shapes (named after their node ids) from a validated scene."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Pt

    def rgb(h: str) -> RGBColor:
        return RGBColor.from_string(h.upper())

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(SLIDE_W * 914400)), Emu(int(SLIDE_H * 914400))
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    cw, ch = scene["canvas"]["w"], scene["canvas"]["h"]
    k = min(prs.slide_width / cw, prs.slide_height / ch)
    e = lambda v: Emu(int(round(v * k)))  # noqa: E731
    for n in scene["nodes"]:
        t = n["type"]
        if t == "line":
            shp = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, e(n["x"]), e(n["y"]), e(n["x"] + n["w"]), e(n["y"] + n["h"]))
            if "stroke" in n:
                shp.line.color.rgb = rgb(n["stroke"])
            shp.line.width = Pt(n.get("stroke_w", 1) * k / 12700)
        elif t in ("rect", "ellipse"):
            kind = MSO_SHAPE.ROUNDED_RECTANGLE if t == "rect" and n.get("radius") else MSO_SHAPE.RECTANGLE if t == "rect" else MSO_SHAPE.OVAL
            shp = slide.shapes.add_shape(kind, e(n["x"]), e(n["y"]), e(n["w"]), e(n["h"]))
            if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
                shp.adjustments[0] = min(0.5, n["radius"] / max(1.0, min(n["w"], n["h"])))
            if "fill" in n:
                shp.fill.solid()
                shp.fill.fore_color.rgb = rgb(n["fill"])
            else:
                shp.fill.background()
            if "stroke" in n:
                shp.line.color.rgb = rgb(n["stroke"])
                shp.line.width = Pt(n.get("stroke_w", 1) * k / 12700)
            else:
                shp.line.fill.background()
        else:
            shp = slide.shapes.add_textbox(e(n["x"]), e(n["y"]), e(n["w"]), e(n["h"]))
            tf = shp.text_frame
            tf.word_wrap = True
            para = tf.paragraphs[0]
            para.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}[n.get("align", "left")]
            run = para.add_run()
            run.text = n.get("text", "")
            run.font.size = Pt(n.get("size", 24) * k / 12700)
            run.font.bold = bool(n.get("bold"))
            run.font.color.rgb = rgb(n.get("color", "1F2937"))
        shp.name = n["id"]
        if n.get("rotate"):
            shp.rotation = n["rotate"]
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _xlsx(spec: dict) -> bytes:
    """Workbooks are written with XlsxWriter (a dependency of python-pptx), never openpyxl: other plugins ship a package that provides the same import name."""
    import xlsxwriter

    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {"in_memory": True})
    head = wb.add_format({"bold": True})
    for sh in spec["sheets"]:
        ws = wb.add_worksheet(sh["name"])
        widths: dict[int, int] = {}
        for ri, row in enumerate(sh["rows"]):
            for ci, c in enumerate(row):
                if isinstance(c, dict) and "value" in c:
                    ws.write_number(ri, ci, c["value"], wb.add_format({"num_format": c["number_format"]}))
                    shown = len(f"{c['value']:,.2f}")
                elif isinstance(c, dict):
                    ws.write_formula(ri, ci, c["formula"])
                    shown = 12
                elif isinstance(c, (int, float)):
                    ws.write_number(ri, ci, c)
                    shown = len(str(c))
                else:
                    ws.write_string(ri, ci, c, head if ri == 0 else None)
                    shown = len(str(c))
                widths[ci] = max(widths.get(ci, 8), min(shown + 2, 60))
        for ci, w in widths.items():
            ws.set_column(ci, ci, w)
        ws.freeze_panes(1, 0)
    wb.close()
    return out.getvalue()


def _docx(spec: dict) -> bytes:
    from docx import Document

    doc = Document()
    for b in spec["blocks"]:
        kind = b["type"]
        if kind == "heading":
            doc.add_heading(b["text"], level=max(1, min(int(b.get("level", 1)), 4)))
        elif kind == "paragraph":
            doc.add_paragraph(b["text"])
        elif kind == "bullets":
            for item in b["items"]:
                doc.add_paragraph(item, style="List Bullet")
        elif kind == "table":
            rows = [b["header"]] + b["rows"]
            cols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(cols):
                    table.cell(ri, ci).text = row[ci] if ci < len(row) else ""
                    if ri == 0:
                        for r in table.cell(ri, ci).paragraphs[0].runs:
                            r.bold = True
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def main() -> int:
    try:
        req = json.loads(sys.stdin.read(8_000_000))
        spec = req["spec"]
        data = _pptx(spec) if spec["kind"] == "pptx" else _xlsx(spec) if spec["kind"] == "xlsx" else _scene_pptx(spec["scene"]) if spec["kind"] == "scene_pptx" else _docx(spec)
        reply = {"ok": True, "file": base64.b64encode(data).decode("ascii")}
    except LayoutError as exc:
        reply = {"ok": False, "code": "overflow", "error": str(exc)}
    except Exception as exc:  # the parent turns any failure into a refusal; nothing is half-built
        reply = {"ok": False, "code": "build_failed", "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(reply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
