"""Edit ONE number in each real deck with office-desk and with the Workroom kernel; count what else changed.

Research instrument. office-desk is imported from its own checkout; nothing is sent anywhere. Real decks are the
public test decks used by the other corpus benches. Measures: did the edit land, how many package parts differ from the
original (decompressed bytes), and does the output still open.
"""

import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ["OFFICE_DESK_CHECKOUT"])  # folder holding the office-desk package `hermes_office`

from pptx import Presentation  # noqa: E402

from hermes_office import pptx_ops  # noqa: E402
from workroom.workroom_core.ooxml.package import PackageError  # noqa: E402
from workroom.workroom_core.ooxml.pptx import Deck  # noqa: E402
from workroom.workroom_core.ooxml.runs import EditError  # noqa: E402

NUM = re.compile(r"\d{2,}")


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist()}


def differing(a: bytes, b: bytes) -> list[str]:
    pa, pb = parts(a), parts(b)
    return sorted(n for n in set(pa) | set(pb) if pa.get(n) != pb.get(n))


def pick(path: Path):
    """A slide index, shape name and a number found wholly inside one text run of an ordinary text shape."""
    prs = Presentation(str(path))
    for si, slide in enumerate(prs.slides):
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    m = NUM.search(r.text)
                    if m and sh.name:
                        return si, sh.name, m.group(0)
    return None


def kernel_pick(original: bytes):
    deck = Deck(original)
    for m in deck.mentions():
        if len(m.number.raw) >= 2 and m.number.raw.isdigit():
            return deck, m
    return None, None


def main(folders: list[str]) -> None:
    rows = []
    for folder in folders:
        for path in sorted(Path(folder).glob("*.pptx")):
            original = path.read_bytes()
            try:
                deck, m = kernel_pick(original)
            except (EditError, PackageError):
                continue
            if m is None:
                continue
            old = m.number.raw
            new = str(int(old) + 7)
            si = m.slide - 1
            row = {"deck": path.name, "target": f"slide {m.slide} {old}->{new}"}
            part = deck.slide_parts()[si] if hasattr(deck, "slide_parts") else None
            try:
                out, report = deck.edit_mention(m, new) or deck.serialize()
            except Exception:  # noqa: BLE001
                out = None
            try:
                deck2 = Deck(original)
                m2 = next(x for x in deck2.mentions() if x.number.raw == old and x.slide == m.slide)
                deck2.edit_mention(m2, new)
                out, _ = deck2.serialize()
                row["workroom"] = {"parts_changed": len(differing(original, out)), "landed": new.encode() in parts(out).get(part, b"")}
            except Exception as exc:  # noqa: BLE001
                row["workroom"] = {"error": f"{type(exc).__name__}: {str(exc)[:70]}"}
            tmp = Path(tempfile.mkdtemp()) / path.name
            shutil.copy(path, tmp)
            try:
                prs = Presentation(str(path))
                shape = next((sh.name for sh in prs.slides[si].shapes if sh.has_text_frame and old in sh.text_frame.text), None)
                if shape is None:
                    row["office_desk"] = {"error": "shape not found by name"}
                else:
                    pptx_ops.edit_pptx_shape(str(tmp), slide=si, shape=shape, ops=[{"op": "replace_text", "find": old, "replace": new}])
                    out_od = tmp.read_bytes()
                    row["office_desk"] = {"parts_changed": len(differing(original, out_od)), "landed": new.encode() in parts(out_od).get(part, b"")}
            except Exception as exc:  # noqa: BLE001
                row["office_desk"] = {"error": f"{type(exc).__name__}: {str(exc)[:70]}"}
            rows.append(row)

    def stats(key):
        ok = [r[key] for r in rows if key in r and "error" not in r[key]]
        err = [r[key] for r in rows if key in r and "error" in r[key]]
        landed = sum(1 for o in ok if o["landed"])
        pc = sorted(o["parts_changed"] for o in ok)
        kinds: dict[str, int] = {}
        for e in err:
            k = e["error"].split(":")[0]
            kinds[k] = kinds.get(k, 0) + 1
        return {"decks": len(rows), "ran_ok": len(ok), "errors": len(err), "error_kinds": kinds, "edit_landed": landed,
                "parts_changed_median": pc[len(pc) // 2] if pc else None, "parts_changed_max": pc[-1] if pc else None,
                "decks_with_more_than_one_part_changed": sum(1 for x in pc if x > 1)}

    summary = {"office_desk": stats("office_desk"), "workroom_kernel": stats("workroom")}
    Path(__file__).with_name("real_decks_vs_officedesk_result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
