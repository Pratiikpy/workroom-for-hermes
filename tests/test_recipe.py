"""The reporting recipe: a model report's approved links are inherited by a copy of it."""

import json
from pathlib import Path

import pytest

from workroom.tests.test_docx import make_docx, texts
from workroom.tests.test_flagship_headless import change_source, make_workbook
from workroom.workroom_core import recipe
from workroom.workroom_core.service import Service, ServiceError


def project(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "q2.docx").write_bytes(make_docx())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return root, svc, pid


def approved(svc: Service, pid: str, deck: str = "q2.docx") -> dict:
    proposed = svc.recipe_propose(pid, deck)
    return svc.recipe_approve(pid, proposed["proposal"], proposed["digest"])


def test_a_proposal_changes_nothing_and_only_the_owner_route_installs_it(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    proposed = svc.recipe_propose(pid, "q2.docx")
    assert proposed["links"] >= 2 and svc.recipe_status(pid)["active"] is None
    assert [p["proposal"] for p in svc.recipe_status(pid)["pending"]] == [proposed["proposal"]]
    with pytest.raises(ServiceError, match="not the recipe you were shown"):
        svc.recipe_approve(pid, proposed["proposal"], "0" * 64)
    done = svc.recipe_approve(pid, proposed["proposal"], proposed["digest"])
    status = svc.recipe_status(pid)
    assert done["version"] == 1 and status["active"]["model"] == "q2.docx" and status["pending"] == []


def test_no_agent_tool_can_install_a_recipe() -> None:
    from workroom import TOOLS

    names = {t[0] for t in TOOLS}
    assert "workroom_recipe_propose" in names and "workroom_recipe_status" in names
    assert not any("approve" in n or "install" in n or "revoke" in n for n in names if n.startswith("workroom_recipe"))
    assert {t[4] for t in TOOLS if t[0] == "workroom_recipe_status"} == {"workroom_ro"}


def test_a_proposal_for_a_report_with_no_accepted_links_is_refused(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    (root / "empty.docx").write_bytes(_blank_docx())
    svc.discover(pid)
    with pytest.raises(ServiceError, match="no links yet"):
        svc.recipe_propose(pid, "empty.docx")


def test_a_tampered_or_stale_proposal_is_not_installed(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    proposed = svc.recipe_propose(pid, "q2.docx")
    path = tmp_path / "data" / "projects" / svc._resolve(pid) / "recipes" / f"{proposed['proposal']}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rules"][0]["ref"] = "Z99"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ServiceError, match="digest"):
        svc.recipe_approve(pid, proposed["proposal"], proposed["digest"])
    proposed = svc.recipe_propose(pid, "q2.docx")
    (root / "q2.docx").write_bytes(make_docx() + b"")  # same bytes: unchanged
    changed = root / "q2.docx"
    data = bytearray(changed.read_bytes())
    data[-1] ^= 1
    changed.write_bytes(bytes(data))
    with pytest.raises(ServiceError, match="changed since"):
        svc.recipe_approve(pid, proposed["proposal"], proposed["digest"])


def test_a_copy_of_the_model_inherits_its_links_and_follows_the_workbook(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    (root / "q3.docx").write_bytes((root / "q2.docx").read_bytes())  # last period's report, copied
    change_source(root, "C2", 150)
    change_source(root, "C4", 0.30)
    found = svc.discover(pid)
    ties = [t for t in svc.ties(pid) if t["deck"] == "q3.docx"]
    assert len([t for t in ties if t["state"] == "accepted"]) >= 2
    assert found["accepted"] >= 4  # both reports
    staged = svc.stage(pid)
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
    for name in ("q2.docx", "q3.docx"):
        assert "Revenue in Q2 was 150 and margin was 30%." in texts((root / name).read_bytes())
        assert "Headcount reached 120 people." in texts((root / name).read_bytes())  # the decoy is never touched


def test_explain_says_a_recipe_link_came_from_the_model(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    (root / "q3.docx").write_bytes((root / "q2.docx").read_bytes())
    svc.discover(pid)
    link = next(t for t in svc.ties(pid) if t["deck"] == "q3.docx" and t["state"] == "accepted")
    assert "model report" in svc.explain(pid, link["id"])["how"]


def test_a_copy_whose_figure_was_retyped_keeps_it_held_not_overwritten(tmp_path: Path) -> None:
    from docx import Document
    import io

    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    d = Document(io.BytesIO((root / "q2.docx").read_bytes()))
    for p in d.paragraphs:
        for r in p.runs:
            if r.text == "120":
                r.text = "125"
    buf = io.BytesIO()
    d.save(buf)
    (root / "q3.docx").write_bytes(buf.getvalue())
    svc.discover(pid)
    revenue = [t for t in svc.ties(pid) if t["deck"] == "q3.docx" and "Revenue in Q2" in t["sentence"]]
    assert revenue and revenue[0]["state"] in ("held", "confirm")


def test_revoking_the_recipe_stops_copies_inheriting_links(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    svc.recipe_revoke(pid)
    (root / "q3.docx").write_bytes((root / "q2.docx").read_bytes())
    change_source(root, "C2", 150)
    svc.discover(pid)
    carried = [t for t in svc.ties(pid) if t["deck"] == "q3.docx"]
    assert all(svc.explain(pid, t["id"])["how"].find("model report") < 0 for t in carried)


def test_a_model_of_another_kind_is_never_used_for_a_document(tmp_path: Path) -> None:
    from workroom.workroom_core.project import Project

    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    proj = Project(root, tmp_path / "data" / "projects" / svc._resolve(pid))
    assert recipe.carry(proj, "deck.pptx") == 0 and recipe.carry(proj, "q2.docx") == 0


def test_the_recipe_history_keeps_every_version(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    approved(svc, pid)
    approved(svc, pid)
    versions = svc.recipe_status(pid)["history"]
    assert [v["version"] for v in versions] == [1, 2] and [v["active"] for v in versions] == [False, True]


def _blank_docx() -> bytes:
    import io

    from docx import Document

    d = Document()
    d.add_paragraph("No figures here.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_a_table_that_lost_a_source_is_not_half_updated_and_an_acknowledgement_cannot_release_it(tmp_path: Path) -> None:
    from docx import Document
    import io

    from workroom.tests.test_flagship_headless import make_workbook

    d = Document()
    d.add_paragraph("Results")
    t = d.add_table(rows=3, cols=3)
    for c, v in enumerate(["Metric", "Q1", "Q2"]):
        t.cell(0, c).text = v
    for c, v in enumerate(["Revenue", "100", "120"]):
        t.cell(1, c).text = v
    for c, v in enumerate(["Costs", "60", "90"]):
        t.cell(2, c).text = v
    d.add_paragraph("Revenue in Q2 was 120 for the year.")
    buf = io.BytesIO()
    d.save(buf)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "report.docx").write_bytes(buf.getvalue())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    # Revenue Q2 changes; Costs Q2 loses its number (the row was cleared in the new workbook)
    import zipfile

    src = zipfile.ZipFile(io.BytesIO((root / "results.xlsx").read_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            raw = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = raw.decode("utf-8")
                assert 'r="C2"' in text and 'r="C3"' in text
                import re

                text = re.sub(r'<c r="C2"[^>]*><v>120</v></c>', '<c r="C2"><v>150</v></c>', text)
                text = re.sub(r'<c r="C3"[^>]*><v>90</v></c>', '<c r="C3"/>', text)
                raw = text.encode("utf-8")
            z.writestr(item, raw)
    (root / "results.xlsx").write_bytes(out.getvalue())
    staged = svc.stage(pid)
    assert staged["blocked"] and "mix old and new" in staged["blocked"][0]
    svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    after = texts((root / "report.docx").read_bytes())
    assert "120" in after and "150" not in after[2:5] + after[5:8]  # the table kept every old figure
    assert "Revenue in Q2 was 150 for the year." in after  # the sentence is not in the broken table and follows the workbook
