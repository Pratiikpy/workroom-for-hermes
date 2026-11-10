"""A real Hermes cron run of Workroom's watch script: a source changes, the job runs unattended, one release is prepared, and the run is on record.

    python cron_watch.py

Uses the test Hermes home (C:\\Users\\prate\\nous\\.hermes-test) and its Hermes interpreter. Creates a throwaway project, a script job with no model
(`--no-agent`, delivery `local`), forces a run, ticks the scheduler once and reads the durable run record.
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
HOME = NOUS / ".hermes-test"
PY = HOME / "tools" / "python-3.14.9+20261021-win32-x64" / "python.exe"
SITE = HOME / "installs" / "c47a72f73c69678d" / "environments" / "22611b534e5345f082d96ec3a3d9c7c2" / "venv" / "Lib" / "site-packages"
ENV = {**os.environ, "HERMES_HOME": str(HOME), "PYTHONPATH": f"{NOUS / 'study-clones' / 'hermes-0.23'};{SITE};{NOUS}", "PYTHONIOENCODING": "utf-8"}
sys.path.insert(0, str(NOUS))

from workroom.tests.test_flagship_headless import change_source, make_workbook  # noqa: E402
from workroom.tests.test_docx import make_docx  # noqa: E402
from workroom.workroom_core.service import Service  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def hermes(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-m", "hermes_cli.main", *args], env=ENV, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="wr_cron_"))
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "report.docx").write_bytes(make_docx())
    original_report = (root / "report.docx").read_bytes()
    data = HOME / "plugin-data" / "workroom"
    svc = Service(data)
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    change_source(root, "C2", 150)  # the source moves after the links were found
    scripts = HOME / "scripts"
    scripts.mkdir(exist_ok=True)
    name = f"workroom-watch-{pid}.py"
    (scripts / name).write_text("\n".join([
        "import os, runpy, sys",
        f'sys.argv = ["watch.py", "--project", "{pid}", "--data-dir", r"{data}"]',
        f'runpy.run_path(r"{NOUS / "workroom" / "scripts" / "watch.py"}", run_name="__main__")']), encoding="utf-8")
    for line in hermes("cron", "list").stdout.splitlines():
        pass
    made = hermes("cron", "create", "every 6h", "--no-agent", "--script", name, "--deliver", "local", "--name", f"wr-watch-{pid}")
    check("the cron job is created", made.returncode == 0, (made.stdout + made.stderr)[-300:])
    listing = hermes("cron", "list")
    lines = listing.stdout.splitlines()
    job_id = next((lines[i - 1].split()[0] for i, line in enumerate(lines) if f"wr-watch-{pid}" in line and i > 0), "")
    check("the job is listed", bool(job_id), listing.stdout[-300:])
    ran = hermes("cron", "run", job_id) if job_id else None
    tick = hermes("cron", "tick", timeout=300)
    time.sleep(2)
    runs = hermes("cron", "runs", job_id) if job_id else None
    print((runs.stdout if runs else "")[-600:])
    awaiting = svc.awaiting(pid)
    check("a release was prepared by the unattended run", len(awaiting) == 1, str([a["state"] for a in awaiting]))
    check("the project folder was not changed by the run", (root / "report.docx").read_bytes() == original_report)
    check("the run is on record", bool(runs and runs.returncode == 0 and (job_id[:8] in runs.stdout or "success" in runs.stdout.lower() or "ok" in runs.stdout.lower())), (runs.stdout if runs else "")[-300:])
    second = hermes("cron", "run", job_id) if job_id else None
    hermes("cron", "tick", timeout=300)
    check("a second run with nothing new prepares no second release", len(svc.awaiting(pid)) == 1)
    if job_id:
        hermes("cron", "remove", job_id)
    (scripts / name).unlink(missing_ok=True)
    shutil.rmtree(root, ignore_errors=True)
    _ = (ran, tick, second)
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
    _ = json
