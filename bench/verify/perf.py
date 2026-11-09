"""Measure what Workroom costs on large projects: time for each step and the peak memory of the process.

    python perf.py <out.json> [--slides N] [--rows N] [--cols N] [--docs N]

Builds a project whose documents quote figures from a large workbook (a deck of N slides each holding a sentence with three figures and a
table, a Word report of N paragraphs, optionally several of each), then times: reading the project (Find links), previewing a change, preparing
the release, approving it, and restoring it. Nothing is simulated: every figure in the deck is tied to a real cell.
"""

import argparse
import json
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

import psutil  # noqa: E402
from docx import Document  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402
from xlsxwriter import Workbook  # noqa: E402

from workroom.workroom_core.service import Service  # noqa: E402

PROC = psutil.Process()


def peak_mb() -> float:
    info = PROC.memory_info()
    return round(getattr(info, "peak_wset", info.rss) / 1e6, 1)


def build(root: Path, slides: int, rows: int, cols: int, docs: int) -> dict:
    rnd = random.Random(11)
    periods = ["Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025"]
    values = {}
    with Workbook(str(root / "model.xlsx"), {"constant_memory": True}) as wb:
        ws = wb.add_worksheet("Data")
        ws.write_row(0, 0, ["Metric"] + [f"{p}" for p in periods] + [f"Extra {c}" for c in range(cols - len(periods))])
        for r in range(1, rows + 1):
            row = [f"Metric {r:05d} revenue"] + [round(rnd.uniform(1, 900), 1) for _ in range(cols)]
            values[r] = row[1:5]
            ws.write_row(r, 0, row)
    figures = 0
    for d in range(docs):
        prs = Presentation()
        for s in range(slides):
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = f"Review {s + 1}"
            r = 1 + (s * 7 + d * 3) % rows
            q = values[r]
            box = slide.shapes.add_textbox(Inches(0.5), Inches(1.4), Inches(9), Inches(1))
            box.text_frame.text = f"Metric {r:05d} revenue reached ${q[3]:.1f} million in Q4 2025, from ${q[2]:.1f} million in Q3 2025 and ${q[1]:.1f} million in Q2 2025."
            figures += 3
        prs.save(str(root / f"deck{d}.pptx"))
        doc = Document()
        for s in range(slides):
            r = 1 + (s * 5 + d) % rows
            doc.add_paragraph(f"Metric {r:05d} revenue closed the year at ${values[r][3]:.1f} million.")
            figures += 1
        doc.save(str(root / f"report{d}.docx"))
    return {"figures_expected": figures}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--slides", type=int, default=100)
    ap.add_argument("--rows", type=int, default=2000)
    ap.add_argument("--cols", type=int, default=12)
    ap.add_argument("--docs", type=int, default=1)
    ns = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="perf_"))
    state = Path(tempfile.mkdtemp(prefix="perf_state_"))
    t0 = time.time()
    meta = build(root, ns.slides, ns.rows, ns.cols, ns.docs)
    out = {"slides": ns.slides, "rows": ns.rows, "cols": ns.cols, "documents": ns.docs * 2, "build_seconds": round(time.time() - t0, 1), **meta,
           "workbook_cells": ns.rows * (ns.cols + 1), "bytes": sum(p.stat().st_size for p in root.iterdir())}
    svc = Service(state)
    pid = svc.add_project(str(root))["project"]

    def timed(name, fn):
        t = time.time()
        r = fn()
        out[name + "_seconds"] = round(time.time() - t, 2)
        out["peak_mb_after_" + name] = peak_mb()
        return r

    found = timed("find_links", lambda: svc.discover(pid))
    out["numbers_found"], out["linked"] = found["numbers_found"], sum(1 for t in svc.ties(pid) if t["state"] == "accepted")
    # change a tenth of the model's Q4 values
    from openpyxl import load_workbook

    wb = load_workbook(root / "model.xlsx")
    ws = wb["Data"]
    changed = 0
    for r in range(2, ns.rows + 2, 10):
        c = ws.cell(row=r, column=5)
        c.value = round(float(c.value) * 1.05, 1)
        changed += 1
    wb.save(root / "model.xlsx")
    out["source_cells_changed"] = changed
    plan = timed("preview", lambda: svc.plan(pid))
    staged = timed("prepare_release", lambda: svc.stage(pid))
    out["figures_in_release"] = len(staged["changes"])
    timed("approve_publish", lambda: svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True))
    timed("restore", lambda: svc.restore_release(pid, staged["release_id"]))
    out["peak_mb"] = peak_mb()
    Path(ns.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(state, ignore_errors=True)


if __name__ == "__main__":
    main()
