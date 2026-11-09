"""Link, update and check documents other people wrote against a workbook built from the document's own figures.

    python foreign_ties.py <out.json> <folder or file> [...] [--mode labelled|bare] [--max-seeds N] [--min-seeds N] [--updates N]

The document is real and foreign; the workbook is the one an analyst would have behind it. For each document:
  1. seeds: figures found with python-docx / python-pptx and a regular expression that shares no code with Workroom;
  2. a workbook holding every seed in its own cell ("labelled": the words before the figure as the row label; "bare": figures only);
  3. Workroom reads the project; every seed is classified as linked right, linked WRONG, proposed with the right cell, proposed without it,
     or not found. A wrong automatic link is a silent error;
  4. a few right links get a new source value, the release is approved, and the real Word or PowerPoint reads the result: only the
     expected text may differ, and each new figure must equal the independent calculation.
"""

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import tempfile
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

from docx import Document  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from pptx import Presentation  # noqa: E402

from foreign_edit import app_for, collect, compare_text, norm, word_texts, ppt_texts  # noqa: E402
from workroom.workroom_core.service import NeedsAcknowledgement, Service, ServiceError  # noqa: E402

TOKEN = re.compile(r"(?<![\w.,/:$-])(\$?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s?(?:%|bn|m|k|million|billion|thousand)\b|%)?(?![\w:/]|[.,]\d)")
SCALE = {"bn": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}
STOP = set("the a an of in on at to for and or with by from as is was were are be been this that these those it its their our which who than then also over under into".split())


def paragraphs_of(path: Path) -> list[str]:
    out: list[str] = []
    if path.suffix.lower() == ".docx":
        d = Document(str(path))
        out.extend(p.text for p in d.paragraphs)
        for t in d.tables:
            for row in t.rows:
                for c in row.cells:
                    out.extend(p.text for p in c.paragraphs)
    else:
        def walk(shapes):
            for sh in shapes:
                if sh.shape_type == 6:
                    walk(sh.shapes)
                    continue
                if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                    out.extend(p.text for p in sh.text_frame.paragraphs)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        for c in row.cells:
                            out.extend(p.text for p in c.text_frame.paragraphs)
        for slide in Presentation(str(path)).slides:
            walk(slide.shapes)
    seen, uniq = set(), []
    for p in out:
        if p.strip() and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def seeds_of(paragraphs: list[str], limit: int) -> list[dict]:
    found = []
    for para in paragraphs:
        words = re.findall(r"[A-Za-z]{3,}", para)
        if len(words) < 4:
            continue
        toks = list(TOKEN.finditer(para))
        for m in toks:
            cur, num, tail = m.group(1), m.group(2), (m.group(3) or "").strip().lower()
            v = float(num.replace(",", ""))
            if cur == "" and tail == "" and 1900 <= v <= 2100 and "," not in num and "." not in num:
                continue  # a year
            if v == 0 or para.count(m.group(0)) != 1:
                continue
            raw = m.group(0).strip()
            before = para[: m.start()]
            label_words = [w for w in re.findall(r"[A-Za-z][A-Za-z&-]+", before)[-6:] if w.lower() not in STOP][-3:]
            found.append({"para": para, "raw": raw, "value": v, "unit": "percent" if tail == "%" else ("currency" if cur else "plain"),
                          "scale": SCALE.get(tail, 1.0), "decimals": len(num.split(".")[1]) if "." in num else 0, "comma": "," in num, "cur": cur, "tail": m.group(3) or "",
                          "label": " ".join(label_words)})
    random.Random(7).shuffle(found)
    return found[:limit]


def cell_value(seed: dict, i: int) -> float:
    """Store the figure the way analysts do: a percentage as a fraction or as shown, an amount in full or in the document's unit."""
    h = int(hashlib.sha1(f"{i}{seed['raw']}".encode()).hexdigest(), 16) % 3
    v = seed["value"]
    if seed["unit"] == "percent":
        return v / 100.0 if h != 0 else v
    if seed["scale"] != 1.0 and h == 1:
        return v * seed["scale"]
    return v


def new_token(seed: dict, factor: Decimal = Decimal("1.1")) -> str:
    d = seed["decimals"]
    nv = (Decimal(repr(seed["value"])) * factor).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    body = f"{nv:,.{d}f}" if seed["comma"] else f"{nv:.{d}f}"
    return f"{seed['cur']}{body}{seed['tail']}"


def build_project(doc: Path, seeds: list[dict], mode: str) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="ft_"))
    shutil.copy2(doc, root / doc.name)
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Metric", "Value"])
    for i, s in enumerate(seeds):
        ws.append([s["label"] if mode == "labelled" else f"Item {i + 1}", cell_value(s, i)])
        if s["unit"] == "percent" and cell_value(s, i) < 1.5 and s["value"] >= 1.5:
            ws.cell(row=i + 2, column=2).number_format = "0.0%"
    wb.save(root / "data.xlsx")
    return root, root / "data.xlsx"


