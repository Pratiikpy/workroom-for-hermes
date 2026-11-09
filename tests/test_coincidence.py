"""A short number that equals some cell and nothing else is not a question for the owner."""
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
from xlsxwriter import Workbook

from workroom.workroom_core.match.engine import is_coincidence
from workroom.workroom_core.service import Service


def _project(tmp_path: Path) -> tuple[Service, str]:
    root = tmp_path / "proj"
    root.mkdir()
    with Workbook(str(root / "data.xlsx")) as wb:
        ws = wb.add_worksheet("Data")
        ws.write_row(0, 0, ["Metric", "Value"])
        ws.write_row(1, 0, ["Offices", 3])
        ws.write_row(2, 0, ["Employees", 431])
        ws.write_row(3, 0, ["Contractors", 431])
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Update"
    for i, line in enumerate(["We opened 3 new things this year.", "People on site: 431."]):
        slide.shapes.add_textbox(Inches(0.5), Inches(1.5 + i), Inches(9), Inches(0.8)).text_frame.text = line
    prs.save(str(root / "deck.pptx"))
    svc = Service(tmp_path / "state")
    return svc, svc.add_project(str(root))["project"]


def test_the_rule_needs_no_label_evidence_and_a_short_number() -> None:
    assert is_coincidence(0.0, "3") and is_coincidence(0.0, "52") and is_coincidence(0.0, "0.5")
    assert not is_coincidence(0.0, "431") and not is_coincidence(0.0, "1,234")
    assert not is_coincidence(0.4, "3"), "any label evidence makes a short number a real candidate"


def test_a_coincidental_candidate_is_offered_apart_from_the_questions(tmp_path: Path) -> None:
    svc, pid = _project(tmp_path)
    found = svc.discover(pid)
    asked = [t["text"] for t in found["need_confirmation"]]
    apart = [t["text"] for t in found["coincidences"]]
    assert "431" in asked and "3" not in asked
    assert "3" in apart and "431" not in apart
    flags = {t["text"]: t["coincidence"] for t in svc.ties(pid) if t["state"] == "confirm"}
    assert flags == {"3": True, "431": False}


def test_a_coincidental_candidate_can_still_be_linked_by_the_owner(tmp_path: Path) -> None:
    svc, pid = _project(tmp_path)
    svc.discover(pid)
    tie = next(t for t in svc.ties(pid) if t["text"] == "3")
    svc.confirm(pid, tie["id"])
    assert next(t for t in svc.ties(pid) if t["id"] == tie["id"])["state"] == "confirmed"
