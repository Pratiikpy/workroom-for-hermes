import shutil
from pathlib import Path

from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from workroom.workroom_core.project import Project


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "p"
    root.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q2", "Q3"])
    ws.append(["Revenue", 175, 190])
    ws.append(["Costs", 90, 95])
    wb.save(root / "results.xlsx")
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    t = slide.shapes.add_table(3, 3, Inches(1), Inches(1), Inches(6), Inches(2)).table
    for r, row in enumerate([("Metric", "Q2", "Q3"), ("Revenue", "175", "190"), ("Costs", "90", "95")]):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    prs.save(root / "deck.pptx")
    return Project(root, tmp_path / "state")


def test_rediscovering_an_unchanged_project_does_not_duplicate_table_ties(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    proj.discover()
    first = {(t.cell_rc, t.raw, t.ref) for t in proj.ties()}
    for _ in range(3):
        proj.discover()
    after = [(t.cell_rc, t.raw, t.ref) for t in proj.ties()]
    assert len(after) == len(first) and set(after) == first, "table cells were linked again on every scan"


def test_a_confirmed_table_tie_keeps_its_state_across_scans(tmp_path: Path) -> None:
    proj = _project(tmp_path)
    proj.discover()
    tie = next(t for t in proj.ties() if t.raw == "175")
    proj.db.execute("UPDATE ties SET state='confirmed' WHERE id=?", (tie.id,))
    proj.discover()
    same = [t for t in proj.ties() if t.raw == "175"]
    assert len(same) == 1 and same[0].id == tie.id and same[0].state == "confirmed"
