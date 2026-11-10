"""Print the run score of a Workroom project as JSON, for an evaluation or reward harness.

    python score.py --project <id or folder> [--data-dir <Workroom data dir>]

Read-only: it measures how many of the agent's figures are backed by evidence and whether its decks have blocking layout faults, with the formula in the
output. It does not judge usefulness or substance.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print a Workroom project's run score as JSON.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--data-dir")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root.parent))
    from importlib import import_module

    service = import_module(f"{root.name}.workroom_core.service")
    folder = Path(args.data_dir or os.environ.get("WORKROOM_DATA_DIR") or Path.home() / ".workroom")
    try:
        print(json.dumps(service.Service(folder).run_score(args.project), indent=1))
    except service.ServiceError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
