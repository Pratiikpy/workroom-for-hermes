"""Point-to-edit measured on real decks and reports other people made: 50 scoped text edits, each checked for collateral change.

    python point_edit_bench.py <out.json> <folder-with-pptx-docx> [<folder> ...] [--n 50] [--seed 7]

For each sampled file one word is chosen in one shape (deck) or paragraph (report) and replaced through the same service route the agent tool uses
(`find_text` then `stage_text_edit`), then published. Pass bar per edit: exactly one package part differs from the original, every other part is
byte-identical, the edited word is where it was asked and nowhere else changed (the text of every OTHER shape/paragraph is identical before and after),
and python-pptx / python-docx still open the file. Files that the service refuses (a figure linked to a source, text that spans runs it cannot split)
are counted as refusals, not passes.
"""

import json
import random
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from workroom.workroom_core.service import Service, ServiceError  # noqa: E402

WORD = re.compile(r"[A-Za-z]{5,12}")


def texts(path: Path) -> list[str]:
    if path.suffix.lower() == ".docx":
        from docx import Document

        return [p.text for p in Document(str(path)).paragraphs]
    from pptx import Presentation

    prs = Presentation(str(path))
    return [sh.text_frame.text for s in prs.slides for sh in s.shapes if getattr(sh, "has_text_frame", False) and sh.has_text_frame]


def main() -> None:
    args = sys.argv[1:]
    n = int(args[args.index("--n") + 1]) if "--n" in args else 50
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 7
    for flag in ("--n", "--seed"):
        if flag in args:
            i = args.index(flag)
            del args[i : i + 2]
    out_path, folders = Path(args[0]), [Path(a) for a in args[1:]]
    rng = random.Random(seed)
    files = sorted(p for f in folders for p in f.rglob("*") if p.suffix.lower() in (".pptx", ".docx") and "__E" not in p.name and p.stat().st_size < 4_000_000)
    rng.shuffle(files)
    tmp = Path(tempfile.mkdtemp(prefix="wr_pe_"))
    root = tmp / "proj"
    root.mkdir()
    svc = Service(tmp / "state")
    pid = svc.add_project(str(root))["project"]
    rows = []
    for src in files:
        if sum(1 for r in rows if r["result"] == "pass") >= n:
            break
        name = f"f{len(rows)}{src.suffix.lower()}"
        shutil.copy2(src, root / name)
        row = {"source": src.name, "file": name, "result": "skipped"}
        try:
            try:
                before_text = texts(root / name)
            except Exception as exc:  # noqa: BLE001  a file the reference readers cannot open (fuzzer output, damaged) is not a test of editing
                row.update(result="skipped", why=f"input not readable by python-pptx/docx: {type(exc).__name__}")
                rows.append(row)
                (root / name).unlink(missing_ok=True)
                continue
            words = [(i, m.group(0)) for i, t in enumerate(before_text) for m in WORD.finditer(t)]
            if not words:
                row["why"] = "no editable word"
                rows.append(row)
                (root / name).unlink()
                continue
            _, word = rng.choice(words)
            found = svc.find_text(pid, name, word)["matches"]
            if not found:
                row["why"] = "find_text did not locate the word"
                row["result"] = "fail"
                rows.append(row)
                (root / name).unlink()
                continue
            hit = found[0]
            new = word[::-1] if word[::-1] != word else word + "x"
            original = (root / name).read_bytes()
            staged = svc.stage_text_edit(pid, name, hit["locator"], word, new)
            svc.approve_and_publish(pid, staged["release_id"], staged["digest"])
            after = (root / name).read_bytes()
            za, zb = zipfile.ZipFile(__import__("io").BytesIO(original)), zipfile.ZipFile(__import__("io").BytesIO(after))
            differing = [x for x in za.namelist() if x not in zb.namelist() or za.read(x) != zb.read(x)]
            added = [x for x in zb.namelist() if x not in za.namelist()]
            after_text = texts(root / name)
            changed_blocks = [i for i, (a, b) in enumerate(zip(before_text, after_text)) if a != b]
            ok = len(differing) == 1 and not added and len(before_text) == len(after_text) and len(changed_blocks) == 1 and new in after_text[changed_blocks[0]]
            row.update(word=word, new=new, parts_differing=differing, blocks_changed=len(changed_blocks), result="pass" if ok else "fail")
        except ServiceError as exc:
            row.update(result="refused", why=str(exc)[:120])
        except Exception as exc:  # noqa: BLE001
            row.update(result="fail", why=f"{type(exc).__name__}: {str(exc)[:120]}")
        rows.append(row)
        (root / name).unlink(missing_ok=True)
    tally = {k: sum(1 for r in rows if r["result"] == k) for k in ("pass", "fail", "refused", "skipped")}
    print(json.dumps(tally))
    for r in rows:
        if r["result"] in ("fail",):
            print("FAIL", r)
    out_path.write_text(json.dumps({"seed": seed, "tally": tally, "rows": rows}, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if tally["fail"] else 0)


if __name__ == "__main__":
    main()
