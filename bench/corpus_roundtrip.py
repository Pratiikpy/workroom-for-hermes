"""Round-trip every package in a folder through the kernel and report what happened.

Checks per file: opens or is refused with a reason; rewriting with no edits is byte-identical; rewriting with
one entry replaced by its own content leaves every other entry's compressed bytes identical and the result
passes zipfile's CRC test.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.workroom_core.ooxml.package import PackageError, open_package, raw_unchanged, rewrite  # noqa: E402


def main(folder: str) -> int:
    rows = []
    for path in sorted(Path(folder).glob("*.[px][pl][ts]x")) + sorted(Path(folder).glob("*.docx")):
        data = path.read_bytes()
        row = {"file": path.name, "size": len(data)}
        try:
            pkg = open_package(data)
        except PackageError as exc:
            row.update(status="refused", reason=str(exc))
            rows.append(row)
            continue
        row["entries"] = len(pkg.entries)
        row["identity"] = rewrite(pkg, {}) == data
        target = next((n for n in pkg.names() if n.endswith(".xml") and not n.startswith("[")), None)
        if target:
            out = rewrite(pkg, {target: pkg.read(target)})
            after = open_package(out)
            others = [n for n in pkg.names() if n != target]
            row["others_raw_identical"] = raw_unchanged(pkg, after, others) == others
            row["zip_ok"] = zipfile.ZipFile(io.BytesIO(out)).testzip() is None
        row["status"] = "ok"
        rows.append(row)
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {
        "files": len(rows),
        "opened": len(ok),
        "refused": len(rows) - len(ok),
        "identity_pass": sum(1 for r in ok if r["identity"]),
        "others_identical_pass": sum(1 for r in ok if r.get("others_raw_identical")),
        "zip_ok_pass": sum(1 for r in ok if r.get("zip_ok")),
    }
    Path(__file__).with_name("corpus_roundtrip_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    for r in rows:
        if r["status"] != "ok" or not (r["identity"] and r.get("others_raw_identical", True) and r.get("zip_ok", True)):
            print("ATTENTION", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
