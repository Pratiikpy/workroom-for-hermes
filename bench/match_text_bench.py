"""Synthetic text-mention benchmark for the matcher, built from the embedded workbooks of real chart decks.

For sampled numeric cells with row/column labels, sentences are generated from the labels in several phrasings
(full labels, row label only, column label only, no label) and number formats (rounding, separators, percent, scale
words). Decoy sentences reuse a real value with unrelated wording. This measures formatting and decoy robustness and
the abstention profile; it is OPTIMISTIC about language because sentences are built from the workbook's own words.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stats import wilson  # noqa: E402

from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions  # noqa: E402
from workroom.workroom_core.match.numbers import parse_numbers  # noqa: E402
from workroom.workroom_core.ooxml.package import open_package  # noqa: E402
from workroom.workroom_core.ooxml.pptx import Deck  # noqa: E402
from workroom.workroom_core.ooxml.xlsx import index_workbook, rels_for  # noqa: E402

DECOY_WORDS = ["Headcount", "Offices", "Customers called", "Tickets closed", "Meetings held", "Pages published"]


def fmt(v: float, rnd: random.Random) -> str:
    if 0 < abs(v) < 1 and rnd.random() < 0.8:
        return f"{v * 100:.{rnd.choice([0, 1])}f}%"
    if abs(v) >= 1_000_000 and rnd.random() < 0.5:
        return f"${v / 1e6:.1f} million"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.{rnd.choice([0, 1, 2])}f}" if v != int(v) else f"{int(v)}"


def main(folders: list[str], per_book: int = 12) -> int:
    rnd = random.Random(7)
    stat = {"books": 0, "true_mentions": 0, "accepted_correct": 0, "accepted_wrong": 0, "confirm": 0, "none": 0,
            "decoys": 0, "decoy_accepted": 0, "by_phrasing": {}}
    for folder in folders:
        for path in sorted(Path(folder).glob("*.pptx")):
            try:
                deck = Deck(path.read_bytes())
            except Exception:
                continue
            for part in deck.pkg.names():
                if not part.startswith("ppt/embeddings/") or not part.endswith(".xlsx"):
                    continue
                try:
                    cells = [c for c in index_workbook(open_package(deck.pkg.read(part)), file=part) if c.row_labels and c.col_labels and not c.is_date and abs(c.value) > 0]
                    index = SourceIndex(cells)
                except Exception:
                    continue
                if len(index.cells) < 4:
                    continue
                stat["books"] += 1
                sample = rnd.sample(index.cells, min(per_book, len(index.cells)))
                for cell in sample:
                    shown = fmt(cell.value, rnd)
                    nm = parse_numbers(shown)
                    if not nm:
                        continue
                    row, col = cell.row_labels[0], cell.col_labels[0]
                    for phr, sentence in (("full", f"{row} for {col} was {shown}"), ("row-only", f"{row} was {shown}"),
                                          ("col-only", f"In {col} it was {shown}"), ("none", f"The figure was {shown}")):
                        pos = sentence.rfind(shown)
                        res = match_mentions([Mention("t", nm[0], (sentence,), (pos, pos + len(shown)))], index)[0]
                        b = stat["by_phrasing"].setdefault(phr, {"n": 0, "accept_ok": 0, "accept_wrong": 0, "confirm": 0, "none": 0})
                        b["n"] += 1
                        stat["true_mentions"] += 1
                        if res.decision == "accept":
                            ok = (res.best.cell.sheet, res.best.cell.ref) == (cell.sheet, cell.ref) or res.best.cell.value == cell.value and set(res.best.cell.row_labels) == set(cell.row_labels) and set(res.best.cell.col_labels) == set(cell.col_labels)
                            key = "accept_ok" if ok else "accept_wrong"
                            b[key] += 1
                            stat["accepted_correct" if ok else "accepted_wrong"] += 1
                        elif res.decision == "confirm":
                            b["confirm"] += 1
                            stat["confirm"] += 1
                        else:
                            b["none"] += 1
                            stat["none"] += 1
                    decoy = f"{rnd.choice(DECOY_WORDS)} reached {shown}"
                    pos = decoy.rfind(shown)
                    res = match_mentions([Mention("t", nm[0], (decoy,), (pos, pos + len(shown)))], index)[0]
                    stat["decoys"] += 1
                    if res.decision == "accept":
                        stat["decoy_accepted"] += 1
    acc = stat["accepted_correct"] + stat["accepted_wrong"]
    stat["accepted_precision_95ci"] = wilson(stat.get("accept_correct", stat.get("accepted_correct", 0)), acc)
    stat["accepted_precision"] = round(stat["accepted_correct"] / acc, 4) if acc else None
    stat["accept_rate_on_true_mentions"] = round(acc / stat["true_mentions"], 4) if stat["true_mentions"] else None
    stat["decoy_false_accept_rate"] = round(stat["decoy_accepted"] / stat["decoys"], 4) if stat["decoys"] else None
    Path(__file__).with_name("match_text_bench_result.json").write_text(json.dumps(stat, indent=1), encoding="utf-8")
    print(json.dumps(stat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
