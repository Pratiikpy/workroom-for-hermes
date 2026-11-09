"""Three update cycles on a document someone else wrote, with a person editing it in the real Word between cycles.

    python foreign_cycles.py <out.json> <folder or .docx> [...] [--limit N]

Per document (the document is foreign; the workbook is built from its own figures, as in foreign_ties.py):
  cycle 1  five linked sources change; Workroom releases; the real Word shows exactly those figures updated;
  person   in the real Word: one linked figure is retyped to a value of the person's own; one sentence with a linked figure is reworded
           (a phrase is added in front of it); a new paragraph with a new figure is added; the file is saved by Word itself;
  cycle 2  the same sources change again, including the retyped figure's source: the retyped figure must stay as the person left it
           (held), the reworded sentence must still follow its source, the new paragraph must be untouched;
  person   the retyped figure is put back to what Workroom wrote;
  cycle 3  sources change again: every linked figure, the put-back one included, follows its source and nothing else changes.
After each step the text is read back from the real Word and compared with what the step should have produced.
"""

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import foreign_ties as ft  # noqa: E402
import pythoncom  # noqa: E402
import win32com.client  # noqa: E402
from foreign_edit import collect, norm  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from workroom.workroom_core.service import NeedsAcknowledgement, Service  # noqa: E402


def release(svc, pid) -> int:
    svc.discover(pid)
    staged = svc.stage(pid)
    try:
        svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=False)
    except NeedsAcknowledgement:
        svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
    return len(staged["changes"])


def word_paragraphs(word, path: Path) -> list[str]:
    doc = word.Documents.Open(str(path), False, True, False, "x", "x", True)
    try:
        out = []
        for sr in doc.StoryRanges:
            r = sr
            while r is not None:
                out.extend(norm(p) for p in re.split(r"[\r\x07]", r.Text or "") if norm(p))
                r = r.NextStoryRange
        return out
    finally:
        doc.Close(False)


def person_edits(word, path: Path, retype: dict, reword: dict, new_para: str) -> dict:
    """What a person does in the real Word, then saves. Returns what was done."""
    doc = word.Documents.Open(str(path), False, False, False, "x", "x", True)
    done = {"retyped": False, "reworded": False, "added": False}
    try:
        def in_paragraph(anchor: str, old: str, new: str, front: str | None = None) -> bool:
            rng = doc.Content
            f = rng.Find
            f.ClearFormatting()
            if not f.Execute(FindText=anchor[:200], MatchCase=True, Forward=True, Wrap=0):
                return False
            para = rng.Paragraphs(1).Range
            if front is not None:
                para.InsertBefore(front)
                return True
            inner = para.Duplicate
            g = inner.Find
            if not g.Execute(FindText=old, MatchCase=True, Forward=True, Wrap=0):
                return False
            inner.Text = new
            return True

        if retype:
            done["retyped"] = in_paragraph(retype["anchor"], retype["old"], retype["new"])
        if reword:
            done["reworded"] = in_paragraph(reword["anchor"], "", "", front=reword["front"])
        if new_para:
            doc.Content.InsertAfter("\r" + new_para)
            done["added"] = True
        doc.Save()
    finally:
        doc.Close(True)
    return done


def scale_token(raw: str, factor: float) -> str:
    """What a figure written as ``raw`` shows after its value is multiplied by ``factor``: same decimals, separators and affixes (independent of Workroom)."""
    m = ft.TOKEN.search(raw)
    if not m:
        return raw
    cur, num, tail = m.group(1), m.group(2), m.group(3) or ""
    d = len(num.split(".")[1]) if "." in num else 0
    v = (ft.Decimal(num.replace(",", "")) * ft.Decimal(str(factor))).quantize(ft.Decimal(1).scaleb(-d), rounding=ft.ROUND_HALF_UP)
    body = f"{v:,.{d}f}" if "," in num else f"{v:.{d}f}"
    return raw[: m.start()] + cur + body + tail + raw[m.end():]


