"""Restructure the source workbook with the real Excel, then check that every link still reads the right cell.

    python foreign_excel_shift.py <FRED folder> <out.json>

For each operation a fresh quarterly project (the deck is tied to economy.xlsx) is built; Excel itself then rewrites or restructures the workbook
(save-as, inserted column or rows, sorted rows, renamed or reordered sheets, a moved block, a table, constants turned into formulas, a hidden
column); one source cell gets a new value in the same Excel session; Workroom reads the project and prepares a release. The oracle: the
release must change exactly the figures that were linked to that cell before the restructuring, to the value the cell now holds, and nothing
else. A figure updated from another cell is a silent error; a figure not updated and not reported is a silent miss.
"""

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import cycles  # noqa: E402
import pythoncom  # noqa: E402
import win32com.client  # noqa: E402

from workroom.workroom_core.match.numbers import format_like, parse_numbers  # noqa: E402
from workroom.workroom_core.service import Service, ServiceError  # noqa: E402

TARGET_ROW_LABEL_OFFSET = -1  # the cell edited: the second-latest quarter of Nominal GDP (it is used by a sentence and a table row)


def find(ws, text: str):
    r = ws.UsedRange.Find(text, LookIn=-4163, LookAt=1)  # xlValues, xlWhole
    return r


def op_saveas(xl, wb, ws):
    pass


def op_insert_column(xl, wb, ws):
    ws.Columns(2).Insert()
    ws.Cells(1, 2).Value = "Notes"
    ws.Cells(2, 2).Value = "preliminary"


def op_insert_rows(xl, wb, ws):
    ws.Rows("1:3").Insert()
    ws.Cells(1, 1).Value = "Macro data pack"
    ws.Cells(2, 1).Value = "prepared by finance"


def op_sort_desc(xl, wb, ws):
    last = ws.UsedRange.Rows.Count
    ws.Range(ws.Cells(2, 1), ws.Cells(last, ws.UsedRange.Columns.Count)).Sort(Key1=ws.Cells(2, 1), Order1=2, Header=2)


def op_rename_and_reorder(xl, wb, ws):
    ws.Name = "Economy"
    extra = wb.Worksheets.Add(Before=wb.Worksheets(1))
    extra.Name = "Cover"
    extra.Cells(1, 1).Value = "Cover page"


def op_move_block(xl, wb, ws):
    rng = ws.UsedRange
    rng.Cut(ws.Cells(6, 4))


def op_table(xl, wb, ws):
    lo = ws.ListObjects.Add(1, ws.UsedRange, None, 1)
    lo.Name = "Macro"


def op_formulas(xl, wb, ws):
    """Constants become formulas over an Inputs sheet, the way a model is built: =Inputs!B2 and so on."""
    inputs = wb.Worksheets.Add(After=ws)
    inputs.Name = "Inputs"
    rows, cols = ws.UsedRange.Rows.Count, ws.UsedRange.Columns.Count
    for r in range(2, rows + 1):
        for c in range(2, cols + 1):
            inputs.Cells(r, c).Value2 = ws.Cells(r, c).Value2
            addr = inputs.Cells(r, c).Address.replace("$", "")
            ws.Cells(r, c).Formula = f"=Inputs!{addr}"


def op_hide_column(xl, wb, ws):
    ws.Columns(3).Hidden = True


OPS = {
    "excel save-as only": op_saveas,
    "a column inserted before the data": op_insert_column,
    "three rows inserted above the table": op_insert_rows,
    "rows sorted newest first": op_sort_desc,
    "sheet renamed, a cover sheet added first": op_rename_and_reorder,
    "the whole block cut and pasted lower and to the right": op_move_block,
    "range turned into an Excel table": op_table,
    "constants turned into formulas over an Inputs sheet": op_formulas,
    "a column hidden": op_hide_column,
}


def locate(ws, row_label: str, col_header_part: str):
    r = find(ws, row_label)
    c = ws.UsedRange.Find(col_header_part, LookIn=-4163, LookAt=2)
    return None if r is None or c is None else ws.Cells(r.Row, c.Column)


