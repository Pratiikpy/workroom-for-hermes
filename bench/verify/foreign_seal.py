"""Split a public corpus into a development half and a sealed held-out half by file hash, before any result is read.

    python foreign_seal.py <corpus folder> <out seal.json> <git commit of the corpus>

A file belongs to the sealed half when the last hex digit of its SHA-1 is 8 to f. Fixes are made and judged on the development half only;
the sealed half is run once, after the last fix, and every row of its result carries the seal's own hash. The seal is a list of hashes: the
files are public (Apache POI test data) and are not stored in the repository.
"""

import hashlib
import json
import sys
from pathlib import Path


def main(folder: str, out: str, commit: str = "") -> None:
    rows = []
    for f in sorted(Path(folder).rglob("*")):
        if f.suffix.lower() in (".docx", ".pptx", ".xlsx", ".xlsm") and f.is_file() and f.stat().st_size:
            h = hashlib.sha1(f.read_bytes()).hexdigest()
            rows.append({"file": f.relative_to(folder).as_posix(), "sha1": h, "set": "sealed" if int(h[-1], 16) >= 8 else "dev"})
    body = {"rule": "last hex digit of the SHA-1 is 8 to f -> sealed, otherwise dev", "source": "apache/poi test-data/{document,spreadsheet,slideshow} at commit " + commit + " (cloned 2026-11-09)", "files": rows}
    blob = json.dumps(body, sort_keys=True).encode()
    body["seal_sha256"] = hashlib.sha256(blob).hexdigest()
    Path(out).write_text(json.dumps(body, indent=1), encoding="utf-8")
    print(len(rows), "files:", sum(r["set"] == "sealed" for r in rows), "sealed;", body["seal_sha256"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
