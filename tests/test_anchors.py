"""Contract C4: ties survive the edits people and programs make to a document (T-ANC-1 to T-ANC-9)."""
import copy
import io
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from workroom.workroom_core.project import Project


def _workbook(root: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2", "Q3"])
    ws.append(["Revenue", 130, 175, 190])
    ws.append(["Margin", 0.40, 0.30, 0.33])
    ws.append(["Headcount", 100, 112, 120])
    wb.save(root / "results.xlsx")


def _deck(root: Path) -> None:
    prs = Presentation()
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(blank)
    s1.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text_frame.text = "Revenue in Q2 was 175 and margin was 30%"
    s2 = prs.slides.add_slide(blank)
    tb = s2.shapes.add_table(2, 3, Inches(1), Inches(1), Inches(6), Inches(1)).table
    for c, v in enumerate(["Metric", "Q2", "Q3"]):
        tb.cell(0, c).text = v
    for c, v in enumerate(["Revenue", "175", "190"]):
        tb.cell(1, c).text = v
    s3 = prs.slides.add_slide(blank)
    s3.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1)).text_frame.text = "Headcount reached 120 people"
    prs.save(root / "deck.pptx")


def _project(tmp_path: Path) -> tuple[Project, Path]:
    root = tmp_path / "p"
    root.mkdir()
    _workbook(root)
    _deck(root)
    proj = Project(root, tmp_path / "state")
    proj.discover()
    return proj, root


def _ties(proj: Project) -> dict[int, tuple]:
    return {t.id: (t.raw, t.ref, t.state, t.slide) for t in proj.ties()}


def _confirm_all(proj: Project) -> None:
    proj.db.execute("UPDATE ties SET state='confirmed' WHERE state IN ('accepted','confirm')")


def _edit(root: Path, fn) -> None:
    prs = Presentation(root / "deck.pptx")
    fn(prs)
    prs.save(root / "deck.pptx")


def _assert_survived(before: dict, after: dict, *, moved_by: int = 0, expect_drop: int = 0) -> None:
    kept = [i for i in before if i in after]
    assert len(kept) == len(before) - expect_drop, f"ties lost: {len(before) - len(kept)} of {len(before)}"
    for i in kept:
        assert after[i][0] == before[i][0] and after[i][1] == before[i][1], "a tie now points at a different number or cell"
        assert after[i][2] == before[i][2], f"state changed for tie {i}: {before[i][2]} -> {after[i][2]}"
    assert len(after) == len(before) - expect_drop, "extra ties were created"


def test_t_anc_1_unrelated_text_edit_keeps_every_tie(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)

    def fn(prs):
        for sh in prs.slides[2].shapes:
            if sh.has_text_frame:
                sh.text_frame.paragraphs[0].runs[0].text = "Headcount reached 120 people across both shops"

    _edit(root, fn)
    proj.discover()
    _assert_survived(before, _ties(proj))


def test_t_anc_2_a_slide_inserted_before_keeps_every_tie_and_every_confirmation(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)

    def fn(prs):
        prs.slides.add_slide(prs.slide_layouts[6])
        lst = prs.slides._sldIdLst
        el = lst[-1]
        lst.remove(el)
        lst.insert(0, el)

    _edit(root, fn)
    proj.discover()
    after = _ties(proj)
    _assert_survived(before, after)
    assert all(after[i][3] == before[i][3] + 1 for i in before), "tie slide numbers were not refreshed after the insert"


def test_t_anc_3_reordered_slides_keep_every_tie(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)

    def fn(prs):
        lst = prs.slides._sldIdLst
        el = lst[0]
        lst.remove(el)
        lst.append(el)

    _edit(root, fn)
    proj.discover()
    _assert_survived(before, _ties(proj))


def test_t_anc_4_deleting_an_unrelated_slide_keeps_the_others(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)
    gone = {i for i, v in before.items() if v[3] == 3}

    def fn(prs):
        lst = prs.slides._sldIdLst
        prs.part.drop_rel(lst[2].rId)
        lst.remove(lst[2])

    _edit(root, fn)
    proj.discover()
    after = _ties(proj)
    assert set(after) == set(before) - gone
    for i in after:
        assert after[i][:3] == before[i][:3]


