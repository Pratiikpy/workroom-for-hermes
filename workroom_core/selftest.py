"""A self-test anyone can run from inside Hermes: `workroom_selftest` reruns a bundled, seeded battery and prints rates.

It is a SYNTHETIC battery: sentences are built from the same words as the source labels, so it measures formatting and
decoy robustness and the editing and release machinery, not language understanding. The numbers on real files are in
bench/EVIDENCE.md. Takes a few seconds, writes only to a temporary directory.
"""

from __future__ import annotations

import random
import shutil
import tempfile
from math import sqrt
from pathlib import Path
from typing import Any

from lxml import etree

from .controller.approvals import sign
from .controller.release import Controller
from .match.engine import Mention, SourceIndex, match_mentions
from .match.numbers import parse_numbers
from .ooxml.runs import DRAWING, EditError, find_all, replace_once
from .ooxml.xlsx import SourceCell

_METRICS = ["Revenue", "Costs", "Margin", "Headcount", "Churn", "Orders", "Refunds", "Pipeline", "Backlog", "Cash"]
_REGIONS = ["Europe", "Asia", "Americas", "Africa", "Oceania"]
_PERIODS = ["Q1", "Q2", "Q3", "Q4"]
_DECOYS = ["Tickets closed", "Offices opened", "Meetings held", "Pages written", "Calls made"]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _fmt(v: float, rnd: random.Random) -> str:
    if 0 < abs(v) < 1:
        return f"{v * 100:.{rnd.choice([0, 1])}f}%"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.0f}"


def _matching(seed: int, books: int) -> dict[str, Any]:
    rnd = random.Random(seed)
    acc_ok = acc_bad = decoys = decoy_acc = confirm = total = 0
    for b in range(books):
        cells = []
        n = 0
        for metric in rnd.sample(_METRICS, 5):
            for period in _PERIODS:
                n += 1
                v = rnd.choice([rnd.randint(10, 999), rnd.randint(1000, 90000), round(rnd.uniform(0.05, 0.95), 3)])
                cells.append(SourceCell("Sheet1", f"{chr(66 + _PERIODS.index(period))}{n}", n, 2, float(v), False, False, (metric,), (period,), False, f"book{b}.xlsx"))
        index = SourceIndex(cells)
        for cell in rnd.sample(cells, 12):
            shown = _fmt(cell.value, rnd)
            nm = parse_numbers(shown)
            if not nm:
                continue
            sentence = f"{cell.row_labels[0]} in {cell.col_labels[0]} was {shown}"
            pos = sentence.rfind(shown)
            total += 1
            r = match_mentions([Mention("t", nm[0], (sentence,), (pos, pos + len(shown)))], index)[0]
            if r.decision == "accept":
                ok = r.best.cell.ref == cell.ref
                acc_ok += ok
                acc_bad += not ok
            else:
                confirm += 1
            dec = f"{rnd.choice(_DECOYS)} reached {shown}"
            dpos = dec.rfind(shown)
            decoys += 1
            if match_mentions([Mention("t", nm[0], (dec,), (dpos, dpos + len(shown)))], index)[0].decision == "accept":
                decoy_acc += 1
    acc = acc_ok + acc_bad
    return {"sentences": total, "accepted": acc, "accepted_correct": acc_ok, "accepted_wrong": acc_bad,
            "accepted_precision_95ci": wilson(acc_ok, acc), "sent_to_a_human": confirm,
            "decoys": decoys, "decoys_accepted": decoy_acc, "decoy_false_accept_95ci": wilson(decoy_acc, decoys)}


def _editing(seed: int) -> dict[str, Any]:
    rnd = random.Random(seed)
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ok = bad = 0
    for _ in range(300):
        left, right = rnd.randint(10, 99), rnd.randint(10, 99)
        number = f"{rnd.randint(100, 999)}"
        cut = rnd.randint(1, len(number) - 1)
        runs = f'<a:r><a:rPr b="1"/><a:t>Total {left} and {number[:cut]}</a:t></a:r><a:r><a:rPr i="1"/><a:t>{number[cut:]} then {right}</a:t></a:r>'
        p = etree.fromstring(f'<a:p xmlns:a="{A}">{runs}</a:p>')
        new = str(rnd.randint(1000, 9999))
        try:
            hits = find_all(p, number, DRAWING)
            replace_once(p, number, new, DRAWING, occurrence=0 if len(hits) > 1 else None)
            text = "".join(t.text or "" for t in p.iter("{%s}t" % A))
            good = text == f"Total {left} and {new} then {right}" or (len(hits) > 1 and new in text)
        except EditError:
            good = False
        ok += good
        bad += not good
    return {"split_run_edits": ok + bad, "edits_correct": ok, "edits_wrong": bad}


def _release(tmp: Path) -> dict[str, Any]:
    key = b"s" * 32
    owner = "selftest:owner"

    class Crash(BaseException):
        pass

    points = [f"{p}:{i}" for i in range(3) for p in ("before_backup", "after_backup", "after_tmp_write", "before_replace", "after_replace")]
    recovered = 0
    for n_point, point in enumerate(points):
        proj, state = tmp / f"p{n_point}", tmp / f"s{n_point}"
        proj.mkdir(parents=True)
        files = {f"f{i}.txt": f"old {i}".encode() for i in range(3)}
        for n, d in files.items():
            (proj / n).write_bytes(d)

        def fp(name: str, point: str = point) -> None:
            if name == point:
                raise Crash(name)

        ctl = Controller(proj, state, key, frozenset({owner}), fp)
        rid = ctl.stage({n: f"new {n}".encode() for n in files})
        ctl.mark_verified(rid)
        ctl.record_approval(rid, sign(key, rid, ctl.digest(rid), owner, "selftest", 10**12, "n"), now=1.0)
        try:
            ctl.publish(rid, now=2.0)
        except Crash:
            pass
        ctl.journal.close()
        fresh = Controller(proj, state, key, frozenset({owner}))
        outcome = fresh.recover()
        fresh.journal.close()
        if outcome == {rid: "published"} and all((proj / n).read_bytes() == f"new {n}".encode() for n in files) and not list(proj.rglob("*.tmp")):
            recovered += 1
    return {"crash_points": len(points), "recovered_to_all_new": recovered}


def run(seed: int = 7, books: int = 40) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="workroom_selftest_"))
    try:
        result = {
            "kind": "SYNTHETIC battery; real-file results are in bench/EVIDENCE.md",
            "seed": seed,
            "matching": _matching(seed, books),
            "editing": _editing(seed),
            "release_recovery": _release(tmp),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    m, e, r = result["matching"], result["editing"], result["release_recovery"]
    result["passed"] = m["accepted_wrong"] == 0 and m["decoys_accepted"] == 0 and e["edits_wrong"] == 0 and r["recovered_to_all_new"] == r["crash_points"]
    return result
