"""Usage: python anchor_survival.py <board-pack.pptx>. Experiment: do Workroom's ties survive the edits a person or another program really makes to a deck?

Baseline: the generated board pack plus a workbook whose values match every number on the slides.
Each mutation is applied to a fresh copy; then discovery runs again on the same project state.
We record: ties kept with the same id and state, ties re-created (new id, state lost), ties dropped, and WRONG links (a kept tie whose source cell is not the one for that number).
"""
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from openpyxl import Workbook  # noqa: E402
from pptx import Presentation  # noqa: E402

from workroom.workroom_core.project import Project  # noqa: E402

SRC_DECK = Path(sys.argv[1])  # the board pack made by make_board_pack.py; its numbers match make_workbook() below


def make_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2", "Q3", "Q4"])
    ws.append(["Revenue", 130, 175, 190, 205])
    ws.append(["Costs", 60, 90, 95, 110])
    ws.append(["Margin", 0.40, 0.30, 0.33, 0.35])
    ws.append(["Headcount", 100, 112, 120, 125])
    ws.append(["Cash", 35.0, 39.2, 42.3, 44.0])
    wb.save(path)


def fresh_project(tmp: Path):
    root = tmp / "proj"
    root.mkdir()
    shutil.copy(SRC_DECK, root / "deck.pptx")
    make_workbook(root / "results.xlsx")
    state = tmp / "state"
    proj = Project(root, state)
    d = proj.discover()
    return root, state, proj, d


def snapshot(proj):
    return {t.id: (t.raw, t.src_file + "!" + t.sheet + "!" + t.ref, t.state, t.slide) for t in proj.ties()}


def mutate(name: str, root: Path) -> None:
    deck = root / "deck.pptx"
    if name == "unrelated_text_edit":
        prs = Presentation(deck)
        for sh in prs.slides[0].shapes:
            if sh.has_text_frame and "Prepared for the board" in sh.text_frame.text:
                sh.text_frame.paragraphs[0].runs[0].text = "Prepared for the board of directors."
        prs.save(deck)
    elif name == "insert_slide_before":
        prs = Presentation(deck)
        blank = prs.slide_layouts[6]
        s = prs.slides.add_slide(blank)
        lst = prs.slides._sldIdLst
        el = lst[-1]
        lst.remove(el)
        lst.insert(0, el)
        prs.save(deck)
    elif name == "delete_unrelated_slide":
        prs = Presentation(deck)
        lst = prs.slides._sldIdLst
        rid = lst[2].rId  # slide 3 holds no tie used by the check below
        prs.part.drop_rel(rid)
        lst.remove(lst[2])
        prs.save(deck)
    elif name == "reorder_slides":
        prs = Presentation(deck)
        lst = prs.slides._sldIdLst
        el = lst[0]
        lst.remove(el)
        lst.append(el)
        prs.save(deck)
    elif name == "duplicate_tied_slide":
        prs = Presentation(deck)
        src = prs.slides[0]
        dst = prs.slides.add_slide(prs.slide_layouts[6])
        for sh in src.shapes:
            dst.shapes._spTree.insert_element_before(copy.deepcopy(sh._element), "p:extLst")
        prs.save(deck)
    elif name == "retype_a_tied_number":
        prs = Presentation(deck)
        for sh in prs.slides[0].shapes:
            if sh.has_text_frame and sh.text_frame.text == "$175.0M":
                sh.text_frame.paragraphs[0].runs[0].text = "$176.0M"
        prs.save(deck)
    elif name == "powerpoint_roundtrip":
        import subprocess
        out = root / "rt.pptx"
        ps = (f'$pp = New-Object -ComObject PowerPoint.Application; $p = $pp.Presentations.Open("{deck}", 0, 0, 0); '
              f'$p.SaveCopyAs("{out}"); $p.Close(); $pp.Quit()')
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
        shutil.move(out, deck)
    else:
        raise SystemExit("unknown mutation " + name)


MUTATIONS = ["unrelated_text_edit", "insert_slide_before", "delete_unrelated_slide", "reorder_slides", "duplicate_tied_slide", "retype_a_tied_number", "powerpoint_roundtrip"]
rows = []
for m in MUTATIONS:
    tmp = Path(tempfile.mkdtemp())
    root, state, proj, d0 = fresh_project(tmp)
    before = snapshot(proj)
    # a person confirms two links before the deck is edited
    for tid in list(before)[:2]:
        proj.db.execute("UPDATE ties SET state='confirmed' WHERE id=?", (tid,))
    before = snapshot(proj)
    proj.db.close()
    mutate(m, root)
    proj = Project(root, state)
    d1 = proj.discover()
    after = snapshot(proj)
    kept = [i for i in before if i in after and before[i][0] == after[i][0] and before[i][1] == after[i][1]]
    kept_state = [i for i in kept if before[i][2] == after[i][2]]
    lost = [i for i in before if i not in after]
    created = [i for i in after if i not in before]
    wrong = [i for i in after if i in before and (before[i][0] != after[i][0] or before[i][1] != after[i][1])]
    confirmed_before = [i for i in before if before[i][2] == "confirmed"]
    confirmed_kept = [i for i in confirmed_before if i in after and after[i][2] == "confirmed" and after[i][0] == before[i][0]]
    rows.append({"mutation": m, "ties_before": len(before), "ties_after": len(after), "kept_same_id": len(kept), "dropped": len(lost), "newly_created": len(created),
                 "wrong_links": len(wrong), "confirmed_before": len(confirmed_before), "confirmed_still_confirmed": len(confirmed_kept), "unreadable": list(d1.unreadable)})
    proj.db.close()
print(json.dumps(rows, indent=1))
Path(__file__).with_name("anchor_survival_result.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
