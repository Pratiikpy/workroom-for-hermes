"""The run score: figures backed by evidence and decks without blocking layout faults, as one number with its formula, and honest when there is nothing to judge."""

import io
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt

from workroom.tests.test_room import project
from workroom.workroom_core.figure_proof import EvidenceStore


def test_nothing_to_judge_gives_no_number(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    got = svc.run_score(pid)
    assert got["reward"] is None and "does_not_measure" in got and "formula" in got


def test_a_deck_with_a_blocking_layout_fault_lowers_the_score_and_a_clean_one_does_not(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    for name, size in (("clean.pptx", 24), ("tiny.pptx", 6)):
        prs = Presentation()
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
        s = prs.slides.add_slide(prs.slide_layouts[6])
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
        tb.text_frame.text = "Revenue held"
        tb.text_frame.paragraphs[0].runs[0].font.size = Pt(size)
        buf = io.BytesIO()
        prs.save(buf)
        (root / name).write_bytes(buf.getvalue())
        svc.deliverable_register(pid, name, "made by a script")
    got = svc.run_score(pid)
    assert got["decks_with_blocking_layout_faults"] == ["tiny.pptx"] and got["reward"] == 0.75


def test_figures_count_by_how_well_the_evidence_backs_them(tmp_path: Path, monkeypatch) -> None:
    root, svc, pid = project(tmp_path)
    (root / "memo.md").write_text("x")
    svc.deliverable_register(pid, "memo.md", "made by a script")
    import workroom.workroom_core.service as service

    real = service.Service.deliverables

    def with_proof(self, p):
        return [{**d, "proof": {"figures": 4, "sourced": 2, "calculated": 0, "candidate": 1, "unsourced": 1, "stale": False}} if d["path"] == "memo.md" else d for d in real(self, p)]

    monkeypatch.setattr(service.Service, "deliverables", with_proof)
    got = svc.run_score(pid)
    assert got["figures"] == {"supported": 2, "unclear": 1, "unsourced": 1} and got["reward"] == (2 + 0.5) / 4
    monkeypatch.setattr(service.Service, "deliverables", lambda self, p: [{**d, "proof": {"figures": 4, "sourced": 4, "unsourced": 0, "stale": True}} for d in real(self, p)])
    assert svc.run_score(pid)["reward"] is None  # a proof that is out of date is not counted
    _ = EvidenceStore


def test_the_script_prints_the_score_as_json(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    root, svc, pid = project(tmp_path)
    script = Path(__file__).resolve().parents[1] / "scripts" / "score.py"
    out = subprocess.run([sys.executable, str(script), "--project", pid, "--data-dir", str(svc.data_dir)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and json.loads(out.stdout)["reward"] is None
    bad = subprocess.run([sys.executable, str(script), "--project", "nope", "--data-dir", str(svc.data_dir)], capture_output=True, text=True, timeout=60)
    assert bad.returncode == 1 and "error" in json.loads(bad.stdout)
