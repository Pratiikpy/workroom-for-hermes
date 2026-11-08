"""Tracked-change edits on every real Word file: accept-all and reject-all must give the right text, OfficeCLI must validate."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from docx import Document  # noqa: E402
from lxml import etree  # noqa: E402

from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402
from workroom.workroom_core.ooxml.package import PackageError  # noqa: E402
from workroom.workroom_core.ooxml.runs import EditError  # noqa: E402

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
q = lambda t: "{%s}%s" % (W, t)
OFFICECLI = Path(os.environ["OFFICECLI"])  # path to the OfficeCLI executable


def paragraph_views(xml: bytes) -> list[tuple[str, str]]:
    root = etree.fromstring(xml)
    views = []
    for p in root.iter(q("p")):
        acc, rej = [], []
        for el in p.iter():
            in_del = any(a.tag == q("del") for a in el.iterancestors())
            in_ins = any(a.tag == q("ins") for a in el.iterancestors())
            if el.tag == q("t"):
                if not in_del:
                    acc.append(el.text or "")
                if not in_ins:
                    rej.append(el.text or "")
            elif el.tag == q("delText"):
                rej.append(el.text or "")
        views.append(("".join(acc), "".join(rej)))
    return views


def officecli_errors(path: Path) -> int:
    """Number of validation errors OfficeCLI reports (0 means it passed)."""
    subprocess.run([str(OFFICECLI), "close", str(path)], capture_output=True)
    r = subprocess.run([str(OFFICECLI), "validate", str(path)], capture_output=True, text=True)
    subprocess.run([str(OFFICECLI), "close", str(path)], capture_output=True)
    m = re.search(r"Found (\d+) validation error", r.stdout + r.stderr)
    return int(m.group(1)) if m else (0 if r.returncode == 0 else 999)


def errors_of(data: bytes, name: str) -> int:
    td = tempfile.mkdtemp()
    tp = Path(td) / name
    tp.write_bytes(data)
    n = officecli_errors(tp)
    shutil.rmtree(td, ignore_errors=True)
    return n


def main(folder: str) -> None:
    rows = []
    for path in sorted(Path(folder).glob("*.docx")):
        data = path.read_bytes()
        row = {"file": path.name}
        try:
            doc = Doc(data)
            ms = [m for m in doc.mentions() if m.slide == 1 and m.number.raw.isdigit() and len(m.number.raw) >= 2]
        except (EditError, PackageError, KeyError) as exc:
            row.update(status="skipped", reason=type(exc).__name__)
            rows.append(row)
            continue
        if not ms:
            row.update(status="skipped", reason="no numbers")
            rows.append(row)
            continue
        m = ms[0]
        new = str(int(m.number.raw) + 7)
        try:
            doc.tracked = True
            doc.edit_mention(m, new)
            out, report = doc.serialize()
            before = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
            after = zipfile.ZipFile(io.BytesIO(out)).read("word/document.xml")
            vb, va = paragraph_views(before), paragraph_views(after)
            reject_same = [r for _, r in va] == [a for a, _ in vb]
            changed = [i for i, ((a0, _), (a1, _)) in enumerate(zip(vb, va)) if a0 != a1]
            accept_ok = len(changed) == 1 and new in va[changed[0]][0] and va[changed[0]][0].replace(new, m.number.raw, 1) == vb[changed[0]][0]
            Document(io.BytesIO(out))
            e_before, e_after = errors_of(data, path.name), errors_of(out, path.name)
            validated = e_after <= e_before
            row.update(status="ok" if (reject_same and accept_ok and validated) else "FAILED", reject_restores_original=reject_same,
                       accept_has_only_the_change=accept_ok, officecli_errors_before=e_before, officecli_errors_after=e_after, officecli_no_new_errors=validated, parts_changed=list(report.parts_changed))
        except Exception as exc:  # noqa: BLE001
            row.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:100]}")
        rows.append(row)
    summary = {"docs": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] in ("FAILED", "failed") for r in rows),
               "skipped": sum(r["status"] == "skipped" for r in rows)}
    Path(__file__).with_name("corpus_edit_docx_tracked_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    for r in rows:
        if r["status"] in ("FAILED", "failed"):
            print("FAIL", {k: r[k] for k in r if k != "parts_changed"})


if __name__ == "__main__":
    main(sys.argv[1])
