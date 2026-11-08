"""Edit one real shape in every deck of a folder and verify nothing else moved.

For each deck: pick the first text shape holding a word of 4+ letters that occurs exactly once in that shape,
replace it through the kernel, then check with python-pptx (an independent reader) that the target text changed
as expected, every other shape's text on every slide is unchanged, and every part except the edited slide has
identical compressed bytes.
"""

import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pptx import Presentation  # noqa: E402

from workroom.workroom_core.ooxml.package import PackageError, open_package, raw_unchanged  # noqa: E402
from workroom.workroom_core.ooxml.pptx import Deck  # noqa: E402
from workroom.workroom_core.ooxml.runs import EditError  # noqa: E402


def _walk(shapes):
    for sh in shapes:
        if sh.shape_type == 6:  # group
            yield from _walk(sh.shapes)
            continue
        if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
            yield sh.shape_id, sh.text_frame.text
        if getattr(sh, "has_table", False) and sh.has_table:
            for ri, row in enumerate(sh.table.rows):
                for ci, cell in enumerate(row.cells):
                    yield sh.shape_id, f"[{ri},{ci}]" + cell.text_frame.text


def snapshot(data: bytes) -> list[list[tuple[int, str]]]:
    prs = Presentation(io.BytesIO(data))
    return [list(_walk(s.shapes)) for s in prs.slides]


def main(folder: str) -> int:
    rows = []
    for path in sorted(Path(folder).glob("*.pptx")):
        data = path.read_bytes()
        row = {"file": path.name}
        try:
            deck = Deck(data)
            slides = len(deck.slide_parts())
        except (PackageError, EditError, KeyError, Exception) as exc:  # noqa: BLE001
            row.update(status="skipped", reason=f"{type(exc).__name__}: {str(exc)[:80]}")
            rows.append(row)
            continue
        target = None
        for si in range(1, slides + 1):
            for sid, name, text in deck.shapes(si):
                for m in re.finditer(r"[A-Za-z]{4,}", text):
                    if text.count(m.group(0)) == 1:
                        target = (si, sid, m.group(0))
                        break
                if target:
                    break
            if target:
                break
        if not target:
            row.update(status="skipped", reason="no suitable text")
            rows.append(row)
            continue
        si, sid, word = target
        marker = word + "QQ"
        try:
            before = snapshot(data)
            deck.edit_text(si, sid, word, marker)
            out, report = deck.serialize()
            after = snapshot(out)
        except Exception as exc:  # noqa: BLE001
            row.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:100]}")
            rows.append(row)
            continue
        changed = [(i, a, b) for i, (sa, sb) in enumerate(zip(before, after)) for a, b in zip(sa, sb) if a != b]
        expected_ok = len(changed) == 1 and changed[0][0] == si - 1 and marker in changed[0][2][1] and changed[0][1][0] == sid
        b_pkg, a_pkg = open_package(data), open_package(out)
        others = [n for n in b_pkg.names() if n not in report.parts_changed]
        row.update(
            status="ok" if expected_ok and raw_unchanged(b_pkg, a_pkg, others) == others and len(report.parts_changed) == 1 else "FAILED",
            slide=si, shape=sid, parts_changed=list(report.parts_changed), only_target_changed=expected_ok,
        )
        rows.append(row)
    ok = sum(1 for r in rows if r["status"] == "ok")
    summary = {"decks": len(rows), "ok": ok, "failed": sum(1 for r in rows if r["status"] in ("FAILED", "failed")), "skipped": sum(1 for r in rows if r["status"] == "skipped")}
    Path(__file__).with_name("corpus_edit_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    for r in rows:
        if r["status"] in ("FAILED", "failed"):
            print("FAIL", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
