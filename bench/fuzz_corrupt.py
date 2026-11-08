"""Break it on purpose: corrupt real Office files and require a clean refusal, never a crash, hang or silent wrong output."""

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.workroom_core.ooxml.book import Book  # noqa: E402
from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402
from workroom.workroom_core.ooxml.pptx import Deck  # noqa: E402
from workroom.workroom_core.ooxml.runs import EditError  # noqa: E402
from workroom.workroom_core.ooxml.package import PackageError  # noqa: E402

CLEAN = (EditError, PackageError)


def mutate(data: bytes, rnd: random.Random) -> bytes:
    kind = rnd.choice(["truncate", "flip", "zero", "splice"])
    b = bytearray(data)
    if kind == "truncate":
        return bytes(b[: rnd.randint(1, max(1, len(b) - 1))])
    if kind == "flip":
        for _ in range(rnd.randint(1, 40)):
            b[rnd.randrange(len(b))] ^= 1 << rnd.randrange(8)
    elif kind == "zero":
        i = rnd.randrange(len(b))
        b[i : i + rnd.randint(1, 512)] = b"\x00" * min(512, len(b) - i)
    else:
        i = rnd.randrange(len(b))
        b[i:i] = bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 64)))
    return bytes(b)


def main(files: list[str], per_file: int = 25) -> int:
    rnd = random.Random(5)
    counts = {"clean_refusal": 0, "opened_and_serialized": 0, "unexpected": 0, "slow": 0}
    bad = []
    for f in files:
        path = Path(f)
        cls = {".docx": Doc, ".pptx": Deck, ".xlsx": Book}[path.suffix.lower()]
        data = path.read_bytes()
        for _ in range(per_file):
            m = mutate(data, rnd)
            t = time.time()
            try:
                obj = cls(m)
                list(obj.mentions())
                obj.serialize()
                counts["opened_and_serialized"] += 1
            except CLEAN:
                counts["clean_refusal"] += 1
            except Exception as exc:  # noqa: BLE001
                counts["unexpected"] += 1
                bad.append(f"{path.name}: {type(exc).__name__}: {str(exc)[:80]}")
            if time.time() - t > 5:
                counts["slow"] += 1
    counts["files"] = len(files)
    counts["mutations"] = len(files) * per_file
    print(json.dumps(counts))
    for b in sorted(set(bad))[:15]:
        print("UNEXPECTED", b)
    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