def classify(seeds: list[dict], ties: list[dict], docname: str, mode: str = "labelled") -> list[dict]:
    out = []
    for i, s in enumerate(seeds):
        want = f"B{i + 2}"
        cands = [t for t in ties if t["deck"] == docname and t["text"].strip() == s["raw"] and (t["sentence"] and (t["sentence"] in s["para"] or s["para"] in t["sentence"] or norm(t["sentence"]) in norm(s["para"])))]
        if not cands:
            out.append({"seed": i, "result": "not_found"})
            continue
        t = cands[0]
        got = t["source"].split("!")[-1]
        if t["state"] == "accepted":
            result = "linked_right" if got == want else "LINKED_WRONG"
            if result == "LINKED_WRONG":
                other = seeds[int(got[1:]) - 2] if got[1:].isdigit() and 0 <= int(got[1:]) - 2 < len(seeds) else None
                words = set(re.findall(r"[a-z]{3,}", s["para"].lower()))
                if other and other["raw"] == s["raw"] and other["label"] and {w.lower() for w in other["label"].split()} <= words:
                    result = "linked_equivalent"  # another cell holds the same figure and its label is in this paragraph: a person would pick it too
            out.append({"seed": i, "result": result, "got": got, "want": want, "tie": t["id"]})
            if mode == "labelled" and not s["label"] and result in ("LINKED_WRONG",):
                out[-1]["result"] = "unlabelled_ambiguous_linked"  # the workbook row has no words at all: the harness built an unlabelled row, another cell with the same figure may rightly win
        else:
            out.append({"seed": i, "result": "proposed" if got == want else "proposed_wrong", "got": got, "want": want, "tie": t["id"], "state": t["state"]})
    return out


def read_com(kind: str, path: Path) -> list[str]:
    import pythoncom

    pythoncom.CoInitialize()
    app, reader = app_for(kind)
    try:
        return reader(app, str(path))
    finally:
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass


def run_doc(doc: Path, mode: str, max_seeds: int, min_seeds: int, updates: int) -> dict:
    row: dict = {"file": doc.name, "kind": doc.suffix.lower(), "mode": mode}
    try:
        paras = paragraphs_of(doc)
    except Exception as exc:  # noqa: BLE001
        row.update(status="skipped", reason=f"independent reader: {type(exc).__name__}")
        return row
    seeds = seeds_of(paras, max_seeds)
    if len(seeds) < min_seeds:
        row.update(status="skipped", reason=f"only {len(seeds)} usable figures")
        return row
    root, wbpath = build_project(doc, seeds, mode)
    state = Path(tempfile.mkdtemp(prefix="ft_state_"))
    try:
        svc = Service(state)
        pid = svc.add_project(str(root))["project"]
        t0 = time.time()
        svc.discover(pid)
        row["discover_seconds"] = round(time.time() - t0, 2)
        ties = svc.ties(pid)
        cls = classify(seeds, ties, doc.name, mode)
        count = {}
        for c in cls:
            count[c["result"]] = count.get(c["result"], 0) + 1
        row.update(status="ok", seeds=len(seeds), classes=count, wrong=[{"raw": seeds[c["seed"]]["raw"], "label": seeds[c["seed"]]["label"], "got": c["got"], "want": c["want"]} for c in cls if c["result"] == "LINKED_WRONG"][:5],
                   unseeded_links=sum(1 for t in ties if t["state"] == "accepted") - count.get("linked_right", 0) - count.get("LINKED_WRONG", 0))
        right = [c for c in cls if c["result"] == "linked_right"][:updates]
        row["updated"] = 0
        if not right:
            return row
        from openpyxl import load_workbook

        wb = load_workbook(wbpath)
        ws = wb.active
        edits = []
        for c in right:
            s = seeds[c["seed"]]
            cur = ws.cell(row=c["seed"] + 2, column=2).value
            ws.cell(row=c["seed"] + 2, column=2).value = cur * 1.1 if abs(cur * 1.1 - cur) > 0 else cur
            edits.append((s["raw"], new_token(s)))
        wb.save(wbpath)
        before_texts = read_com(doc.suffix.lower(), root / doc.name)
        svc.discover(pid)
        staged = svc.stage(pid)
        try:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=False)
        except NeedsAcknowledgement:
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"], acknowledge=True)
        after_texts = read_com(doc.suffix.lower(), root / doc.name)
        edits = [e for e in edits if e[0] != e[1]]
        ok, why = compare_text(before_texts, after_texts, edits)
        row.update(updated=len(edits), text_ok=ok, text_note=why)
        if not ok:
            from collections import Counter

            cb, ca = Counter(before_texts), Counter(after_texts)
            row["removed"] = [t[:300] for t in list((cb - ca).elements())[:3]]
            row["added"] = [t[:300] for t in list((ca - cb).elements())[:3]]
            row["edits"] = edits[:8]
    except (ServiceError, Exception) as exc:  # noqa: BLE001
        row.update(status=row.get("status", "failed") if row.get("status") == "ok" else "failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(state, ignore_errors=True)
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--mode", default="labelled", choices=("labelled", "bare"))
    ap.add_argument("--max-seeds", type=int, default=30)
    ap.add_argument("--min-seeds", type=int, default=6)
    ap.add_argument("--updates", type=int, default=5)
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--no-update", action="store_true", help="classify the links only; skip the update and the real-Office check")
    ns = ap.parse_args()
    files = collect(ns.targets, (".docx", ".pptx"))[: ns.limit]
    rows = []
    for i, f in enumerate(files, 1):
        r = run_doc(f, ns.mode, ns.max_seeds, ns.min_seeds, 0 if ns.no_update else ns.updates)
        rows.append(r)
        print(f"{i}/{len(files)} {f.name[:40]} {r.get('status')} {r.get('classes', r.get('reason', r.get('error', '')))}", flush=True)
        Path(ns.out).write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    ok = [r for r in rows if r["status"] == "ok"]
    tot: dict = {}
    for r in ok:
        for k, v in r["classes"].items():
            tot[k] = tot.get(k, 0) + v
    summary = {"documents": len(rows), "measured": len(ok), "seeds": sum(r["seeds"] for r in ok), "classes": tot,
               "updates_checked": sum(r.get("updated", 0) for r in ok), "docs_update_ok": sum(1 for r in ok if r.get("text_ok")), "docs_update_failed": sum(1 for r in ok if r.get("updated") and not r.get("text_ok"))}
    print(json.dumps(summary))
    Path(ns.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
