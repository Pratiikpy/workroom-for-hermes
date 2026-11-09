"""Run Workroom on one independently authored report-and-workbook pair, following VPSC_PROTOCOL.md.

    python real_pair.py <report.docx> <workbook.xlsx> <out.json>

The files are copied into a fresh project folder; the originals are never touched. Real Word reads the result back when it is installed.
"""

import io
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from lxml import etree  # noqa: E402

from workroom.workroom_core.service import NeedsAcknowledgement, Service  # noqa: E402

S_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sheet_part(z: zipfile.ZipFile, sheet: str) -> str:
    wb = etree.fromstring(z.read("xl/workbook.xml"))
    rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid = next(s.get("{%s}id" % R_NS) for s in wb.iter("{%s}sheet" % S_NS) if s.get("name") == sheet)
    target = next(r.get("Target") for r in rels if r.get("Id") == rid)
    return target.lstrip("/") if target.startswith("/") else "xl/" + target


def set_constant(xlsx: Path, sheet: str, ref: str, value: float) -> bool:
    """Change one constant numeric cell in the workbook's XML and leave every other byte of the cell grid alone. False when the cell is a formula or not numeric."""
    data = xlsx.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        part = sheet_part(z, sheet)
        root = etree.fromstring(z.read(part))
        cell = next((c for c in root.iter("{%s}c" % S_NS) if c.get("r") == ref), None)
        if cell is None or cell.find("{%s}f" % S_NS) is not None or cell.get("t") not in (None, "n"):
            return False
        v = cell.find("{%s}v" % S_NS)
        if v is None:
            return False
        v.text = repr(float(value))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in z.infolist():
                dst.writestr(info, etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if info.filename == part else z.read(info.filename))
    xlsx.write_bytes(out.getvalue())
    return True


def paragraphs(docx: Path) -> list[str]:
    from docx import Document

    d = Document(str(docx))
    out = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            out.extend(c.text for c in row.cells)
    return out


def word_read(docx: Path) -> dict:
    try:
        import win32com.client as w
    except ImportError:
        return {"status": "no pywin32"}
    app = w.DispatchEx("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    try:
        doc = app.Documents.Open(str(docx), ReadOnly=True, AddToRecentFiles=False)
        n = doc.Paragraphs.Count
        doc.Close(False)
        return {"status": "opened", "paragraphs": n}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": str(exc)[:150]}
    finally:
        app.Quit()


def main() -> None:
    report, workbook, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    tmp = Path(tempfile.mkdtemp(prefix="real_pair_"))
    root = tmp / "project"
    root.mkdir()
    shutil.copy2(report, root / report.name)
    shutil.copy2(workbook, root / workbook.name)
    result: dict = {"report": report.name, "workbook": workbook.name}
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    t0 = time.time()
    found = svc.discover(pid)
    result["discover_seconds"] = round(time.time() - t0, 1)
    result["discover"] = {k: (v if not isinstance(v, list) else len(v)) for k, v in found.items()}
    ties = svc.ties(pid)
    states: dict[str, int] = {}
    for t in ties:
        states[t["state"]] = states.get(t["state"], 0) + 1
    result["states"] = states
    result["asked"] = sum(1 for t in ties if t["state"] == "confirm" and not t["coincidence"])
    result["coincidences_not_asked"] = sum(1 for t in ties if t["state"] == "confirm" and t["coincidence"])
    accepted = [t for t in ties if t["state"] in ("accepted", "confirmed")]
    rows = []
    for t in accepted:
        why = svc.explain(pid, t["id"])
        rows.append({"id": t["id"], "text": t["text"], "sentence": t["sentence"][:240], "source": t["source"], "row": why["source"]["row"], "column": why["source"]["column"], "formula": why["source"]["formula"], "value": why["source"]["value_now"]})
    result["automatic_links"] = rows
    result["asked_examples"] = [{"text": t["text"], "sentence": t["sentence"][:160], "note": t["note"]} for t in ties if t["state"] == "confirm"][:15]

    # the release test: change up to 10 constant source cells of automatic links
    before = paragraphs(root / report.name)
    changed = []
    for r in rows:
        if len(changed) >= 10:
            break
        file_, rest = r["source"].split(" ", 1)
        sheet, ref = rest.rsplit("!", 1)
        cur = r["value"]
        if cur is None or r["formula"]:
            continue
        new = float(cur) * 1.5 + 1
        if set_constant(root / file_, sheet, ref, new):
            changed.append({"id": r["id"], "source": r["source"], "old": cur, "new": new, "text": r["text"]})
    result["changed_cells"] = changed
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("discover_seconds", "discover", "states", "asked", "coincidences_not_asked")}, indent=1), flush=True)
    print("automatic links:", len(rows), "| cells changed for the release test:", len(changed), flush=True)
    try:
        staged = svc.stage(pid)
    except Exception as exc:  # noqa: BLE001
        result["stage_error"] = str(exc)[:300]
        out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print("stage refused:", result["stage_error"])
        return
    result["stage"] = {k: staged.get(k) for k in ("state", "held")} | {"changes": len(staged.get("changes", [])), "flags": [f["kind"] for f in staged.get("flags", [])]}
    result["planned"] = [{"old": c["old_text"], "new": c["new_text"], "where": c.get("where")} for c in staged.get("changes", [])][:40]
    if staged.get("state") == "awaiting_approval":
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
        after = paragraphs(root / report.name)
        diff = [(a, b) for a, b in zip(before, after) if a != b]
        result["paragraphs_before_after_equal_length"] = len(before) == len(after)
        result["paragraphs_changed"] = len(diff)
        result["diffs"] = [{"before": a[:200], "after": b[:200]} for a, b in diff[:25]]
        result["word"] = word_read(root / report.name)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print("planned:", len(result["planned"]), "| paragraphs changed:", result.get("paragraphs_changed"))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
