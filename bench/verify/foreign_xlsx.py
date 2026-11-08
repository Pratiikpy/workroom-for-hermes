"""Check Workroom's workbook reader against the real Excel on workbooks other people made.

    python foreign_xlsx.py <out.json> <folder or file> [<folder or file> ...] [--limit N] [--batch N]

For every workbook, Workroom's reader (index_workbook) and Excel's own object model are compared:
  * coverage: the numeric cells Excel reports (constants and formulas, every sheet) against the cells Workroom indexed;
  * values: each indexed cell's value against Excel's Value2, and date or currency typing against Excel's Value;
  * hidden state: rows, columns and sheets Excel reports hidden against the flag Workroom sets.
A cell Excel has and Workroom lacks is a silent omission; a differing value is a silent misreading.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

SAMPLE = 4000


def workroom_cells(data: bytes):
    from workroom.workroom_core.ooxml.package import open_package
    from workroom.workroom_core.ooxml.xlsx import index_workbook

    return index_workbook(open_package(data), max_cells=2_000_000)


def numeric_ranges(ws):
    """Excel's own list of numeric cells on one sheet: constants and formulas with a numeric result."""
    cells = []
    for kind in (2, -4123):  # xlCellTypeConstants, xlCellTypeFormulas
        try:
            rng = ws.UsedRange.SpecialCells(kind, 1)  # xlNumbers
        except Exception:  # noqa: BLE001
            continue
        for area in rng.Areas:
            cells.append(area)
    return cells


def inspect(xl, path: Path) -> dict:
    row: dict = {"file": path.name, "bytes": path.stat().st_size}
    data = path.read_bytes()
    t0 = time.time()
    try:
        ours = workroom_cells(data)
    except Exception as exc:  # noqa: BLE001
        row.update(status="workroom_refused", reason=f"{type(exc).__name__}: {str(exc)[:90]}")
        return row
    row["workroom_seconds"] = round(time.time() - t0, 3)
    try:
        wb = xl.Workbooks.Open(str(path), 0, True, None, "x", "x", True)
    except Exception as exc:  # noqa: BLE001
        row.update(status="excel_refused", reason=str(exc)[:120], workroom_cells=len(ours))
        return row
    try:
        by_sheet: dict[str, list] = {}
        for c in ours:
            by_sheet.setdefault(c.sheet, []).append(c)
        names = [ws.Name for ws in wb.Worksheets]
        row["sheets"] = len(names)
        missing, extra, value_bad, date_bad, hidden_missed, formula_diff = [], [], [], [], [], 0
        total_excel = 0
        compared = 0
        for ws in wb.Worksheets:
            ex_keys = set()
            for area in numeric_ranges(ws):
                r0, c0 = area.Row, area.Column
                nr, nc = area.Rows.Count, area.Columns.Count
                if nr * nc > 400_000:
                    row.setdefault("big_area_skipped", 0)
                    row["big_area_skipped"] += 1
                    continue
                vals = area.Value2
                if nr == 1 and nc == 1:
                    vals = ((vals,),)
                for i in range(nr):
                    for j in range(nc):
                        v = vals[i][j]
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            ex_keys.add((r0 + i, c0 + j))
            total_excel += len(ex_keys)
            mine = {(c.row, c.col): c for c in by_sheet.get(ws.Name, [])}
            for key in ex_keys - set(mine):
                if len(missing) < 40:
                    missing.append((ws.Name, key))
            for key in set(mine) - ex_keys:
                if len(extra) < 40:
                    extra.append((ws.Name, key))
            keys = sorted(set(mine) & ex_keys)
            if len(keys) > SAMPLE:
                step = len(keys) / SAMPLE
                keys = [keys[int(i * step)] for i in range(SAMPLE)]
            for (r, c) in keys:
                cell = mine[(r, c)]
                x = ws.Cells(r, c)
                compared += 1
                v2 = x.Value2
                if not (isinstance(v2, (int, float)) and abs(v2 - cell.value) <= 1e-9 * max(1.0, abs(cell.value))):
                    if cell.is_formula:
                        formula_diff += 1
                    elif len(value_bad) < 30:
                        value_bad.append((ws.Name, cell.ref, cell.value, v2))
                typed = type(x.Value).__name__
                excel_date = typed in ("datetime", "pywintypes.datetime", "TimeType") or "time" in typed.lower()
                if excel_date != cell.is_date and len(date_bad) < 30:
                    date_bad.append((ws.Name, cell.ref, cell.is_date, typed, str(x.NumberFormat)[:30]))
                hidden = bool(x.EntireRow.Hidden) or bool(x.EntireColumn.Hidden) or ws.Visible != -1
                if hidden and not cell.hidden and len(hidden_missed) < 30:
                    why = "row" if x.EntireRow.Hidden else "column" if x.EntireColumn.Hidden else "sheet"
                    hidden_missed.append((ws.Name, cell.ref, why))
        row.update(
            status="ok", workroom_cells=len(ours), excel_cells=total_excel, compared=compared,
            missing=len(missing), extra=len(extra), value_mismatch=len(value_bad), formula_cache_differs=formula_diff,
            date_typing_mismatch=len(date_bad), hidden_not_flagged=len(hidden_missed),
            examples={k: v[:5] for k, v in dict(missing=missing, extra=extra, value=value_bad, date=date_bad, hidden=hidden_missed).items() if v},
        )
    finally:
        try:
            wb.Close(False)
        except Exception:  # noqa: BLE001
            pass
    return row


