"""Compare a later run with the adjudicated verdicts of an earlier blind run, figure by figure.

    python holdout_compare.py <old_result.json> <verdicts.json> <new_result.json>

Figures are matched by (figure text, paragraph text, nth occurrence). The reader's verdict fixes which cell is right (the first candidate, the
second, or a named cell); the table says what the new run now does with each judged figure.
"""

import collections
import json
import sys
from pathlib import Path


def keyed(rows):
    seen = collections.Counter()
    out = {}
    for r in rows:
        k = (r["figure"], (r["context"] or [""])[0])
        out[(k, seen[k])] = r
        seen[k] += 1
    return out


def short(cell: str) -> str:
    return cell.split(" ", 1)[1] if " " in cell else cell


def main() -> None:
    old = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    verdicts = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    new = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    old_k, new_k = keyed(old["rows"]), keyed(new["rows"])
    by_id = {r["i"]: key for key, r in old_k.items()}
    table = collections.Counter()
    bad = []
    for kind, items in verdicts.items():
        for v in items:
            key = by_id[v["id"]]
            o, n = old_k[key], new_k.get(key)
            right = None
            if v["verdict"] in ("correct", "candidate_correct"):
                right = short(o["best"]["cell"]) if o.get("best") else None
            elif v["verdict"] == "second_correct" and o.get("runner_up"):
                right = short(o["runner_up"]["cell"])
            elif v["verdict"] in ("other_cell_correct", "source_exists"):
                right = v.get("cell")
            if n is None:
                table[(kind, v["verdict"], "figure no longer read (e.g. the mark of $'000)")] += 1
                continue
            nd = n["decision"]
            got = short(n["best"]["cell"]) if n.get("best") else None
            if nd == "accept":
                if right is None:
                    outcome = "accept, but the reader found no source"
                    bad.append((kind, v["id"], v["verdict"], got))
                elif right.split("!")[-1] == got.split("!")[-1] and right.split("!")[0].split()[-1] == got.split("!")[0].split()[-1]:
                    outcome = "accept, right cell"
                else:
                    outcome = "accept, OTHER cell"
                    bad.append((kind, v["id"], v["verdict"], f"{got} (reader: {right})"))
            else:
                outcome = nd
            table[(kind, v["verdict"], outcome)] += 1
    for k, c in sorted(table.items()):
        print(c, k)
    print("to look at:", bad)


if __name__ == "__main__":
    main()
