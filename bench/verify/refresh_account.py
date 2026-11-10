"""Account for every figure that differs between two published years: what Workroom did with it and why.

Each figure the department's two published reports give differently (under the section, row and column-group key of ``oracle_groups``) is classified by
what the refreshed copy now shows and by what the roll recorded for the tied figure (a coded reason per tie). Writes a readable table and the rows.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from oracle_groups import _norm


def build_account(ties: list[dict], before: dict, after: dict, official: dict, out_dir: Path) -> None:
    by_text: dict[tuple, list[dict]] = collections.defaultdict(list)
    for t in sorted(ties, key=lambda x: (x["table"], x["cell"][0] if x["cell"] else 0, x["cell"][1] if x["cell"] else 0)):
        by_text[(_norm(t["row_head"]), t["raw"].strip())].append(t)
    taken: collections.Counter = collections.Counter()
    rows = []
    for k in sorted(k for k in before if k in official and before[k] != official[k]):
        b, a, o = before[k], after.get(k), official[k]
        cand = by_text.get((k[2], b.strip()), [])
        tie = cand[taken[(k[2], b.strip())]] if taken[(k[2], b.strip())] < len(cand) else None
        taken[(k[2], b.strip())] += 1
        if a == o:
            cls, why = "updated to the published figure", ""
        elif a != b:
            cls, why = "changed, differs from the published figure", (tie["why"][0] if tie else "")
        elif tie is None:
            cls, why = "left as last year: no link to this figure", ""
        elif tie["state"] in ("confirm", "skipped"):
            cls, why = "left as last year: link never confirmed", tie["state"]
        elif tie["why"][0]:
            cls, why = "left as last year: " + tie["why"][0].replace("_", " "), tie["why"][0]
        else:
            cls, why = "left as last year: linked, no reason recorded", tie["state"]
        rows.append({"section": k[0], "table": k[1], "row": k[2], "column": k[3], "n": k[4], "last_year": b, "copy_now": a, "published": o, "class": cls, "reason": why})
    counts = collections.Counter(r["class"] for r in rows)
    (out_dir / "refresh_account.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Account of every figure that differs between the two published years", "", f"{len(rows)} figures, classified by what the refreshed copy shows and why.", "", "| class | figures |", "|---|---|"]
    lines += [f"| {c} | {n} |" for c, n in counts.most_common()]
    by_section = collections.defaultdict(collections.Counter)
    for r in rows:
        by_section[r["section"]][r["class"]] += 1
    lines += ["", "## By section (largest first; the three biggest classes)", ""]
    for sec, c in sorted(by_section.items(), key=lambda x: -sum(x[1].values()))[:25]:
        lines.append(f"- {sec}: {sum(c.values())} figures; " + "; ".join(f"{n} {name}" for name, n in c.most_common(3)))
    (out_dir / "refresh_account.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
