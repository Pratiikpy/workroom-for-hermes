"""Build the adjudication packets for one holdout result: the sampled figures (without the matcher's reasons or scores) and a flat dump of every source cell.

    python holdout_packets.py <result.json> <out_dir> <report> <workbook.xlsx> [...]
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core.service import Service  # noqa: E402


def main() -> None:
    result = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    report, books = Path(sys.argv[3]), [Path(p) for p in sys.argv[4:]]
    tmp = Path(tempfile.mkdtemp(prefix="packets_"))
    root = tmp / "project"
    root.mkdir()
    for p in [report, *books]:
        shutil.copy2(p, root / p.name)
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    proj, _ = svc._open(pid)
    with (out / "source_cells.tsv").open("w", encoding="utf-8") as f:
        f.write("file\tsheet\tcell\tvalue\trow_headings\tcolumn_headings\n")
        for c in proj.source_index().cells:
            f.write(f"{c.file}\t{c.sheet}\t{c.ref}\t{c.value}\t{' | '.join(c.row_labels)}\t{' | '.join(c.col_labels)}\n".replace("\n\t", " ").replace("\r", " "))
    rows = {r["i"]: r for r in result["rows"]}
    packets = {}
    for kind, ids in result["sample_ids"].items():
        items = []
        for i in ids:
            r = rows[i]
            item = {"id": i, "figure": r["figure"], "words_around_it": r["context"], "table_row_heading": r["row_head"], "table_column_heading": r["col_head"]}
            if r["best"]:
                item["candidate"] = {k: r["best"][k] for k in ("cell", "value", "row", "col")}
            if kind == "confirm" and r["runner_up"]:
                item["second_candidate"] = r["runner_up"]
            items.append(item)
        packets[kind] = items
    for kind, items in packets.items():
        (out / f"{kind}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print({k: len(v) for k, v in packets.items()})


if __name__ == "__main__":
    main()
