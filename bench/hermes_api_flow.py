"""Drive the Workroom routes of a running Hermes API end to end and check the files afterwards.

Usage: python hermes_api_flow.py <port> <session-token>
The routes are called exactly as the Desktop would call them, with the Hermes session header.
"""

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.tests.test_flagship_headless import change_source, deck_texts, make_deck, make_workbook  # noqa: E402

PORT, TOKEN = sys.argv[1], sys.argv[2]
BASE = f"http://127.0.0.1:{PORT}/api/plugins/workroom"
results: list[tuple[str, bool, str]] = []


def call(path: str, body: dict | None = None, token: str | None = TOKEN) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET")
    if token:
        req.add_header("X-Hermes-Session-Token", token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


root = Path(tempfile.mkdtemp(prefix="wr_flow_"))
(root / "results.xlsx").write_bytes(make_workbook())
(root / "deck.pptx").write_bytes(make_deck())
before = (root / "deck.pptx").read_bytes()

check("no token is refused", call("/status", token=None)[0] == 401)
check("wrong token is refused", call("/status", token="nope")[0] == 401)
code, body = call("/status")
check("status with token", code == 200 and body.get("ready") is True, str(body))
code, body = call("/projects", {"folder": str(root)})
check("add project", code == 200 and "project" in body, str(body))
pid = body["project"]
check("add a missing folder is refused", call("/projects", {"folder": str(root / "nope")})[0] == 400)
code, body = call("/discover", {"project": pid})
check("discover finds ties", code == 200 and body["accepted"] >= 2, str(body))
check("discover wrote nothing to the deck", (root / "deck.pptx").read_bytes() == before)
check("stage with nothing changed is refused", call("/stage", {"project": pid})[0] == 400)
change_source(root, "C2", 150)
code, body = call("/plan", {"project": pid})
check("plan lists exactly the tied change", code == 200 and [c["new_text"] for c in body["changes"]] == ["150"], str(body))
code, body = call("/stage", {"project": pid})
check("stage prepares a release", code == 200 and body.get("state") == "awaiting_approval", str(body))
rid, digest = body["release_id"], body["digest"]
check("staging changed no document", deck_texts(root / "deck.pptx")["Revenue line"].startswith("Revenue in Q2 was 120"))
code, _ = call("/approve", {"project": pid, "release_id": rid, "digest": "0" * 64})
check("approval with a different digest is refused", code == 400)
code, _ = call("/approve", {"project": pid, "release_id": rid, "digest": digest}, token="nope")
check("approval without a session is refused", code == 401)
check("deck still unchanged", deck_texts(root / "deck.pptx")["Revenue line"].startswith("Revenue in Q2 was 120"))
code, body = call("/approve", {"project": pid, "release_id": rid, "digest": digest})
check("approval publishes", code == 200 and body.get("state") == "published", str(body))
texts = deck_texts(root / "deck.pptx")
check("tied number changed", texts["Revenue line"].startswith("Revenue in Q2 was 150"), texts["Revenue line"])
check("decoy untouched", texts["Decoy"] == "Headcount reached 120 people")
code, _ = call("/approve", {"project": pid, "release_id": rid, "digest": digest})
check("the same approval cannot publish twice", code in (400, 500))
code, body = call("/plan", {"project": pid})
check("nothing left to change after the release", code == 200 and body["changes"] == [], str(body))

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