def tied_text(deck_path: Path) -> list[str]:
    from pptx import Presentation

    out: list[str] = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                walk(sh.shapes)
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                out.extend(p.text for p in sh.text_frame.paragraphs)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for c in row.cells:
                        out.extend(p.text for p in c.text_frame.paragraphs)

    for slide in Presentation(str(deck_path)).slides:
        walk(slide.shapes)
        if slide.has_notes_slide:
            out.extend(p.text for p in slide.notes_slide.notes_text_frame.paragraphs)
    return out


def run_one(xl, name: str, op, fred: Path) -> dict:
    kind = cycles.QuarterlyDeck(fred, "Q1 2025", "Q3 2026")
    root = Path(tempfile.mkdtemp(prefix="shift_"))
    state = Path(tempfile.mkdtemp(prefix="shift_state_"))
    kind.workbook(root, 2)  # three quarters of history behind the first: the deck is about the latest
    kind.build(root)
    svc = Service(state)
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    cycles.settle(svc, pid)
    book = root / "economy.xlsx"
    before_ties = svc.ties(pid)
    latest = kind.labels[kind.first]
    row: dict = {"operation": name}
    wb = xl.Workbooks.Open(str(book))
    try:
        ws = wb.Worksheets("Data")
        # choose the cell: Nominal GDP in the quarter the deck is about
        pre_cell = locate(ws, latest, "Nominal GDP")
        if pre_cell is None:
            row.update(status="harness_error", why="could not find the target cell before the operation")
            return row
        pre_addr = pre_cell.Address.replace("$", "")
        linked_before = [t for t in before_ties if t["source"].endswith("!" + pre_addr)]
        old_value = pre_cell.Value2
        op(xl, wb, ws)
        ws2 = next(w for w in wb.Worksheets if w.Name in ("Data", "Economy"))
        cell = locate(ws2, latest, "Nominal GDP")
        if cell is None:
            row.update(status="harness_error", why="could not find the target cell after the operation")
            return row
        new_value = old_value * 1.07
        cell.Value2 = new_value if not cell.HasFormula else new_value
        if cell.HasFormula:
            for w in wb.Worksheets:
                if w.Name == "Inputs":
                    w.Range(cell.Formula.split("!")[1].lstrip("=")).Value2 = new_value
        wb.Save()
    finally:
        wb.Close(True)
    row["linked_before"] = len(linked_before)
    expected = {t["text"]: format_like(parse_numbers(t["text"])[0], new_value if "trillion" not in t["text"] else new_value, "exact") for t in linked_before}
    try:
        found = svc.discover(pid)
        row["after_discover"] = {"need_confirmation": len(found["need_confirmation"]), "no_source": found["no_source"]}
        staged = svc.stage(pid)
        changes = staged["changes"]
        row["release_changes"] = len(changes)
        wrong = []
        for c in changes:
            if not any(c["old_text"] == t["text"] for t in linked_before):
                wrong.append({"changed": c["old_text"] + " -> " + c["new_text"], "where": c.get("where")})
        missed = [t["text"] for t in linked_before if not any(c["old_text"] == t["text"] for c in changes)]
        row.update(wrong_updates=wrong[:4], missed=missed[:4], held=len(staged.get("held", [])), status="ok" if not wrong and not missed else "FAILED")
    except ServiceError as exc:
        row.update(status="FAILED" if linked_before else "ok", why=f"release refused: {str(exc)[:140]}")
    return row


def main(fred: str, out: str) -> None:
    pythoncom.CoInitialize()
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    rows = []
    try:
        for name, op in OPS.items():
            try:
                r = run_one(xl, name, op, Path(fred))
            except Exception as exc:  # noqa: BLE001
                r = {"operation": name, "status": "harness_error", "why": f"{type(exc).__name__}: {str(exc)[:160]}"}
            rows.append(r)
            print(json.dumps(r), flush=True)
    finally:
        xl.Quit()
    Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps({"operations": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] == "FAILED" for r in rows), "harness_errors": sum(r["status"] == "harness_error" for r in rows)}))


if __name__ == "__main__":
    main(*sys.argv[1:3])