def neighbours(token: str) -> list[str]:
    """The token itself and the figures one unit of its last digit away (rounding a rounded figure can differ by one)."""
    m = ft.TOKEN.search(token)
    if not m:
        return [token]
    num = m.group(2)
    d = len(num.split(".")[1]) if "." in num else 0
    v = ft.Decimal(num.replace(",", ""))
    out = []
    for k in (0, 1, -1):
        w = v + ft.Decimal(k) * ft.Decimal(1).scaleb(-d)
        body = f"{w:,.{d}f}" if "," in num else f"{w:.{d}f}"
        out.append(token[: m.start()] + m.group(1) + body + (m.group(3) or "") + token[m.end():])
    return out


def check_step(before: list[str], after: list[str], pairs: list[tuple[str, str]]) -> tuple[bool, str]:
    """Every paragraph that changed must carry one of the expected new figures, and every expected change must have happened."""
    from collections import Counter

    cb, ca = Counter(before), Counter(after)
    removed, added = list((cb - ca).elements()), list((ca - cb).elements())
    missing = [pair for pair in pairs if not any(any(n in a for n in neighbours(pair[1])) for a in added)]
    unexplained = [a for a in added if not any(any(n in a for n in neighbours(new)) for _, new in pairs)]
    if missing:
        return False, f"expected change missing: {missing[0][0]!r} -> {missing[0][1]!r}"
    if unexplained:
        gone = [r for r in removed if not any(n in r for _, n in pairs)]
        return False, f"an unexpected paragraph changed: {unexplained[0][:160]!r} (it was: {(gone[:1] or ['?'])[0][:160]!r}); pairs {pairs[:6]}"
    return True, f"{len(added)} paragraph(s) changed, all explained"


