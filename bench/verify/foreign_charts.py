"""Charts in decks other people made: link them to a workbook, change values, and read the result back from the real PowerPoint.

    python foreign_charts.py <out.json> <folder or .pptx> [...] [--limit N]

For every deck with native charts: the chart's own categories and values (read with python-pptx) are written to a workbook, one sheet per chart;
Workroom reads the project and its chart links are compared with where each point really came from; some source values change; Workroom
releases; and the real PowerPoint is asked, through its chart object model, for every series' values: the changed points must hold the new
value, every other point of every chart its old value. The embedded workbook of each chart is read with openpyxl and must agree with the chart.
"""

import argparse
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import pythoncom  # noqa: E402
import win32com.client  # noqa: E402
from foreign_edit import collect, validator_errors  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402
from pptx import Presentation  # noqa: E402

from workroom.workroom_core.service import NeedsAcknowledgement, Service  # noqa: E402


def charts_of(path: Path) -> list[dict]:
    out = []
    prs = Presentation(str(path))

    def walk(si, shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                walk(si, sh.shapes)
            if getattr(sh, "has_chart", False) and sh.has_chart:
                ch = sh.chart
                series = []
                original = 0  # position of the series in the chart, counting those left out of the workbook
                for plot in ch.plots:
                    cats = [str(c) for c in plot.categories]
                    for s in plot.series:
                        vals = list(s.values)
                        if len(cats) == len(vals) and all(v is not None for v in vals) and len(set(cats)) == len(cats):
                            series.append({"name": s.name, "cats": cats, "vals": [float(v) for v in vals], "orig": original})
                        original += 1
                out.append({"slide": si, "shape": sh.shape_id, "name": sh.name, "series": series})

    for si, slide in enumerate(prs.slides, 1):
        walk(si, slide.shapes)
    return [c for c in out if c["series"]]


def mirror(root: Path, charts: list[dict]) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for n, ch in enumerate(charts, 1):
        ws = wb.create_sheet(f"C{n}")
        ws.append(["Category"] + [s["name"] or f"Series {i + 1}" for i, s in enumerate(ch["series"])])
        for r, cat in enumerate(ch["series"][0]["cats"]):
            ws.append([cat] + [s["vals"][r] if r < len(s["vals"]) else None for s in ch["series"]])
    wb.save(root / "charts.xlsx")


def ppt_chart_values(app, path: str) -> list[list[list[float]]]:
    pres = app.Presentations.Open(path, True, False, False)
    out = []
    try:
        for slide in pres.Slides:
            for sh in slide.Shapes:
                if sh.HasChart:
                    ch = sh.Chart
                    out.append([[float(v) if v is not None else float("nan") for v in (ch.SeriesCollection(i).Values or [])] for i in range(1, ch.SeriesCollection().Count + 1)])
    finally:
        pres.Close()
    return out


def embedded_values(data: bytes) -> list[dict]:
    """Per chart: the embedded workbook's cells as openpyxl reads them."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in sorted(z.namelist()):
            if n.startswith("ppt/embeddings/") and n.endswith(".xlsx"):
                wb = load_workbook(io.BytesIO(z.read(n)), data_only=True)
                rows.append({ws.title: {c.coordinate: c.value for r in ws.iter_rows() for c in r if c.value is not None} for ws in wb.worksheets})
    return rows


def run_deck(path: Path, app) -> dict:
    row: dict = {"file": path.name}
    try:
        charts = charts_of(path)
    except Exception as exc:  # noqa: BLE001
        row.update(status="skipped", reason=f"python-pptx: {type(exc).__name__}")
        return row
    if not charts:
        row.update(status="skipped", reason="no chart with plain categories and values")
        return row
    root = Path(tempfile.mkdtemp(prefix="fch_"))
    state = Path(tempfile.mkdtemp(prefix="fch_state_"))
    try:
        shutil.copy2(path, root / path.name)
        mirror(root, charts)
        svc = Service(state)
        pid = svc.add_project(str(root))["project"]
        svc.discover(pid)
        proj, _ = svc._open(pid)
        ties = [t for t in proj.ties() if t.kind == "chart"]
        points = sum(len(s["vals"]) for c in charts for s in c["series"])
        right = wrong = 0
        by_point = {}
        for t in ties:
            info = json.loads(t.chart)
            want_sheet = None
            for n, ch in enumerate(charts, 1):
                if ch["slide"] == t.slide and ch["shape"] == t.shape_id:
                    want_sheet = f"C{n}"
                    ch_i = n - 1
            if want_sheet is None:
                continue
            where = next((k for k, sr in enumerate(charts[ch_i]["series"]) if sr["orig"] == info["series"]), None)
            cats = charts[ch_i]["series"][where]["cats"] if where is not None else []
            ok = t.sheet == want_sheet and info["category"] in cats and t.ref == f"{chr(66 + (where or 0))}{cats.index(info['category']) + 2}" if where is not None else False
            if t.state == "accepted":
                right += ok
                wrong += (not ok)
            by_point[(ch_i, info["series"], info["category"])] = (t, ok)
        svc._close_opened()
        row.update(status="measured", charts=len(charts), points=points, chart_links=len(ties), accepted_right=right, accepted_WRONG=wrong, proposed=sum(1 for t in ties if t.state == "confirm"))
        linked = [(k, v[0]) for k, v in by_point.items() if v[0].state == "accepted" and v[1]]
        if not linked:
            return row
        # change a handful of linked points
        from openpyxl import load_workbook as lw

        wb = lw(root / "charts.xlsx")
        expected = {}
        for (ci, si, cat), t in linked[:6]:
            ws = wb[f"C{ci + 1}"]
            cell = ws[t.ref]
            cell.value = cell.value * 1.1 + 1
            expected[(ci, si, cat)] = cell.value
        wb.save(root / "charts.xlsx")
        before_vals = ppt_chart_values(app, str(root / path.name))
        svc.discover(pid)
        proj2, _ = svc._open(pid)
        held_points = set()
        for note in proj2.plan_refresh().skipped:
            m = re.search(r"chart point '(.+?)' of series (\d+) ", note)
            if m:
                held_points.add((int(m.group(2)) - 1, m.group(1)))
        svc._close_opened()
        row["points_held_with_reason"] = len(held_points)
        for k in list(expected):
            if (k[1], k[2]) in held_points:
                expected.pop(k)
        staged = svc.stage(pid)
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=False)
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
        after_vals = ppt_chart_values(app, str(root / path.name))
        moved = right_new = bad = 0
        for ci, ch in enumerate(charts):
            for s in ch["series"]:
                si = s["orig"]
                for pi, cat in enumerate(s["cats"]):
                    try:
                        old, new = before_vals[ci][si][pi], after_vals[ci][si][pi]
                    except IndexError:
                        continue
                    want = expected.get((ci, si, cat), old)
                    if (new != new and want != want) or abs(new - want) <= 1e-6 * max(1.0, abs(want)):
                        right_new += 1
                        moved += (want != old)
                    else:
                        bad += 1
        data = (root / path.name).read_bytes()
        emb = embedded_values(data)
        emb_ok = True
        for (ci, si, cat), val in expected.items():
            if ci < len(emb):
                sheet = next(iter(emb[ci].values()), {})
                if not any(abs(float(v) - val) <= 1e-6 * max(1.0, abs(val)) for v in sheet.values() if isinstance(v, (int, float))):
                    emb_ok = False
        errs = validator_errors([root / path.name])
        row.update(changed_points=len(expected), points_read_back_ok=right_new, points_moved_as_expected=moved, points_WRONG=bad, embedded_workbook_agrees=emb_ok,
                   validator_errors_after=len(errs.get(str(root / path.name), [])), status="ok" if bad == 0 and emb_ok and moved == len(expected) and len(expected) > 0 else ("FAILED" if bad or not emb_ok else "nothing_writable"))
    except Exception as exc:  # noqa: BLE001
        row.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--limit", type=int, default=10_000)
    ns = ap.parse_args()
    pythoncom.CoInitialize()
    app = win32com.client.DispatchEx("PowerPoint.Application")
    rows = []
    try:
        for i, f in enumerate(collect(ns.targets, (".pptx",))[: ns.limit], 1):
            r = run_deck(f, app)
            rows.append(r)
            print(i, f.name[:40], {k: v for k, v in r.items() if k not in ("file",)}, flush=True)
            Path(ns.out).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    finally:
        app.Quit()
    ok = [r for r in rows if r["status"] in ("ok", "measured")]
    print(json.dumps({"decks": len(rows), "with_charts": len([r for r in rows if r["status"] != "skipped"]), "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] == "FAILED" for r in rows), "errors": sum(r["status"] == "error" for r in rows)}))


if __name__ == "__main__":
    main()
