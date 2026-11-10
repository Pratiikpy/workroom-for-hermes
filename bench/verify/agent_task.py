"""One open task given to the real Hermes agent in an empty registered project, with every file and Workroom action recorded for judging.

    python agent_task.py <name> <model> <provider> <toolsets> "<prompt with {root} and {pid}>"

Used for T1-style tasks of the acceptance suite. It reports the tools called, the files the project holds afterwards (with sizes), the releases waiting, and the
agent's final answer; the verdict on quality is a human reading of that output, not a number.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOUS = HERE.parents[2]
sys.path.insert(0, str(NOUS))

from workroom.workroom_core.service import Service  # noqa: E402

HOME = Path(os.environ.get("WORKROOM_AGENT_HOME", str(NOUS / ".hermes-test")))


def main() -> None:
    name, model, provider, toolsets, prompt = sys.argv[1:6]
    root = Path(tempfile.mkdtemp(prefix=f"agent_{name}_"))
    svc = Service(HOME / "plugin-data" / "workroom")
    pid = svc.add_project(str(root))["project"]
    env = {**os.environ, "HERMES_HOME": str(HOME), "PYTHONIOENCODING": "utf-8"}
    cmd = [str(NOUS / ".hermes-test" / "bin" / "hermes.exe"), "chat", "-q", prompt.format(root=root, pid=pid), "--provider", provider, "-m", model, "-t", toolsets,
           "--format", "stream-json", "--max-turns", os.environ.get("MAX_TURNS", "30"), "--accept-hooks", "--yolo"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1500, encoding="utf-8", errors="replace")
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    calls = [str((e.get("input") or {}).get("command") or e.get("name") or e.get("tool") or "")[:90] for e in events if e.get("type") == "tool_use"]
    names = [e.get("name") or e.get("tool") for e in events if e.get("type") == "tool_use"]
    final = ""
    for e in reversed(events):
        for key in ("content", "text", "message", "final"):
            if isinstance(e.get(key), str) and len(e[key]) > 20:
                final = e[key]
                break
        if final:
            break
    report = {
        "task": name, "model": model, "seconds": round(time.time() - t0, 1), "exit": proc.returncode, "tool_names": names,
        "files": {p.relative_to(root).as_posix(): p.stat().st_size for p in root.rglob("*") if p.is_file()},
        "releases_waiting": [{"id": a["release_id"][:8], "state": a["state"], "created": bool(a.get("created"))} for a in svc.awaiting(pid)],
        "figure_proofs": [{"path": d["path"], "proof": d.get("proof")} for d in svc.deliverables(pid)],
        "final_answer": final[:2500], "first_commands": calls[:12],
    }
    out = NOUS / "research" / "corpus" / "agent_runs"
    out.mkdir(exist_ok=True)
    (out / f"task_{name}_{model}.report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    (out / f"task_{name}_{model}.jsonl").write_text(proc.stdout, encoding="utf-8")
    print(json.dumps(report, indent=1)[:6000])
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
