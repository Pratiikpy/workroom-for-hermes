"""Matching under paraphrase: sentences do not repeat the source label verbatim. Reports accept/ask/wrong with Wilson CIs.

SYNTHETIC: templates written by hand, so this is a stress proxy for messy prose, not a measurement on real business files.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions  # noqa: E402
from workroom.workroom_core.match.numbers import parse_numbers  # noqa: E402
from workroom.workroom_core.ooxml.xlsx import SourceCell  # noqa: E402
from workroom.workroom_core.selftest import wilson  # noqa: E402

LABELS = ["Revenue", "Operating costs", "Gross margin", "Headcount", "Customer churn", "Orders shipped", "Cash balance", "Backlog"]
PARAPHRASE = {
    "Revenue": ["sales", "top line", "turnover"], "Operating costs": ["opex", "running costs", "spend"],
    "Gross margin": ["margin", "gross profit rate"], "Headcount": ["staff", "people on payroll", "employees"],
    "Customer churn": ["attrition", "customers lost", "churn"], "Orders shipped": ["shipments", "orders out the door"],
    "Cash balance": ["cash", "cash on hand"], "Backlog": ["open orders", "unfilled demand"],
}
PERIODS = ["Q1", "Q2", "Q3", "Q4"]
TEMPLATES = ["{p}: {l} came in at {v}", "We closed {p} with {l} of {v}", "{l} ({p}) {v}", "In {p}, {l} stood at {v}, a clear step up", "{v} {l} for {p}"]
DECOY = ["The board approved a budget of {v} for the offsite", "Page {v} of the appendix", "Room {v} is booked for the review"]


def main(seed: int = 11, books: int = 60) -> None:
    rnd = random.Random(seed)
    ok = bad = ask = d_acc = d_n = 0
    for _ in range(books):
        cells, n = [], 0
        for label in LABELS:
            for per in PERIODS:
                n += 1
                v = float(rnd.choice([rnd.randint(100, 900), rnd.randint(1000, 90000)]))
                cells.append(SourceCell("S", f"B{n}", n, 2, v, False, False, (label,), (per,), False, "b.xlsx"))
        idx = SourceIndex(cells)
        for c in rnd.sample(cells, 16):
            shown = f"{int(c.value):,}"
            word = rnd.choice(PARAPHRASE[c.row_labels[0]])
            s = rnd.choice(TEMPLATES).format(p=c.col_labels[0], l=word, v=shown)
            pos = s.rfind(shown)
            nm = parse_numbers(shown)[0]
            r = match_mentions([Mention("t", nm, (s,), (pos, pos + len(shown)))], idx)[0]
            if r.decision == "accept":
                ok += r.best.cell.ref == c.ref
                bad += r.best.cell.ref != c.ref
            else:
                ask += 1
            d = rnd.choice(DECOY).format(v=shown)
            d_n += 1
            d_acc += match_mentions([Mention("t", nm, (d,), (d.rfind(shown), d.rfind(shown) + len(shown)))], idx)[0].decision == "accept"
    total = ok + bad + ask
    out = {"kind": "SYNTHETIC paraphrase stress", "seed": seed, "sentences": total, "accepted_correct": ok, "accepted_wrong": bad,
           "sent_to_a_human": ask, "accepted_precision_95ci": wilson(ok, ok + bad), "share_resolved_automatically": round((ok + bad) / total, 3),
           "decoys": d_n, "decoys_accepted": d_acc, "decoy_false_accept_95ci": wilson(d_acc, d_n)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
