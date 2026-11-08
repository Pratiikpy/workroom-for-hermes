"""Check Workroom's edits with readers that share none of its code.

    python independent_check.py <folder of .pptx> [--limit N] [--com N] [out.json]

For every deck: edit a few numbers through Workroom, then
  1. validate the deck before and after with Microsoft's Open XML SDK (bench/verify/oxml_validate): no error may appear that the
     original did not already have;
  2. read both decks with python-pptx and require that the only paragraphs that differ are the edited ones, and that each differs
     only in the edited number;
  3. for a sample, open the edited deck in the real PowerPoint and require that the text it reports equals python-pptx's reading.
"""

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from pptx import Presentation  # noqa: E402

from workroom.workroom_core.match.numbers import format_like  # noqa: E402
from workroom.workroom_core.ooxml.pptx import Deck  # noqa: E402

VALIDATOR = HERE / "oxml_validate" / "bin" / "Release" / "net8.0" / "oxml_validate.dll"


def paragraph_map(data: bytes) -> dict[tuple, str]:
    """Every paragraph of the deck as read by python-pptx, addressed by (slide, shape id, table cell, paragraph index)."""
    out: dict[tuple, str] = {}

    def walk(si, shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                walk(si, sh.shapes)
                continue
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                for pi, p in enumerate(sh.text_frame.paragraphs):
                    out[(si, sh.shape_id, None, pi)] = p.text
            if getattr(sh, "has_table", False) and sh.has_table:
                for ri, row in enumerate(sh.table.rows):
                    for ci, cell in enumerate(row.cells):
                        for pi, p in enumerate(cell.text_frame.paragraphs):
                            out[(si, sh.shape_id, (ri, ci), pi)] = p.text

    for si, slide in enumerate(Presentation(io.BytesIO(data)).slides, 1):
        walk(si, slide.shapes)
    return out


def paragraphs(data: bytes) -> list[str]:
    out = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                walk(sh.shapes)
                continue
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                out.extend(p.text for p in sh.text_frame.paragraphs)
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        out.extend(p.text for p in cell.text_frame.paragraphs)

    for slide in Presentation(io.BytesIO(data)).slides:
        walk(slide.shapes)
    return out


def edit(data: bytes, how_many: int = 3) -> tuple[bytes, list[tuple]]:
    deck = Deck(data)
    picks = []
    for dm in deck.mentions():
        if dm.number.unit in ("plain", "percent") or dm.number.unit.startswith("currency"):
            if dm.number.value != 0 and not (dm.number.unit == "plain" and 1900 <= dm.number.value <= 2100):
                picks.append(dm)
        if len(picks) >= how_many:
            break
    done = []
    for dm in sorted(picks, key=lambda d: (d.slide, d.shape_id, d.para, d.seg, -d.offset)):
        new_text = format_like(dm.number, dm.number.value * 1.1, "exact")
        if new_text == dm.number.raw:
            continue
        deck.edit_mention(dm, new_text)
        done.append((dm.number.raw, new_text, (dm.slide, dm.shape_id, dm.cell, dm.para), dm.para_offset))
    out, _ = deck.serialize()
    return out, done


def validate(paths: list[Path]) -> dict[str, list[tuple]]:
    result: dict[str, list[tuple]] = {}
    for i in range(0, len(paths), 40):
        chunk = paths[i:i + 40]
        proc = subprocess.run(["dotnet", str(VALIDATOR), *map(str, chunk)], capture_output=True, text=True, timeout=600)
        for line in proc.stdout.splitlines():
            o = json.loads(line)
            result[o["file"]] = [("FATAL", o["fatal"], "")] if o["fatal"] else [(e["part"], e["path"], e["description"]) for e in o["errors"]]
    return result


COM_SCRIPT = r'''
param([string]$Path, [string]$Out)
$app = New-Object -ComObject PowerPoint.Application
$texts = New-Object System.Collections.Generic.List[string]
function Walk($shapes) {
  foreach ($sh in $shapes) {
    if ($sh.Type -eq 6) { Walk $sh.GroupItems; continue }
    if ($sh.HasTextFrame) { $texts.Add($sh.TextFrame.TextRange.Text) }
    if ($sh.HasTable) { foreach ($r in 1..$sh.Table.Rows.Count) { foreach ($c in 1..$sh.Table.Columns.Count) { $texts.Add($sh.Table.Cell($r, $c).Shape.TextFrame.TextRange.Text) } } }
  }
}
try {
  $pres = $app.Presentations.Open($Path, $true, $false, $false)
  foreach ($slide in $pres.Slides) { Walk $slide.Shapes }
  $pres.Close()
  [System.IO.File]::WriteAllText($Out, ($texts | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
} finally { $app.Quit() }
'''


def office_text(path: Path) -> list[str] | None:
    folder = Path(tempfile.mkdtemp())
    script, out = folder / "read.ps1", folder / "out.json"
    script.write_text(COM_SCRIPT, encoding="utf-8")
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Path", str(path), "-Out", str(out)], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not out.is_file():
        return None
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return [data] if isinstance(data, str) else data


def shape_texts(data: bytes) -> list[str]:
    """One string per text shape or table cell, paragraphs joined, in the form PowerPoint's own object model reports them."""
    out: list[str] = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                walk(sh.shapes)
                continue
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                out.append("\n".join(p.text for p in sh.text_frame.paragraphs))
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        out.append("\n".join(p.text for p in cell.text_frame.paragraphs))

    for slide in Presentation(io.BytesIO(data)).slides:
        walk(slide.shapes)
    return out


def norm(texts: list[str]) -> list[str]:
    return sorted(re.sub(r"\s+", " ", t).strip() for t in texts if t and t.strip())


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--limit", type=int, default=10_000)
    ap.add_argument("--com", type=int, default=0)
    ns = ap.parse_args()
    limit, com_n, folder = ns.limit, ns.com, Path(ns.folder)
    out_path = Path(ns.out) if ns.out else None
    work = Path(tempfile.mkdtemp(prefix="independent-"))
    decks = sorted(folder.glob("*.pptx"))[:limit]
    rows = []
    befores, afters = [], []
    for p in decks:
        row = {"deck": p.name}
        try:
            before = p.read_bytes()
            after, done = edit(before)
        except Exception as exc:  # noqa: BLE001
            row["skipped"] = f"{type(exc).__name__}: {str(exc)[:80]}"
            rows.append(row)
            continue
        if not done:
            row["skipped"] = "no number to edit"
            rows.append(row)
            continue
        b, a = work / f"b_{p.name}", work / f"a_{p.name}"
        b.write_bytes(before)
        a.write_bytes(after)
        befores.append(b)
        afters.append(a)
        row["edits"] = [(o, n) for o, n, _, _ in done]
        try:
            mb, ma = paragraph_map(before), paragraph_map(after)
        except Exception as exc:  # noqa: BLE001
            row["python_pptx"] = f"cannot read: {type(exc).__name__}"
            rows.append(row)
            continue
        expected = dict(mb)
        for old, new, key, offset in sorted(done, key=lambda e: (e[2][0], e[2][1], str(e[2][2]), e[2][3], -(e[3] if e[3] is not None else -1))):
            text = expected.get(key)
            pos = offset if offset is not None and text is not None and text[offset:offset + len(old)] == old else (text.find(old) if text else -1)
            if text is not None and pos >= 0:
                expected[key] = text[:pos] + new + text[pos + len(old):]
        wrong = [k for k in set(ma) | set(expected) if ma.get(k) != expected.get(k)]
        row["python_pptx"] = "ok" if not wrong else f"{len(wrong)} paragraphs differ from the expected edit"
        if wrong:
            k = wrong[0]
            row["first_difference"] = {"at": [str(x) for x in k], "expected": (expected.get(k) or "")[:80], "found": (ma.get(k) or "")[:80]}
        row["edits"] = [(o, n) for o, n, _, _ in done]
        rows.append(row)
    vb, va = validate(befores), validate(afters)
    by_name = {r["deck"]: r for r in rows}
    for b, a in zip(befores, afters):
        name = a.name[2:]
        before_errors, after_errors = set(vb.get(str(b), [])), set(va.get(str(a), []))
        new = sorted(after_errors - before_errors)
        by_name[name]["open_xml"] = {"errors_before": len(before_errors), "errors_after": len(after_errors), "new_errors": [list(x) for x in new[:3]]}
    checked_com = 0
    for a in afters:
        if checked_com >= com_n:
            break
        name = a.name[2:]
        row = by_name[name]
        if row.get("python_pptx") != "ok":
            continue
        original = office_text(befores[afters.index(a)])
        checked_com += 1
        if original is None:
            row["powerpoint"] = "the original does not open in PowerPoint either (not counted)"
            continue
        got = office_text(a)
        if got is None:
            row["powerpoint"] = "could not open"
            continue
        from collections import Counter

        py_b, py_a = Counter(norm(shape_texts(befores[afters.index(a)].read_bytes()))), Counter(norm(shape_texts(a.read_bytes())))
        com_b, com_a = Counter(norm(original)), Counter(norm(got))
        same = (py_a - py_b) == (com_a - com_b) and (py_b - py_a) == (com_b - com_a)
        row["powerpoint"] = "ok" if same else f"PowerPoint sees different changes: it added {sum((com_a - com_b).values())} / removed {sum((com_b - com_a).values())} items, python-pptx added {sum((py_a - py_b).values())} / removed {sum((py_b - py_a).values())}"
    done_rows = [r for r in rows if "edits" in r]
    summary = {
        "decks": len(rows), "edited": len(done_rows), "skipped": len(rows) - len(done_rows),
        "python_pptx_ok": sum(1 for r in done_rows if r.get("python_pptx") == "ok"),
        "open_xml_no_new_errors": sum(1 for r in done_rows if "open_xml" in r and not r["open_xml"]["new_errors"]),
        "open_xml_checked": sum(1 for r in done_rows if "open_xml" in r),
        "decks_with_preexisting_open_xml_errors": sum(1 for r in done_rows if "open_xml" in r and r["open_xml"]["errors_before"]),
        "powerpoint_checked": sum(1 for r in done_rows if r.get("powerpoint") in ("ok", "could not open") or str(r.get("powerpoint", "")).startswith("PowerPoint sees")),
        "powerpoint_ok": sum(1 for r in done_rows if r.get("powerpoint") == "ok"),
        "powerpoint_original_does_not_open": sum(1 for r in done_rows if str(r.get("powerpoint", "")).startswith("the original")),
    }
    print(json.dumps(summary, indent=1))
    for r in done_rows:
        bad = r.get("python_pptx") != "ok" or r.get("open_xml", {}).get("new_errors") or r.get("powerpoint") not in (None, "ok") and not str(r.get("powerpoint")).startswith("the original")
        if bad:
            print("FAIL", json.dumps(r)[:400])
    if out_path:
        out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