def run_doc(doc: Path, word) -> dict:
    row: dict = {"file": doc.name}
    try:
        paras = ft.paragraphs_of(doc)
    except Exception as exc:  # noqa: BLE001
        row.update(status="skipped", reason=f"independent reader: {type(exc).__name__}")
        return row
    seeds = ft.seeds_of(paras, 30)
    # a retyped and a reworded figure need distinct, plain, labelled seeds
    if len(seeds) < 10:
        row.update(status="skipped", reason=f"only {len(seeds)} usable figures")
        return row
    root, wbpath = ft.build_project(doc, seeds, "labelled")
    state = Path(tempfile.mkdtemp(prefix="fc_state_"))
    path = root / doc.name
    try:
        svc = Service(state)
        pid = svc.add_project(str(root))["project"]
        svc.discover(pid)
        ties = svc.ties(pid)
        cls = ft.classify(seeds, ties, doc.name, "labelled")
        def moves(sd) -> bool:
            """x1.1 changes the displayed figure three times running, so every cycle has something to release."""
            shown = [ft.new_token({**sd, "value": sd["value"] * float(ft.Decimal("1.1") ** k)}, factor=ft.Decimal("1")) for k in range(4)]
            return all(shown[k] != shown[k + 1] for k in range(3))

        right = [c for c in cls if c["result"] == "linked_right" and seeds[c["seed"]]["label"] and moves(seeds[c["seed"]])]
        if len(right) < 9:
            row.update(status="skipped", reason=f"only {len(right)} labelled links found")
            return row
        pick = [c["seed"] for c in right]
        wb = load_workbook(wbpath)
        ws = wb.active

        def bump(indices, factor):
            """Change the sources; return the figures that must change: every link that reads one of those cells."""
            refs = set()
            for i in indices:
                cell = ws.cell(row=i + 2, column=2)
                cell.value = cell.value * factor
                refs.add(cell.coordinate)
                seeds[i]["_now"] = float(ft.Decimal(repr(seeds[i]["_now"])) * ft.Decimal(str(factor)))
            wb.save(wbpath)
            svc.discover(pid)
            return [(t["text"], scale_token(t["text"], factor)) for t in svc.ties(pid) if t["state"] in ("accepted", "confirmed") and t["source"].split("!")[-1] in refs]

        for s in seeds:
            s["_now"] = s["value"]
        steps = {}
        # cycle 1
        group1 = pick[:5]
        before = word_paragraphs(word, path)
        shown_before = {i: ft.new_token({**seeds[i], "value": seeds[i]["_now"]}, factor=ft.Decimal("1")) for i in pick}
        e1 = bump(group1, 1.1)
        n1 = release(svc, pid)
        after = word_paragraphs(word, path)
        steps["cycle1"] = dict(zip(("ok", "note"), check_step(before, after, e1)), changes=n1)
        # the person edits in Word
        taken_paras = {seeds[j]["para"] for j in group1}
        rest = [i for i in pick[5:] if seeds[i]["para"] not in taken_paras]  # the person edits figures in paragraphs Workroom has not touched
        if len(rest) < 2 or seeds[rest[0]]["para"] == seeds[rest[1]]["para"]:
            row.update(status="skipped", reason="no two untouched paragraphs for the person's edits")
            return row
        retype_i, reword_i = rest[0], rest[1]
        s_r, s_w = seeds[retype_i], seeds[reword_i]
        shown_r = ft.new_token({**s_r, "value": s_r["_now"]}, factor=ft.Decimal("1"))
        mine = ft.new_token({**s_r, "value": s_r["_now"]}, factor=ft.Decimal("1.5"))
        did = person_edits(word, path, {"anchor": s_r["para"][:120], "old": shown_r, "new": mine}, {"anchor": s_w["para"][:120], "front": "Overall, "}, "Note added by hand: 123 units were reviewed.")
        steps["person"] = did
        if not (did["retyped"] and did["reworded"]):
            row.update(status="skipped", reason=f"the person's edit could not be made in Word ({did})", steps=steps)
            return row
        before = word_paragraphs(word, path)
        # cycle 2: all of group1, the retyped and the reworded sources change
        group2 = group1[:2] + [retype_i, reword_i]
        e2 = bump(group2, 1.1)
        n2 = release(svc, pid)
        after = word_paragraphs(word, path)
        ok, note = check_step(before, after, e2)  # the retyped figure is held, so no link to it is in the list
        kept_mine = any(mine in p for p in after)
        steps["cycle2"] = {"ok": ok and kept_mine, "note": note + ("; the retyped figure stayed as typed" if kept_mine else "; THE RETYPED FIGURE WAS OVERWRITTEN"), "changes": n2}
        # the person puts the figure back to what Workroom wrote (the source now says: _now)
        back = ft.new_token({**s_r, "value": s_r["_now"]}, factor=ft.Decimal("1"))
        person_edits(word, path, {"anchor": s_r["para"][:60].replace(shown_r, ""), "old": mine, "new": back}, {}, "")
        before = word_paragraphs(word, path)
        group3 = group1[2:5] + [retype_i]
        e3 = bump(group3, 1.1)
        n3 = release(svc, pid)
        after = word_paragraphs(word, path)
        ok, note = check_step(before, after, e3)
        steps["cycle3"] = {"ok": ok, "note": note, "changes": n3}
        row.update(status="ok" if all(v.get("ok", True) for v in steps.values()) else "FAILED", steps=steps)
    except Exception as exc:  # noqa: BLE001
        row.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--limit", type=int, default=10_000)
    ns = ap.parse_args()
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = 3
    rows = []
    try:
        for i, f in enumerate(collect(ns.targets, (".docx",))[: ns.limit], 1):
            r = run_doc(f, word)
            rows.append(r)
            print(i, f.name[:44], r["status"], r.get("reason", r.get("error", "")), {k: v.get("ok") for k, v in r.get("steps", {}).items() if isinstance(v, dict) and "ok" in v}, flush=True)
            Path(ns.out).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    finally:
        word.Quit()
    summary = {"documents": len(rows), "ok": sum(r["status"] == "ok" for r in rows), "failed": sum(r["status"] == "FAILED" for r in rows), "errors": sum(r["status"] == "error" for r in rows), "skipped": sum(r["status"] == "skipped" for r in rows)}
    print(json.dumps(summary))
    Path(ns.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
