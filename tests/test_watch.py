"""Unattended watch: stage one release when sources changed, say nothing otherwise, never approve."""
import subprocess
import sys
from pathlib import Path

from workroom.tests.test_create_flow import SPEC, _svc, _workbook

WATCH = Path(__file__).resolve().parents[1] / "scripts" / "watch.py"


def run(data: Path, project: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(WATCH), "--data-dir", str(data), "--project", project, *extra], capture_output=True, text=True, timeout=120)


def test_silent_when_nothing_changed_and_stages_one_release_when_it_did(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, made["release_id"], made["digest"])
    data = tmp_path / "state"
    first = run(data, pid)
    assert first.returncode == 0 and first.stdout.strip() == ""
    _workbook(root, 190)
    second = run(data, pid)
    assert second.returncode == 0 and "waiting for your approval" in second.stdout and "$175" in second.stdout and "$190" in second.stdout
    assert "/workroom-approve" in second.stdout
    awaiting = svc.awaiting(pid)
    assert len(awaiting) == 1 and not (root / "pages").exists()
    assert "$190" not in str(list(root.rglob("*.pptx")))  # nothing was written to the project


def test_running_again_does_not_stage_a_duplicate(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SPEC)
    svc.approve_and_publish(pid, made["release_id"], made["digest"])
    _workbook(root, 190)
    data = tmp_path / "state"
    run(data, pid)
    again = run(data, pid)
    assert again.returncode == 0 and "already waiting" in again.stdout
    assert len(svc.awaiting(pid)) == 1


def test_a_bad_project_reports_an_error_and_a_nonzero_exit(tmp_path: Path) -> None:
    _svc(tmp_path)
    bad = run(tmp_path / "state", "nope")
    assert bad.returncode == 1 and "nope" in (bad.stdout + bad.stderr)
