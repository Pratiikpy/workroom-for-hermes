"""Edit one real number in every Word file of a folder and verify nothing else moved (independent reader: python-docx)."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from docx import Document  # noqa: E402

from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402
from workroom.workroom_core.ooxml.package import PackageError, open_package, raw_unchanged  # noqa: E402


def snapshot(data: bytes) -> list[str]:
    """Independent reader: every w:p of the main document, its w:t texts joined (deleted text excluded)."""
    import re as _re
    from lxml import etree as _et

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    pkg = open_package(data)
    out = []
    for name in ["word/document.xml"] + sorted(n for n in pkg.names() if _re.fullmatch(r"word/(header\d*|footer\d*|footnotes|endnotes)\.xml", n)):
        root = _et.fromstring(pkg.read(name))
        for p in root.iter(W + "p"):
            out.append("".join(t.text or "" for t in p.iter(W + "t") if next(t.iterancestors(W + "p")) is p))
    return out


def main(folder: str) -> int:
    rows = []
    for path in sorted(Path(folder).glob("*.docx")):
        data = path.read_bytes()
        row = {"file": path.name}
        try:
            pkg = open_package(data)
            identity = None
            doc = Doc(data)
            ms = list(doc.mentions())
        except Exception as exc:  # noqa: BLE001
            row.update(status="skipped", reason=f"{type(exc).__name__}: {str(exc)[:70]}")
            rows.append(row)
            continue
        if not ms:
            row.update(status="skipped", reason="no numbers")
            rows.append(row)
            continue
        m = ms[0]
        marker = m.number.raw + "QQ"
        try:
            before = snapshot(data)
            doc.edit_mention(m, marker)
            out, report = doc.serialize()
            after = snapshot(out)
        except Exception as exc:  # noqa: BLE001
            row.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:100]}")
            rows.append(row)
            continue
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        b_pkg, a_pkg = open_package(data), open_package(out)
        others = [n for n in b_pkg.names() if n not in report.parts_changed]
        ok = len(before) == len(after) and len(changed) == 1 and marker in changed[0][1] and raw_unchanged(b_pkg, a_pkg, others) == others and len(report.parts_changed) == 1
        identity_ok = Doc(data).serialize()[0] == data
        row.update(status="ok" if ok and identity_ok else "FAILED", changed=len(changed), identity=identity_ok)
        rows.append(row)
    ok = sum(1 for r in rows if r["status"] == "ok")
    summary = {"docs": len(rows), "ok": ok, "failed": sum(1 for r in rows if r["status"] in ("FAILED", "failed")), "skipped": sum(1 for r in rows if r["status"] == "skipped")}
    Path(__file__).with_name("corpus_edit_docx_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    for r in rows:
        if r["status"] in ("FAILED", "failed"):
            print("FAIL", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
