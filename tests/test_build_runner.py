"""Contract C5: builders run in a subprocess, refuse bad input without a partial file, and produce files that open."""
import io

import pytest
from docx import Document
from pptx import Presentation

from workroom.workroom_core.build import runner
from workroom.workroom_core.build.runner import BuildError, build_file

PPTX = {"version": 1, "kind": "pptx", "path": "a.pptx", "facts": {}, "slides": [
    {"title": "Q2 results", "blocks": [
        {"type": "text", "text": "Revenue was $175 and margin 30.0%"},
        {"type": "bullets", "items": ["first point", "second point"]},
        {"type": "table", "header": ["Metric", "Q2"], "rows": [["Revenue", "$175"], ["Margin", "30.0%"]]},
    ]},
    {"title": "Chart", "blocks": [{"type": "chart", "kind": "bar", "title": "Revenue", "categories": ["Q1", "Q2"], "series": [{"name": "Revenue", "facts": ["a", "b"], "values": [130.0, 175.0]}]}]},
]}
DOCX = {"version": 1, "kind": "docx", "path": "a.docx", "facts": {}, "blocks": [
    {"type": "heading", "level": 1, "text": "Quarterly review"},
    {"type": "paragraph", "text": "Revenue was $175."},
    {"type": "bullets", "items": ["one", "two"]},
    {"type": "table", "header": ["Metric", "Q2"], "rows": [["Revenue", "$175"]]},
]}


def test_a_pptx_is_built_with_native_text_table_and_chart() -> None:
    prs = Presentation(io.BytesIO(build_file(PPTX)))
    assert len(prs.slides) == 2
    first = prs.slides[0]
    assert any(s.has_text_frame and "Revenue was $175" in s.text_frame.text for s in first.shapes)
    assert any(s.has_table for s in first.shapes)
    assert any(s.has_chart for s in prs.slides[1].shapes)
    chart = next(s.chart for s in prs.slides[1].shapes if s.has_chart)
    assert list(chart.plots[0].series[0].values) == [130.0, 175.0]


def test_a_docx_is_built_with_headings_bullets_and_a_table() -> None:
    doc = Document(io.BytesIO(build_file(DOCX)))
    texts = [p.text for p in doc.paragraphs]
    assert "Quarterly review" in texts and "Revenue was $175." in texts and "one" in texts
    assert doc.tables[0].cell(1, 1).text == "$175"


def test_content_that_does_not_fit_a_slide_is_refused_not_clipped() -> None:
    big = {**PPTX, "slides": [{"title": "t", "blocks": [{"type": "bullets", "items": ["x"] * 14}]}]}
    with pytest.raises(BuildError) as e:
        build_file(big)
    assert e.value.code == "overflow"


def test_a_crashing_builder_is_reported_and_leaves_nothing() -> None:
    with pytest.raises(BuildError) as e:
        build_file({"kind": "pptx", "slides": "not a list"})
    assert e.value.code == "build_failed"


def test_a_slow_builder_is_stopped_at_the_time_limit(monkeypatch, tmp_path) -> None:
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(30)")
    monkeypatch.setattr(runner, "WORKER", slow)
    with pytest.raises(BuildError) as e:
        build_file(PPTX, timeout=1.0)
    assert e.value.code == "timeout"


def test_the_builder_process_gets_no_secrets_from_the_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WORKROOM_TEST_SECRET", "hunter2")
    probe = tmp_path / "probe.py"
    probe.write_text("import os, json, sys\nprint(json.dumps({'ok': False, 'code': 'probe', 'error': os.environ.get('WORKROOM_TEST_SECRET', 'absent')}))")
    monkeypatch.setattr(runner, "WORKER", probe)
    with pytest.raises(BuildError) as e:
        build_file(PPTX)
    assert str(e.value) == "absent"


def test_kpi_cards_and_a_theme_are_built() -> None:
    spec = {"version": 1, "kind": "pptx", "path": "a.pptx", "facts": {}, "theme": {"accent": "7C3AED", "font": "Arial"}, "slides": [
        {"title": "KPIs", "blocks": [{"type": "kpis", "items": [{"label": "Revenue", "value": "$175", "note": "up 8%"}, {"label": "Margin", "value": "30.0%"}]}]}]}
    prs = Presentation(io.BytesIO(build_file(spec)))
    texts = [s.text_frame.text for s in prs.slides[0].shapes if s.has_text_frame]
    assert "$175" in texts and "30.0%" in texts and "up 8%" in texts
    value = next(s for s in prs.slides[0].shapes if s.has_text_frame and s.text_frame.text == "$175")
    run = value.text_frame.paragraphs[0].runs[0]
    assert str(run.font.color.rgb) == "7C3AED" and run.font.name == "Arial"


def test_a_chart_shrinks_to_the_room_left_under_other_blocks_instead_of_being_refused() -> None:
    spec = {"version": 1, "kind": "pptx", "path": "a.pptx", "facts": {}, "slides": [{"title": "t", "blocks": [
        {"type": "kpis", "items": [{"label": "Revenue", "value": "$1"}]},
        {"type": "chart", "kind": "bar", "categories": ["a", "b"], "series": [{"name": "s", "facts": ["x", "y"], "values": [1.0, 2.0]}]}]}]}
    prs = Presentation(io.BytesIO(build_file(spec)))
    chart = next(s for s in prs.slides[0].shapes if s.has_chart)
    assert chart.top + chart.height <= prs.slide_height, "the chart stays on the slide"
    assert chart.height / 914400 >= 2.4
