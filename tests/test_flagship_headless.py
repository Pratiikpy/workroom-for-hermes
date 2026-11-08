"""The flagship flow without Hermes: workbook + deck -> discover -> source changes -> plan -> approve -> release."""

import io
from pathlib import Path

import pytest

from workroom.workroom_core.controller.approvals import sign
from workroom.workroom_core.controller.release import Controller, StaleRelease
from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell
from workroom.workroom_core.project import Project

KEY = b"k" * 32
OWNER = "desktop:owner"


def make_workbook() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2"])
    ws.append(["Revenue", 100, 120])
    ws.append(["Costs", 60, 90])
    ws.append(["Margin", 0.40, 0.25])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_deck() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Q2 results"
    a = s.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    a.name = "Revenue line"
    a.text_frame.text = "Revenue in Q2 was 120 and margin was 25%"
    b = s.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1))
    b.name = "Decoy"
    b.text_frame.text = "Headcount reached 120 people"
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def setup(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "deck.pptx").write_bytes(make_deck())
    return root, Project(root, tmp_path / "state"), Controller(root, tmp_path / "state", KEY, frozenset({OWNER}))


def deck_texts(path: Path) -> dict[str, str]:
    from pptx import Presentation

    prs = Presentation(str(path))
    return {sh.name: sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame}


def change_source(root: Path, ref: str, value: float) -> None:
    (root / "results.xlsx").write_bytes(patch_numeric_cell((root / "results.xlsx").read_bytes(), "Results", ref, value))


def test_discovery_links_labelled_numbers_and_leaves_the_decoy_for_a_human(tmp_path: Path) -> None:
    root, proj, _ = setup(tmp_path)
    before = (root / "deck.pptx").read_bytes()
    proj.discover()
    assert (root / "deck.pptx").read_bytes() == before  # discovery writes nothing to documents
    by_raw = {}
    for t in proj.ties():
        by_raw.setdefault((t.raw, t.deck), []).append(t)
    revenue = [t for t in proj.ties() if t.raw == "120" and t.shape_id != 0]
    states = {t.state for t in revenue}
    assert "accepted" in states and "confirm" in states  # revenue line accepted, decoy needs confirmation
    accepted = [t for t in proj.ties() if t.state == "accepted"]
    assert any(t.ref == "C2" for t in accepted)  # Revenue / Q2
    assert any(t.ref == "C4" for t in accepted)  # Margin / Q2 as a percentage


def test_refresh_changes_only_the_tied_numbers_and_never_the_decoy(tmp_path: Path) -> None:
    root, proj, ctl = setup(tmp_path)
    proj.discover()
    change_source(root, "C2", 150)
    change_source(root, "C4", 0.30)
    plan = proj.plan_refresh()
    assert {i.new_text for i in plan.impacts} == {"150", "30%"}
    assert plan.files.keys() == {"deck.pptx"}
    rid = ctl.stage(plan.files)
    ctl.mark_verified(rid)
    ctl.record_approval(rid, sign(KEY, rid, ctl.digest(rid), OWNER, "desktop", 10**12, "n1"), now=1.0)
    ctl.publish(rid, now=2.0)
    texts = deck_texts(root / "deck.pptx")
    assert texts["Revenue line"] == "Revenue in Q2 was 150 and margin was 30%"
    assert texts["Decoy"] == "Headcount reached 120 people"
    proj.commit_snapshot(plan)
    assert proj.plan_refresh().impacts == []  # baseline moved; nothing left to change


def test_a_human_edit_between_plan_and_publish_stops_the_release(tmp_path: Path) -> None:
    root, proj, ctl = setup(tmp_path)
    proj.discover()
    change_source(root, "C2", 150)
    plan = proj.plan_refresh()
    rid = ctl.stage(plan.files)
    ctl.mark_verified(rid)
    ctl.record_approval(rid, sign(KEY, rid, ctl.digest(rid), OWNER, "desktop", 10**12, "n1"), now=1.0)
    (root / "deck.pptx").write_bytes(make_deck() + b"")  # someone saved the deck again
    from workroom.workroom_core.ooxml.pptx import Deck

    d = Deck(make_deck())
    sid = next(i for i, n, t in d.shapes(1) if n == "Revenue line")
    d.edit_text(1, sid, "Revenue", "Sales")
    (root / "deck.pptx").write_bytes(d.serialize()[0])
    with pytest.raises(StaleRelease):
        ctl.publish(rid, now=2.0)
    assert "Sales in Q2 was 120" in deck_texts(root / "deck.pptx")["Revenue line"]


def test_a_hand_edited_number_is_held_not_overwritten(tmp_path: Path) -> None:
    root, proj, _ = setup(tmp_path)
    proj.discover()
    from workroom.workroom_core.ooxml.pptx import Deck

    d = Deck((root / "deck.pptx").read_bytes())
    sid = next(i for i, n, t in d.shapes(1) if n == "Revenue line")
    d.edit_text(1, sid, "25%", "about a quarter")  # a person rewrote the margin sentence
    (root / "deck.pptx").write_bytes(d.serialize()[0])
    change_source(root, "C4", 0.30)
    plan = proj.plan_refresh()
    assert plan.impacts == []
    assert any("held" in s for s in plan.skipped)
    assert "about a quarter" in deck_texts(root / "deck.pptx")["Revenue line"]


def test_finding_links_again_keeps_links_whose_source_has_moved(tmp_path: Path) -> None:
    root, proj, _ = setup(tmp_path)
    proj.discover()
    before = {(t.raw, t.ref, t.state, t.linked_value) for t in proj.ties()}
    change_source(root, "C2", 150)
    again = proj.discover()
    assert {(t.raw, t.ref, t.state, t.linked_value) for t in proj.ties()} == before
    assert again.kept == len(before)
    assert any(i.old_text == "120" and i.new_text == "150" for i in proj.plan_refresh().impacts)


def test_finding_links_again_keeps_what_the_owner_decided(tmp_path: Path) -> None:
    root, proj, _ = setup(tmp_path)
    proj.discover()
    ask = next(t for t in proj.ties() if t.state == "confirm")
    proj.confirm(ask.id)
    proj.discover()
    assert next(t for t in proj.ties() if t.id == ask.id).state == "confirmed"
    proj.skip(ask.id)
    proj.discover()
    assert next(t for t in proj.ties() if t.id == ask.id).state == "skipped"


def test_a_link_is_held_not_dropped_when_its_number_was_edited_by_hand(tmp_path: Path) -> None:
    from pptx import Presentation

    root, proj, _ = setup(tmp_path)
    proj.discover()
    linked = next(t for t in proj.ties() if t.state == "accepted" and t.raw == "120")
    prs = Presentation(str(root / "deck.pptx"))
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame and "120" in shape.text_frame.text and "Revenue" in shape.text_frame.text:
            for p in shape.text_frame.paragraphs:
                for r in p.runs:
                    r.text = r.text.replace("120", "999")
    prs.save(str(root / "deck.pptx"))
    proj.discover()
    held = next(t for t in proj.ties() if t.id == linked.id)
    assert held.state == "held"
    assert held.id not in [t.id for t in proj.ties(("accepted", "confirmed"))]
