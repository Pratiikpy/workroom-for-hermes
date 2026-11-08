"""Matcher benchmark on real chart decks: every chart point is a mention whose true source cell is known from the
chart's own cell reference, which the matcher is NOT given. Reports accepted-correct, accepted-wrong, confirm, none.

This corpus is favourable (labels come from the same workbook); it measures the matcher's floor, not its
performance on messy business documents.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stats import wilson  # noqa: E402

from workroom.workroom_core.match.engine import Mention, SourceIndex, match_mentions  # noqa: E402
from workroom.workroom_core.match.numbers import consistent_with_source, parse_numbers  # noqa: E402
from workroom.workroom_core.ooxml.package import open_package  # noqa: E402
from workroom.workroom_core.ooxml.pptx import C_NS, P_NS, Deck, _cell_for  # noqa: E402
from workroom.workroom_core.ooxml.xlsx import index_workbook, rels_for  # noqa: E402


def points(deck: Deck):
    for si, part in enumerate(deck.slide_parts(), 1):
        root = deck._root(part)
        for nv in root.iter("{%s}cNvPr" % P_NS):
            gf = nv.getparent().getparent()
            if gf.tag != "{%s}graphicFrame" % P_NS or gf.find(".//{%s}chart" % C_NS) is None:
                continue
            sid = int(nv.get("id"))
            try:
                cpart, _ = deck._chart_part(si, sid)
                xparts = [v[1] for v in rels_for(deck.pkg, cpart).values() if v[0] == "package"]
                series = deck.chart_series(si, sid)
            except Exception:
                continue
            if len(xparts) != 1:
                continue
            for s in series:
                for idx, val in enumerate(s.values):
                    if val is None or not s.val_formula:
                        continue
                    try:
                        truth = _cell_for(s.val_formula, idx)
                    except Exception:
                        continue
                    cat = s.categories[idx] if idx < len(s.categories) else ""
                    yield xparts[0], truth, val, s.name or "", cat


def main(folders: list[str]) -> int:
    stat = {"decks": 0, "points": 0, "chart_out_of_step_excluded": 0, "accept_correct": 0, "accept_wrong": 0, "confirm": 0, "confirm_has_truth": 0, "none": 0}
    for folder in folders:
        for path in sorted(Path(folder).glob("*.pptx")):
            try:
                deck = Deck(path.read_bytes())
                pts = list(points(deck))
            except Exception:
                continue
            if not pts:
                continue
            stat["decks"] += 1
            indexes: dict[str, SourceIndex] = {}
            for xpart, truth, val, sname, cat in pts:
                try:
                    if xpart not in indexes:
                        indexes[xpart] = SourceIndex(index_workbook(open_package(deck.pkg.read(xpart))))
                    ms = parse_numbers(repr(val))
                    if not ms:
                        continue
                    res = match_mentions([Mention("c", ms[0], (str(sname), str(cat)))], indexes[xpart])[0]
                except Exception:
                    continue
                truth_cell = next((c for c in indexes[xpart].cells if c.sheet == truth[0] and c.ref == truth[1]), None)
                if truth_cell is None or not consistent_with_source(ms[0], truth_cell.value)[0]:
                    stat["chart_out_of_step_excluded"] += 1  # the deck's own chart cache disagrees with its workbook
                    continue
                stat["points"] += 1
                if res.decision == "accept":
                    ok = res.best.cell.sheet == truth[0] and res.best.cell.ref == truth[1]
                    stat["accept_correct" if ok else "accept_wrong"] += 1
                elif res.decision == "confirm":
                    stat["confirm"] += 1
                    if any(c.cell.sheet == truth[0] and c.cell.ref == truth[1] for c in res.candidates):
                        stat["confirm_has_truth"] += 1
                else:
                    stat["none"] += 1
    acc = stat["accept_correct"] + stat["accept_wrong"]
    stat["accepted_precision_95ci"] = wilson(stat.get("accept_correct", stat.get("accepted_correct", 0)), acc)
    stat["accepted_precision"] = round(stat["accept_correct"] / acc, 4) if acc else None
    stat["coverage"] = round(acc / stat["points"], 4) if stat["points"] else None
    Path(__file__).with_name("match_bench_result.json").write_text(json.dumps(stat, indent=1), encoding="utf-8")
    print(json.dumps(stat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
