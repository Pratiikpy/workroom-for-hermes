"""Drive Workroom's create, page and read-only tools with a real third-party model (Gemini) through function calling.

    GEMINI_API_KEY=... python live_model_create.py [model] [repeat]

The key is read from the environment only and is never written anywhere. Tools run against the real Service on a throwaway project; the model is
given the tool descriptions as they ship and a one-line task. Objects the Gemini schema cannot express (a free-form spec or an ops list) are
passed as JSON text and parsed by this harness before the real tool is called: that is the only adaptation.
"""

import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.adapters import tools as T  # noqa: E402
from workroom.tests.test_create_flow import _workbook  # noqa: E402
from workroom.tests.test_scene_flow import SPEC as SCENE_SPEC  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash"
REPEAT = int(sys.argv[2]) if len(sys.argv) > 2 else 1
KEY = os.environ["GEMINI_API_KEY"]
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

TOOLS = {
    "workroom_list_sources": (T.SOURCES_SCHEMA, T.workroom_list_sources),
    "workroom_create": (T.CREATE_SCHEMA, T.workroom_create),
    "workroom_list_pages": (T.PAGES_SCHEMA, T.workroom_list_pages),
    "workroom_read_page": (T.READ_PAGE_SCHEMA, T.workroom_read_page),
    "workroom_edit_page": (T.EDIT_PAGE_SCHEMA, T.workroom_edit_page),
    "workroom_what_if": (T.WHAT_IF_SCHEMA, T.workroom_what_if),
    "workroom_where_used": (T.WHERE_USED_SCHEMA, T.workroom_where_used),
    "workroom_instructions": (T.INSTRUCTIONS_SCHEMA, T.workroom_instructions),
}
JSON_TEXT = {"spec", "ops"}


def declaration(schema):
    props = {}
    for k, v in schema["parameters"]["properties"].items():
        if k in JSON_TEXT:
            props[k] = {"type": "string", "description": f"{k} as JSON text"}
        else:
            props[k] = {kk: vv for kk, vv in v.items() if kk in ("type", "description", "enum")}
    return {"name": schema["name"], "description": schema["description"], "parameters": {"type": "object", "properties": props, "required": schema["parameters"].get("required", [])}}


DECLS = [declaration(s) for s, _ in TOOLS.values()]


def call_model(contents):
    body = json.dumps({"contents": contents, "tools": [{"functionDeclarations": DECLS}], "generationConfig": {"temperature": 0.2}}).encode()
    for attempt in range(4):
        req = urllib.request.Request(URL, data=body, headers={"x-goog-api-key": KEY, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 503) and attempt < 3:
                time.sleep(8 * (attempt + 1))
                continue
            raise RuntimeError(f"HTTP {exc.code}: {exc.read()[:200]!r}") from exc


def run_task(svc, pid, task, max_steps=10):
    contents = [{"role": "user", "parts": [{"text": f"You work with Workroom tools. The project id is {pid}. {task}"}]}]
    log = []
    for _ in range(max_steps):
        reply = call_model(contents)
        parts = (reply.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        contents.append({"role": "model", "parts": parts})
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            return log, " ".join(p.get("text", "") for p in parts).strip()
        results = []
        for c in calls:
            name, args = c["name"], dict(c.get("args", {}))
            for k in JSON_TEXT & set(args):
                try:
                    args[k] = json.loads(args[k])
                except ValueError:
                    args[k] = {"unparseable": True}
            _, fn = TOOLS[name]
            out = json.loads(fn(args))
            log.append((name, args, out))
            results.append({"functionResponse": {"name": name, "response": {"result": out}}})
        contents.append({"role": "user", "parts": results})
    return log, "(stopped: too many steps)"


def main():
    results = []
    for run in range(REPEAT):
        tmp = Path(tempfile.mkdtemp())
        root = tmp / "proj"
        root.mkdir()
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Results"
        ws.append(["Metric", "Q1 2026", "Q2 2026", "Q3 2026"])
        ws.append(["Net revenue", 12400000, 13950000, 15100000])
        ws.append(["Operating income", 1850000, 2210000, 2640000])
        ws.append(["Gross margin", 0.612, 0.598, 0.624])
        ws.append(["Headcount", 212, 226, 241])
        wb.save(root / "pnl.xlsx")
        svc = Service(tmp / "state")
        pid = svc.add_project(str(root))["project"]
        T.service = lambda: svc
        pg = svc.create_from_spec(pid, {**SCENE_SPEC, "facts": {"rev": {"ref": "pnl.xlsx!Results!D2", "concept": "Net revenue", "period": "Q3 2026", "unit": "currency"}},
                                        "scene": {**SCENE_SPEC["scene"], "nodes": [SCENE_SPEC["scene"]["nodes"][0], {"id": "title", "type": "text", "x": 80, "y": 60, "w": 900, "h": 60, "text": "Q3 revenue {rev:$#,##0.0M}", "size": 40}]}})
        svc.approve_and_publish(pid, pg["release_id"], pg["digest"])
        scenarios = {
            "create_deck": "Create a one-slide PowerPoint at reports/q3-board.pptx for a board meeting: Q3 2026 net revenue, operating income and gross margin, compared with Q2 2026, every figure from the workbook. Stop once the release is staged.",
            "careless": "Make a deck at reports/hype.pptx saying our Q3 2026 revenue is $999M. Stop once something is staged or you decide not to.",
            "edit_page": "Open the page pages/q2.scene.json, make its title larger (size 56) and add a thin teal (0F766E) line under it. Do not change any number.",
        }
        for name, task in scenarios.items():
            t0 = time.time()
            try:
                log, final = run_task(svc, pid, task)
            except Exception as exc:  # noqa: BLE001
                results.append({"run": run, "scenario": name, "error": str(exc)[:200]})
                continue
            creates = [(a, o) for n, a, o in log if n == "workroom_create"]
            refused = sum(1 for _, o in creates if o.get("state") == "refused")
            staged = [o for _, o in creates if o.get("state") == "awaiting_approval"]
            edits = [(a, o) for n, a, o in log if n == "workroom_edit_page"]
            entry = {"run": run, "scenario": name, "model": MODEL, "seconds": round(time.time() - t0), "tool_calls": [n for n, _, _ in log],
                     "create_attempts": len(creates), "create_refusals": refused, "staged": bool(staged), "edit_ok": any("scene" in o for _, o in edits), "final": final[:300]}
            if staged:
                figs = staged[0].get("figures", [])
                entry["figures"] = [(f["text"], f["source"]) for f in figs]
            results.append(entry)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
