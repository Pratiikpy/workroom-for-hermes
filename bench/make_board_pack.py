import sys
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

INK, ACCENT, ACCENT2, MUTED, BG, CARD, WARN = "1F2937", "2563EB", "10B981", "6B7280", "F8FAFC", "FFFFFF", "EF4444"
rgb = lambda h: RGBColor.from_string(h)
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
blank = prs.slide_layouts[6]


def bg(slide):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = rgb(BG)


def text(slide, x, y, w, h, s, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = s
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, "Calibri"
    r.font.color.rgb = rgb(color)
    return tb


def tile(slide, x, y, w, h, label, value, delta, good=True):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    card.adjustments[0] = 0.06
    card.fill.solid()
    card.fill.fore_color.rgb = rgb(CARD)
    card.line.color.rgb = rgb("E5E7EB")
    card.shadow.inherit = False
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(0.08), Inches(h))
    bar.fill.solid()
    bar.fill.fore_color.rgb = rgb(ACCENT if good else WARN)
    bar.line.fill.background()
    text(slide, x + 0.3, y + 0.2, w - 0.5, 0.3, label.upper(), 11, True, MUTED)
    text(slide, x + 0.3, y + 0.55, w - 0.5, 0.8, value, 34, True, INK)
    text(slide, x + 0.3, y + 1.45, w - 0.5, 0.3, delta, 12, False, ACCENT2 if good else WARN)


# slide 1
s = prs.slides.add_slide(blank)
bg(s)
text(s, 0.7, 0.55, 10, 0.4, "FERN & FLAME  |  Q3 BOARD PACK", 12, True, ACCENT)
text(s, 0.7, 0.95, 11.5, 0.9, "Revenue grew 16.7% as the second shop opened", 32, True, INK)
text(s, 0.7, 1.85, 11.5, 0.4, "Prepared for the board. Every figure on this page is tied to its source cell.", 14, False, MUTED)
for i, (l, v, d, g) in enumerate([("Revenue", "$175.0M", "+16.7% vs Q2", True), ("Gross margin", "30.0%", "-10 pts vs Q1", False),
                                  ("Headcount", "120", "+8 vs Q2", True), ("Cash", "$42.3M", "+$3.1M vs Q2", True)]):
    tile(s, 0.7 + i * 3.05, 2.9, 2.85, 1.95, l, v, d, g)
text(s, 0.7, 6.7, 11, 0.3, "Source: Q3-results.xlsx (Results!C2, C4). Draft for review.", 10, False, MUTED)

# slide 2
s = prs.slides.add_slide(blank)
bg(s)
text(s, 0.7, 0.5, 11.5, 0.7, "Revenue is up, costs are rising slower", 28, True, INK)
cd = CategoryChartData()
cd.categories = ["Q1", "Q2", "Q3", "Q4 (fcst)"]
cd.add_series("Revenue ($M)", (130, 175, 190, 205))
cd.add_series("Costs ($M)", (60, 90, 95, 110))
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.5), Inches(7.6), Inches(5.0), cd)
ch = gf.chart
ch.has_legend = True
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.legend.include_in_layout = False
ch.legend.font.size = Pt(12)
pl = ch.plots[0]
pl.gap_width = 60
pl.has_data_labels = True
pl.data_labels.font.size = Pt(12)
pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
for ser, c in zip(pl.series, (ACCENT, "9CA3AF")):
    ser.format.fill.solid()
    ser.format.fill.fore_color.rgb = rgb(c)
ch.value_axis.has_major_gridlines = False
ch.value_axis.visible = False
ch.category_axis.tick_labels.font.size = Pt(12)
rows = [("Metric", "Q2", "Q3"), ("Revenue", "$175.0M", "$190.0M"), ("Costs", "$90.0M", "$95.0M"), ("Margin", "30.0%", "33.0%"), ("Headcount", "112", "120")]
tbl = s.shapes.add_table(len(rows), 3, Inches(8.7), Inches(1.7), Inches(4.0), Inches(2.6)).table
for r, row in enumerate(rows):
    for c, v in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = v
        p = cell.text_frame.paragraphs[0]
        p.runs[0].font.size = Pt(13)
        p.runs[0].font.name = "Calibri"
        p.runs[0].font.bold = r == 0
        p.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.RIGHT
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(ACCENT if r == 0 else CARD)
        p.runs[0].font.color.rgb = rgb(CARD if r == 0 else INK)

# slide 3
s = prs.slides.add_slide(blank)
bg(s)
text(s, 0.7, 0.5, 11.5, 0.7, "Margin recovered to 33% in Q3", 28, True, INK)
cd = CategoryChartData()
cd.categories = ["Q1", "Q2", "Q3", "Q4 (fcst)"]
cd.add_series("Gross margin (%)", (40, 30, 33, 35))
gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.7), Inches(1.5), Inches(8.0), Inches(5.0), cd)
ch = gf.chart
ch.has_legend = False
pl = ch.plots[0]
pl.has_data_labels = True
pl.data_labels.font.size = Pt(12)
pl.data_labels.position = XL_LABEL_POSITION.ABOVE
ser = pl.series[0]
ser.format.line.color.rgb = rgb(ACCENT)
ser.format.line.width = Pt(3)
ser.smooth = False
ch.value_axis.has_major_gridlines = False
ch.value_axis.visible = False
call = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.2), Inches(2.0), Inches(3.5), Inches(2.4))
call.fill.solid()
call.fill.fore_color.rgb = rgb(CARD)
call.line.color.rgb = rgb(ACCENT)
text(s, 9.45, 2.25, 3.0, 0.3, "WHAT CHANGED", 11, True, ACCENT)
text(s, 9.45, 2.65, 3.0, 1.6, "Opening costs fell back to plan and the new shop reached target traffic in week six.", 14, False, INK)

prs.save(sys.argv[1])  # usage: python make_board_pack.py <output.pptx>
print("saved python-pptx")
