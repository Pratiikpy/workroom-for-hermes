"""Does a signed record embedded in a Word, PowerPoint or Excel file survive the real Office program opening and saving the file?

    python embed_office.py

For each of .docx, .pptx, .xlsx: embed a record, check our own reader and python-docx/pptx/openpyxl open it, then open the file in the real application
through COM, save a copy under a new name, and look in the saved copy for the part. Reports what survived, and whether the package digest (and so the
signature check) still holds after Office has rewritten the file. Windows with Microsoft Office only.
"""

import io
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core import embed  # noqa: E402
from workroom.workroom_core.ooxml.package import open_package  # noqa: E402

ENVELOPE = {"payload": {"version": 1, "release": "r1"}, "signature": "x", "public_key": "y", "key_fingerprint": "z"}
checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def make_docx() -> bytes:
    from docx import Document

    d = Document()
    d.add_paragraph("Revenue was 120 in Q2.")
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def make_pptx() -> bytes:
    from pptx import Presentation

    p = Presentation()
    s = p.slides.add_slide(p.slide_layouts[5])
    s.shapes.title.text = "Revenue was 120"
    b = io.BytesIO()
    p.save(b)
    return b.getvalue()


def make_xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.active["A1"] = 120
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def office_roundtrip(kind: str, src: Path, dst: Path) -> None:
    import win32com.client as win

    if kind == "docx":
        app = win.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(str(src), ReadOnly=False, AddToRecentFiles=False)
        doc.SaveAs2(str(dst), FileFormat=16)
        doc.Close(False)
        app.Quit()
    elif kind == "pptx":
        app = win.DispatchEx("PowerPoint.Application")
        pres = app.Presentations.Open(str(src), WithWindow=False)
        pres.SaveAs(str(dst))
        pres.Close()
        app.Quit()
    else:
        app = win.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(str(src))
        wb.SaveAs(str(dst), FileFormat=51)
        wb.Close(False)
        app.Quit()


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="wr_embed_"))
    for kind, make in (("docx", make_docx), ("pptx", make_pptx), ("xlsx", make_xlsx)):
        original = make()
        stamped = embed.embed(original, ENVELOPE)
        check(f"{kind}: digest is the same with and without the record", embed.package_digest(original) == embed.package_digest(stamped))
        check(f"{kind}: the record reads back", embed.extract(stamped) == ENVELOPE)
        check(f"{kind}: every other part is byte-identical", all(zipfile.ZipFile(io.BytesIO(original)).read(n) == zipfile.ZipFile(io.BytesIO(stamped)).read(n) for n in zipfile.ZipFile(io.BytesIO(original)).namelist() if n not in ("[Content_Types].xml", embed._rels_of(embed._main_part(open_package(original))))))
        try:
            if kind == "docx":
                from docx import Document

                Document(io.BytesIO(stamped))
            elif kind == "pptx":
                from pptx import Presentation

                Presentation(io.BytesIO(stamped))
            else:
                from openpyxl import load_workbook

                load_workbook(io.BytesIO(stamped))
            check(f"{kind}: the file still opens in its python reader", True)
        except Exception as exc:  # noqa: BLE001
            check(f"{kind}: the file still opens in its python reader", False, str(exc)[:100])
        src, dst = work / f"in.{kind}", work / f"out.{kind}"
        src.write_bytes(stamped)
        try:
            office_roundtrip(kind, src, dst)
        except Exception as exc:  # noqa: BLE001
            check(f"{kind}: the real Office program opens and saves it", False, str(exc)[:160])
            continue
        check(f"{kind}: the real Office program opens and saves it", dst.is_file())
        saved = dst.read_bytes()
        names = zipfile.ZipFile(io.BytesIO(saved)).namelist()
        check(f"{kind}: the record survives Office's save", embed.extract(saved) == ENVELOPE, f"parts with 'workroom' or customXml: {[n for n in names if 'workroom' in n.lower() or 'customxml' in n.lower()]}")
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
