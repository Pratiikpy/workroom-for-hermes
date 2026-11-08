"""Edit one numeric constant in every real workbook embedded in a folder of decks; verify with openpyxl (independent)."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from openpyxl import load_workbook  # noqa: E402

from workroom.workroom_core.ooxml.book import Book  # noqa: E402
from workroom.workroom_core.ooxml.package import PackageError, open_package, raw_unchanged  # noqa: E402


def cells(data: bytes) -> dict:
    wb = load_workbook(io.BytesIO(data))  # formulas as written, not cached values
    return {(ws.title, c.coordinate): c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None}


def main(folders: list[str]) -> int:
    rows = []
    for folder in folders:
        for path in sorted(Path(folder).glob("*.pptx")):
            try:
                deck = open_package(path.read_bytes())
            except PackageError:
                continue
            for part in deck.names():
                if not (part.startswith("ppt/embeddings/") and part.endswith(".xlsx")):
                    continue
                data = deck.read(part)
                row = {"file": f"{path.name}:{part.split('/')[-1]}"}
                try:
                    book = Book(data)
                    ms = list(book.mentions())
                except Exception as exc:  # noqa: BLE001
                    row.update(status="skipped", reason=f"{type(exc).__name__}: {str(exc)[:60]}")
                    rows.append(row)
                    continue
                if not ms:
                    row.update(status="skipped", reason="no numeric constants")
                    rows.append(row)
                    continue
                m = ms[0]
                new_val = m.number.value + 7
                try:
                    before = cells(data)
                    book.edit_mention(m, repr(new_val))
                    out, report = book.serialize()
                    after = cells(out)
                except Exception as exc:  # noqa: BLE001
                    row.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:100]}")
                    rows.append(row)
                    continue
                diff = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
                b_pkg, a_pkg = open_package(data), open_package(out)
                others = [n for n in b_pkg.names() if n not in report.parts_changed]
                ok = len(diff) == 1 and abs(float(after[diff[0]]) - new_val) < 1e-9 and raw_unchanged(b_pkg, a_pkg, others) == others
                identity = Book(data).serialize()[0] == data
                row.update(status="ok" if ok and identity else "FAILED", cells_changed=len(diff), identity=identity)
                rows.append(row)
    ok = sum(1 for r in rows if r["status"] == "ok")
    summary = {"workbooks": len(rows), "ok": ok, "failed": sum(1 for r in rows if r["status"] in ("FAILED", "failed")), "skipped": sum(1 for r in rows if r["status"] == "skipped")}
    Path(__file__).with_name("corpus_edit_xlsx_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    for r in rows:
        if r["status"] in ("FAILED", "failed"):
            print("FAIL", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
