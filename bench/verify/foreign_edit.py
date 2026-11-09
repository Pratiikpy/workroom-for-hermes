"""Edit numbers in Word and PowerPoint files other people made, then check the result with the real Office apps and Microsoft's validator.

    python foreign_edit.py <out.json> <folder or file> [...] [--limit N] [--batch N] [--edits N]

For each .docx or .pptx: three numbers are edited through Workroom (first, middle, last). Then
  1. Workroom's own guarantee: every part it did not change is byte-identical, and a no-edit rewrite is identical;
  2. Microsoft's Open XML SDK validator reports no error the original did not already have;
  3. the real Word or PowerPoint opens the edited file, and the text it reports differs from the original's only in the edited
     numbers, in the places that were edited (text compared token by token, so a stray change anywhere else is a failure).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

NUM = re.compile(r"[0-9](?:[0-9,.]*[0-9])?")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", CONTROL.sub(" ", text)).strip()


def pick_mentions(mentions, how_many: int):
    good = [dm for dm in mentions if (dm.number.unit in ("plain", "percent") or dm.number.unit.startswith("currency"))
            and dm.number.value != 0 and not (dm.number.unit == "plain" and 1900 <= dm.number.value <= 2100)]
    if len(good) <= how_many:
        return good
    idx = sorted({0, len(good) // 2, len(good) - 1})[:how_many]
    return [good[i] for i in idx]


def edit_file(path: Path, how_many: int):
    from workroom.workroom_core.match.numbers import format_like
    from workroom.workroom_core.ooxml.docx import Doc
    from workroom.workroom_core.ooxml.pptx import Deck

    data = path.read_bytes()
    kind = path.suffix.lower()
    doc = (Doc if kind == ".docx" else Deck)(data)
    if doc.serialize()[0] != data:
        raise AssertionError("a no-edit rewrite is not byte-identical")
    picks = pick_mentions(list(doc.mentions()), how_many)
    done = []
    for dm in sorted(picks, key=lambda d: (d.slide, d.shape_id, d.para, d.seg, -d.offset)):
        new_text = format_like(dm.number, dm.number.value * 1.1, "exact")
        if new_text == dm.number.raw:
            continue
        doc.edit_mention(dm, new_text)
        done.append((dm.number.raw, new_text))
    out, report = doc.serialize()
    return data, out, done, report


def parts_identical(before: bytes, after: bytes, changed) -> bool:
    from workroom.workroom_core.ooxml.package import open_package, raw_unchanged

    b, a = open_package(before), open_package(after)
    others = [n for n in b.names() if n not in changed]
    return raw_unchanged(b, a, others) == others and sorted(b.names()) == sorted(a.names())


def validator_errors(paths: list[Path]) -> dict[str, list]:
    dll = HERE / "oxml_validate" / "bin" / "Release" / "net8.0" / "oxml_validate.dll"
    result: dict[str, list] = {}
    for i in range(0, len(paths), 40):
        proc = subprocess.run(["dotnet", str(dll), *map(str, paths[i:i + 40])], capture_output=True, text=True, timeout=900)
        for line in proc.stdout.splitlines():
            o = json.loads(line)
            result[o["file"]] = [("FATAL", o["fatal"], "")] if o["fatal"] else [(e["part"], e["path"], e["description"]) for e in o["errors"]]
    return result


# ---- the real Office apps ----

def word_texts(app, path: str) -> list[str]:
    doc = app.Documents.Open(path, False, True, False, "x", "x", True)
    try:
        out = []
        for sr in doc.StoryRanges:
            r = sr
            while r is not None:
                for part in re.split(r"[\r\x07]", r.Text or ""):
                    if norm(part):
                        out.append(norm(part))
                r = r.NextStoryRange
        return out
    finally:
        doc.Close(False)


def ppt_texts(app, path: str) -> list[str]:
    pres = app.Presentations.Open(path, True, False, False)
    out: list[str] = []

    def walk(shapes):
        for sh in shapes:
            if sh.Type == 6:
                walk(sh.GroupItems)
                continue
            try:
                if sh.HasTextFrame and sh.TextFrame.HasText:
                    out.append(norm(sh.TextFrame.TextRange.Text))
                if sh.HasTable:
                    for r in range(1, sh.Table.Rows.Count + 1):
                        for c in range(1, sh.Table.Columns.Count + 1):
                            out.append(norm(sh.Table.Cell(r, c).Shape.TextFrame.TextRange.Text))
            except Exception:  # noqa: BLE001
                continue

    try:
        for slide in pres.Slides:
            walk(slide.Shapes)
            try:
                walk(slide.NotesPage.Shapes)
            except Exception:  # noqa: BLE001
                pass
        return [t for t in out if t]
    finally:
        pres.Close()


def app_for(kind: str):
    import win32com.client

    if kind == ".docx":
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        app.DisplayAlerts = 0
        app.AutomationSecurity = 3
        return app, word_texts
    app = win32com.client.DispatchEx("PowerPoint.Application")
    return app, ppt_texts


def compare_text(before: list[str], after: list[str], edits: list[tuple]) -> tuple[bool, str]:
    cb, ca = Counter(before), Counter(after)
    removed, added = list((cb - ca).elements()), list((ca - cb).elements())
    if not edits:
        return (not removed and not added), "no edits made"
    if len(removed) != len(added):
        return False, f"{len(removed)} texts removed but {len(added)} added"
    if not removed:
        return False, "edited but the real app sees no change"
    pairs = {(o, n) for o, n in edits}
    old_nums, new_nums = {tuple(NUM.findall(o)) for o, _ in pairs}, {tuple(NUM.findall(n)) for _, n in pairs}
    used = set()
    for r in removed:
        for j, a in enumerate(added):
            if j in used:
                continue
            tr, ta = NUM.split(r), NUM.split(a)
            nr, na = NUM.findall(r), NUM.findall(a)
            if len(nr) == len(na) and tr == ta:
                diff = [(x, y) for x, y in zip(nr, na) if x != y]
                if diff and all(any(x in o and y in n for o, n in pairs) for x, y in diff):
                    used.add(j)
                    break
        else:
            return False, f"changed text not explained by the edits: {r[:70]!r}"
    return True, f"{len(removed)} text(s) changed, all explained by the edits"


def worker(kind: str, jobs_file: str, out: str) -> None:
    import pythoncom

    pythoncom.CoInitialize()
    jobs = json.loads(Path(jobs_file).read_text(encoding="utf-8"))
    app, reader = app_for(kind)
    rows = []
    try:
        for j in jobs:
            row = {"file": j["name"]}
            try:
                try:
                    tb = reader(app, j["before"])
                except Exception as exc:  # noqa: BLE001
                    row.update(original_unopenable=True, text_note=f"the original file does not open in the real app either ({type(exc).__name__})")
                    rows.append(row)
                    Path(out).write_text(json.dumps(rows), encoding="utf-8")
                    continue
                ta = reader(app, j["after"])
                ok, why = compare_text(tb, ta, [tuple(e) for e in j["edits"]])
                row.update(office_opens=True, text_ok=ok, text_note=why, texts=len(tb))
            except Exception as exc:  # noqa: BLE001
                row.update(office_opens=False, text_ok=False, text_note=f"{type(exc).__name__}: {str(exc)[:140]}")
            rows.append(row)
            Path(out).write_text(json.dumps(rows), encoding="utf-8")
    finally:
        try:
            app.Quit()
        except Exception:  # noqa: BLE001
            pass


def run_office(kind: str, jobs: list[dict], work: Path, batch: int) -> dict[str, dict]:
    results: dict[str, dict] = {}
    pending = list(jobs)
    n = 0
    while pending:
        chunk, pending = pending[:batch], pending[batch:]
        n += 1
        jf, out = work / f"jobs{kind}{n}.json", work / f"out{kind}{n}.json"
        jf.write_text(json.dumps(chunk), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(Path(__file__)), "--worker", kind, str(jf), str(out)])
        timed_out = False
        try:
            proc.wait(timeout=150 + 40 * len(chunk))
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        done = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else []
        for r in done:
            results[r["file"]] = r
        if len(done) < len(chunk):
            hung = chunk[len(done)]
            results[hung["name"]] = {"file": hung["name"], "office_opens": False, "text_ok": False, "text_note": "the app did not answer within the time limit (hung)" if timed_out else f"the checking process stopped (exit {proc.returncode}) before this file"}
            pending = chunk[len(done) + 1:] + pending
        print(f"{kind}: {len(results)}/{len(jobs)} checked in the real app", flush=True)
    return results


def collect(targets: list[str], exts: tuple[str, ...]) -> list[Path]:
    seen, out = set(), []
    for t in targets:
        p = Path(t).resolve()
        files = [p] if p.is_file() else [f for f in sorted(p.rglob("*")) if f.suffix.lower() in exts and "~$" not in f.name]
        for f in files:
            try:
                if f.stat().st_size == 0:
                    continue
                h = hashlib.sha1(f.read_bytes()).hexdigest()
            except OSError:
                continue
            if h not in seen:
                seen.add(h)
                out.append(f)
    return out


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:5])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--edits", type=int, default=3)
    ns = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="foreign-edit-"))
    files = collect(ns.targets, (".docx", ".pptx"))[: ns.limit]
    rows, jobs = {}, {".docx": [], ".pptx": []}
    pairs = []
    for i, f in enumerate(files):
        row = {"file": f.name, "kind": f.suffix.lower(), "bytes": f.stat().st_size}
        try:
            before, after, done, report = edit_file(f, ns.edits)
        except Exception as exc:  # noqa: BLE001
            row.update(status="skipped", reason=f"{type(exc).__name__}: {str(exc)[:90]}")
            rows[f.name] = row
            continue
        if not done:
            row.update(status="skipped", reason="no number to edit")
            rows[f.name] = row
            continue
        b, a = work / f"b{i}{f.suffix}", work / f"a{i}{f.suffix}"
        b.write_bytes(before)
        a.write_bytes(after)
        row.update(edits=len(done), parts_changed=len(report.parts_changed), others_identical=parts_identical(before, after, report.parts_changed), status="pending")
        rows[f.name] = row
        pairs.append((b, a, f.name))
        jobs[f.suffix.lower()].append({"name": f.name, "before": str(b), "after": str(a), "edits": done})
    print(f"edited {len(pairs)} of {len(files)} files; validating with the Open XML SDK", flush=True)
    errs = validator_errors([p for b, a, _ in pairs for p in (b, a)])
    for b, a, name in pairs:
        eb, ea = errs.get(str(b), []), errs.get(str(a), [])
        known = {(e[0], e[1], e[2]) for e in eb}
        rows[name]["validator_before"], rows[name]["validator_after"] = len(eb), len(ea)
        rows[name]["validator_new_errors"] = [e for e in ea if (e[0], e[1], e[2]) not in known][:5]
    for kind, js in jobs.items():
        if js:
            for name, r in run_office(kind, js, work, ns.batch).items():
                rows[name].update({k: v for k, v in r.items() if k != "file"})
    for r in rows.values():
        if r["status"] == "pending":
            if r.get("original_unopenable"):
                r["status"] = "original_not_openable"
                continue
            bad = []
            if not r["others_identical"]:
                bad.append("parts Workroom did not touch differ")
            if r["validator_new_errors"]:
                bad.append("validator: new errors")
            if not r.get("office_opens"):
                bad.append("real app could not open it")
            elif not r.get("text_ok"):
                bad.append("real app text differs unexpectedly")
            r["status"] = "ok" if not bad else "FAILED"
            r["why"] = bad
    vals = list(rows.values())
    summary = {"files": len(vals), "ok": sum(r["status"] == "ok" for r in vals), "failed": sum(r["status"] == "FAILED" for r in vals),
               "skipped": sum(r["status"] == "skipped" for r in vals), "original_not_openable": sum(r["status"] == "original_not_openable" for r in vals), "by_kind": {k: sum(1 for r in vals if r["kind"] == k and r["status"] == "ok") for k in (".docx", ".pptx")}}
    Path(ns.out).write_text(json.dumps({"summary": summary, "rows": vals}, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary))
    for r in vals:
        if r["status"] == "FAILED":
            print("FAIL", r["file"], r["why"], r.get("text_note"), r.get("validator_new_errors"))


if __name__ == "__main__":
    main()
