import io
import json
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

from workroom.tests.test_flagship_headless import make_workbook
from workroom.workroom_core.ooxml.docx import Doc
from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell
from workroom.workroom_core.service import Service

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
q = lambda t: "{%s}%s" % (W, t)


def body_paragraph(data: bytes, index: int = 1) -> etree._Element:
    import zipfile

    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    return list(root.iter(q("p")))[index]


def accept_all(p: etree._Element) -> str:
    return "".join(t.text or "" for t in p.iter(q("t")) if not any(a.tag == q("del") for a in t.iterancestors()))


def reject_all(p: etree._Element) -> str:
    out = []
    for el in p.iter():
        if el.tag == q("t") and not any(a.tag == q("ins") for a in el.iterancestors()):
            out.append(el.text or "")
        elif el.tag == q("delText"):
            out.append(el.text or "")
    return "".join(out)


def make_doc(text_runs) -> bytes:
    d = Document()
    d.add_heading("Q2 results", 1)
    para = d.add_paragraph()
    for text, bold in text_runs:
        r = para.add_run(text)
        r.bold = bold
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def edit(data: bytes, old: str, new: str, tracked: bool) -> bytes:
    doc = Doc(data)
    doc.tracked = tracked
    m = next(x for x in doc.mentions() if x.number.raw == old)
    doc.edit_mention(m, new)
    return doc.serialize()[0]


def test_a_tracked_edit_strikes_the_old_number_and_inserts_the_new_one() -> None:
    data = make_doc([("Revenue in Q2 was ", False), ("120", True), (" and margin was 25%.", False)])
    out = edit(data, "120", "150", tracked=True)
    p = body_paragraph(out)
    assert accept_all(p) == "Revenue in Q2 was 150 and margin was 25%."
    assert reject_all(p) == "Revenue in Q2 was 120 and margin was 25%."
    dels, inss = list(p.iter(q("del"))), list(p.iter(q("ins")))
    assert len(dels) == len(inss) == 1 and dels[0].get(q("author")) == "Workroom" == inss[0].get(q("author"))
    assert inss[0].find(".//" + q("rPr") + "/" + q("b")) is not None  # the inserted number keeps the bold of the digits it replaced
    Document(io.BytesIO(out))  # python-docx still opens it


def test_a_number_split_over_formatted_runs_is_struck_out_whole() -> None:
    data = make_doc([("Total 12", False), ("0 units", True)])
    out = edit(data, "120", "150", tracked=True)
    p = body_paragraph(out)
    assert accept_all(p) == "Total 150 units" and reject_all(p) == "Total 120 units"
    assert len(list(p.iter(q("del")))) == 2 and len(list(p.iter(q("ins")))) == 1


def test_a_direct_edit_is_unchanged_when_tracking_is_off() -> None:
    out = edit(make_doc([("Revenue was 120.", False)]), "120", "150", tracked=False)
    p = body_paragraph(out)
    assert accept_all(p) == "Revenue was 150." and not list(p.iter(q("ins"))) and not list(p.iter(q("del")))


def project(tmp_path: Path, tracked: bool):
    root = tmp_path / "w"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    d = Document()
    d.add_paragraph("Revenue in Q2 was 120 and margin was 25%.")
    d.save(root / "report.docx")
    (root / "workroom.json").write_text(json.dumps({"tracked_changes": tracked, "targets": []}))
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, root, pid


def set_source(root: Path, ref: str, value: float) -> None:
    f = root / "results.xlsx"
    f.write_bytes(patch_numeric_cell(f.read_bytes(), "Results", ref, value))


def release(svc: Service, pid: str) -> None:
    st = svc.stage(pid)
    assert st["state"] != "blocked", st
    svc.approve_and_publish(pid, st["release_id"], st["digest"])