def test_t_anc_5_a_duplicated_slide_gets_its_own_ties_and_does_not_steal_the_originals(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)

    def fn(prs):
        src = prs.slides[0]
        dst = prs.slides.add_slide(prs.slide_layouts[6])
        for sh in src.shapes:
            dst.shapes._spTree.insert_element_before(copy.deepcopy(sh._element), "p:extLst")

    _edit(root, fn)
    proj.discover()
    after = _ties(proj)
    for i in before:
        assert i in after and after[i][:3] == before[i][:3], "an original tie was moved or lost"
    assert len(after) > len(before)


def test_t_anc_6_a_number_retyped_by_hand_is_held_not_forgotten(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)
    target = next(i for i, v in before.items() if v[0] == "120")

    def fn(prs):
        for sh in prs.slides[2].shapes:
            if sh.has_text_frame:
                sh.text_frame.paragraphs[0].runs[0].text = "Headcount reached 121 people"

    _edit(root, fn)
    proj.discover()
    held = proj.tie(target)
    assert held is not None, "the tie of a retyped number was forgotten"
    assert held.state == "held"
    assert [t for t in proj.ties(("accepted", "confirmed")) if t.id == target] == []
    # a source change must not overwrite the human's number
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Metric", "Q1", "Q2", "Q3"])
    ws.append(["Revenue", 130, 175, 190])
    ws.append(["Margin", 0.40, 0.30, 0.33])
    ws.append(["Headcount", 100, 112, 130])
    wb.save(root / "results.xlsx")
    plan = proj.plan_refresh()
    assert not any("121" in s or "130" in s for s in [i.new_text for i in plan.impacts]), "the human's number was overwritten"
    assert any("held" in s for s in plan.skipped)


def test_t_anc_6b_a_held_tie_returns_when_the_human_restores_the_number(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    target = next(i for i, v in _ties(proj).items() if v[0] == "120")

    def retype(text):
        def fn(prs):
            for sh in prs.slides[2].shapes:
                if sh.has_text_frame:
                    sh.text_frame.paragraphs[0].runs[0].text = text
        return fn

    _edit(root, retype("Headcount reached 121 people"))
    proj.discover()
    assert proj.tie(target).state == "held"
    _edit(root, retype("Headcount reached 120 people"))
    proj.discover()
    assert proj.tie(target).state == "confirmed"


def test_t_anc_7_words_added_before_a_number_in_the_same_paragraph_reanchor_it(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)

    def fn(prs):
        for sh in prs.slides[0].shapes:
            if sh.has_text_frame:
                sh.text_frame.paragraphs[0].runs[0].text = "Group revenue in Q2 was 175 and margin was 30%"

    _edit(root, fn)
    proj.discover()
    _assert_survived(before, _ties(proj))


def test_t_anc_8_rescanning_an_unchanged_project_changes_nothing(tmp_path: Path) -> None:
    proj, root = _project(tmp_path)
    _confirm_all(proj)
    before = _ties(proj)
    for _ in range(3):
        proj.discover()
    assert _ties(proj) == before


def test_t_anc_9_a_paragraph_inserted_above_a_number_in_word_keeps_the_tie(tmp_path: Path) -> None:
    root = tmp_path / "w"
    root.mkdir()
    _workbook(root)
    d = Document()
    d.add_paragraph("Introduction paragraph.")
    d.add_paragraph("Revenue in Q2 was 175 and margin was 30%.")
    d.save(root / "report.docx")
    proj = Project(root, tmp_path / "state")
    proj.discover()
    _confirm_all(proj)
    before = _ties(proj)
    assert before, "nothing was linked in the Word file"
    d = Document(root / "report.docx")
    first = d.paragraphs[0]
    first.insert_paragraph_before("A new opening paragraph the reader added.")
    d.save(root / "report.docx")
    proj.discover()
    _assert_survived(before, _ties(proj))
