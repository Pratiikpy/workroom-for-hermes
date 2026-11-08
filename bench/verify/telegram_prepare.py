"""Prepare a release that needs an acknowledgement, for the real Telegram approval check.

    python telegram_prepare.py <folder to create>

Builds the quarterly project from real FRED series in the folder, registers it in the test Hermes home, puts the next quarter in the
workbook and stages a roll forward. Prints the project id, the release id and how many flagged sentences need reading.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))

import cycles  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

NOUS = HERE.parents[2]


def main(folder: str) -> None:
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    kind = cycles.QuarterlyDeck(NOUS / "research" / "corpus" / "fred", "Q1 2025", "Q3 2026")
    kind.workbook(root, 0)
    kind.build(root)
    svc = Service(NOUS / ".hermes-test" / "plugin-data" / "workroom", approvers=frozenset({"telegram:1962993868"}))
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    cycles.settle(svc, pid)
    kind.workbook(root, 1)
    staged = svc.stage_rollforward(pid)
    flags = staged["flags"]
    print(json.dumps({"project": pid, "release": staged["release_id"], "digest": staged["digest"], "flags": {s: sum(1 for f in flags if f["severity"] == s) for s in ("high", "medium", "info")}}))


if __name__ == "__main__":
    main(sys.argv[1])