def test_a_project_can_release_word_changes_as_tracked_changes(tmp_path: Path) -> None:
    svc, root, pid = project(tmp_path, tracked=True)
    set_source(root, "C2", 150)
    set_source(root, "C4", 0.30)
    release(svc, pid)
    p = body_paragraph((root / "report.docx").read_bytes(), 0)
    assert accept_all(p) == "Revenue in Q2 was 150 and margin was 30%."
    assert reject_all(p) == "Revenue in Q2 was 120 and margin was 25%."
    assert len(list(p.iter(q("ins")))) == 2
    assert all(t["state"] in ("accepted", "confirmed") for t in svc.ties(pid))  # links survived being re-anchored


def test_a_second_release_updates_workrooms_own_insertion_in_place(tmp_path: Path) -> None:
    svc, root, pid = project(tmp_path, tracked=True)
    set_source(root, "C2", 150)
    release(svc, pid)
    set_source(root, "C2", 170)
    assert [c["new_text"] for c in svc.plan(pid)["changes"]] == ["170"]
    release(svc, pid)
    p = body_paragraph((root / "report.docx").read_bytes(), 0)
    assert accept_all(p) == "Revenue in Q2 was 170 and margin was 25%."
    assert reject_all(p) == "Revenue in Q2 was 120 and margin was 25%."  # rejecting still gets the owner's original back
    assert len(list(p.iter(q("del")))) == 1 and len(list(p.iter(q("ins")))) == 1  # no pile of nested revisions


def test_text_another_reviewer_inserted_is_left_alone(tmp_path: Path) -> None:
    svc, root, pid = project(tmp_path, tracked=True)
    docx = (root / "report.docx").read_bytes()
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(docx))
    xml = z.read("word/document.xml").decode()
    xml = xml.replace("<w:r><w:t>Revenue in Q2 was 120 and margin was 25%.</w:t></w:r>",
                      f'<w:ins w:id="7" w:author="Someone Else" w:date="2026-01-01T00:00:00Z"><w:r><w:t>Revenue in Q2 was 120 and margin was 25%.</w:t></w:r></w:ins>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in z.namelist():
            out.writestr(n, xml if n == "word/document.xml" else z.read(n))
    assert "Someone Else" in xml  # the substitution really happened
    (root / "report.docx").write_bytes(buf.getvalue())
    svc.discover(pid)
    set_source(root, "C2", 150)
    assert svc.plan(pid)["changes"] == []  # nothing found to change inside a stranger's insertion


def test_the_tracked_changes_setting_is_stored_with_the_project(tmp_path: Path) -> None:
    svc, root, pid = project(tmp_path, tracked=False)
    assert svc.settings(pid) == {"tracked_changes": False}
    assert svc.set_settings(pid, True) == {"tracked_changes": True}
    cfg = json.loads((root / "workroom.json").read_text())
    assert cfg["tracked_changes"] is True and cfg["targets"] == []  # other keys the owner wrote are kept
    set_source(root, "C2", 150)
    release(svc, pid)
    assert list(body_paragraph((root / "report.docx").read_bytes(), 0).iter(q("ins")))


def test_a_project_can_be_named_by_folder_name_or_path_and_unknown_names_list_the_known_ones(tmp_path: Path) -> None:
    svc, root, pid = project(tmp_path, tracked=False)
    assert svc.settings("w") == svc.settings(pid) == svc.settings(str(root))
    with pytest.raises(Exception) as err:
        svc.settings("nope")
    assert pid in str(err.value) and "workroom_status" in str(err.value)


def test_the_status_tool_lists_projects_so_an_agent_can_find_the_id(tmp_path: Path, monkeypatch) -> None:
    from workroom.adapters import tools

    svc, root, pid = project(tmp_path, tracked=False)
    monkeypatch.setattr(tools, "service", lambda: svc)
    monkeypatch.setattr(tools, "host_status", lambda: {"ready": True})
    out = json.loads(tools.workroom_status({}))
    assert out["projects"] == [{"project": pid, "folder": str(root.resolve())}]