def worker(paths: list[str], out: str) -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.EnableEvents = False
    xl.AutomationSecurity = 3
    rows = []
    try:
        for p in paths:
            try:
                rows.append(inspect(xl, Path(p)))
            except Exception as exc:  # noqa: BLE001
                rows.append({"file": Path(p).name, "status": "harness_error", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"})
            Path(out).write_text(json.dumps(rows), encoding="utf-8")
    finally:
        try:
            xl.Quit()
        except Exception:  # noqa: BLE001
            pass


def collect(targets: list[str]) -> list[Path]:
    seen, out = set(), []
    for t in targets:
        p = Path(t).resolve()
        files = [p] if p.is_file() else [f for f in sorted(p.rglob("*")) if f.suffix.lower() in (".xlsx", ".xlsm") and "~$" not in f.name]
        for f in files:
            if f.stat().st_size == 0:
                continue
            try:
                h = hashlib.sha1(f.read_bytes()).hexdigest()
            except OSError:
                continue
            if h in seen:
                continue
            seen.add(h)
            out.append(f)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--batch", type=int, default=15)
    ap.add_argument("--worker", action="store_true")
    ns = ap.parse_args()
    if ns.worker:
        worker(ns.targets, ns.out)
        return
    files = collect(ns.targets)[: ns.limit]
    work = Path(tempfile.mkdtemp(prefix="foreign-xlsx-"))
    rows: list[dict] = []
    pending = [str(f) for f in files]
    while pending:
        chunk, pending = pending[: ns.batch], pending[ns.batch:]
        out = work / f"part{len(rows)}.json"
        proc = subprocess.Popen([sys.executable, str(Path(__file__)), "--worker", str(out), *chunk])
        try:
            proc.wait(timeout=180 + 25 * len(chunk))
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        done = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else []
        rows.extend(done)
        if len(done) < len(chunk):
            hung = chunk[len(done)]
            rows.append({"file": Path(hung).name, "status": "excel_hung", "reason": "no answer within the time limit"})
            pending = chunk[len(done) + 1:] + pending
        print(f"{len(rows)}/{len(files)}", flush=True)
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {
        "workbooks": len(rows), "by_status": by,
        "with_missing_cells": sum(1 for r in ok if r["missing"]), "with_extra_cells": sum(1 for r in ok if r["extra"]),
        "with_value_mismatch": sum(1 for r in ok if r["value_mismatch"]), "with_date_mismatch": sum(1 for r in ok if r["date_typing_mismatch"]),
        "with_hidden_not_flagged": sum(1 for r in ok if r["hidden_not_flagged"]),
        "cells_compared": sum(r["compared"] for r in ok), "excel_cells": sum(r["excel_cells"] for r in ok), "workroom_cells": sum(r["workroom_cells"] for r in ok),
    }
    Path(ns.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
