import json
from pathlib import Path

from workroom.adapters.commands import APPROVE, CANCEL, make_approve_command
from workroom.tests.test_book import workbook
from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell
from workroom.workroom_core.service import Service


def staged(tmp_path: Path, approvers=frozenset()):
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "data" / "data.xlsx").write_bytes(workbook(120, 0.25))
    (root / "report.xlsx").write_bytes(workbook(120, 0.25))
    (root / "workroom.json").write_text(json.dumps({"targets": ["report.xlsx"]}))
    svc = Service(tmp_path / "state", approvers)
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    src = root / "data" / "data.xlsx"
    src.write_bytes(patch_numeric_cell(src.read_bytes(), "Results", "C2", 150))
    return svc, root, pid, svc.stage(pid)


class Source:
    def __init__(self, uid: str) -> None:
        self.user_id = uid


def run(svc, answer, approvers, platform=None, source=None, args=""):
    asked: list[str] = []

    def ask(q, choices):
        asked.append(q)
        return answer

    handler = make_approve_command(lambda: svc, ask, lambda: approvers)
    return handler(args, source=source, platform=platform), asked


def test_local_session_approves_and_publishes(tmp_path: Path) -> None:
    svc, root, pid, st = staged(tmp_path)
    out, asked = run(svc, APPROVE, [])
    assert out.startswith("Published") and st["digest"][:12] in asked[0]
    from openpyxl import load_workbook

    assert load_workbook(root / "report.xlsx").active["C2"].value == 150


def test_cancel_and_no_answer_change_nothing(tmp_path: Path) -> None:
    svc, root, pid, st = staged(tmp_path)
    before = (root / "report.xlsx").read_bytes()
    assert run(svc, CANCEL, [])[0] == "Nothing was changed."
    assert "No answer" in run(svc, None, [])[0]
    assert (root / "report.xlsx").read_bytes() == before


def test_unlisted_chat_user_is_refused_without_a_prompt(tmp_path: Path) -> None:
    svc, root, pid, st = staged(tmp_path)
    out, asked = run(svc, APPROVE, [], platform="telegram", source=Source("42"))
    assert "not allowed" in out and asked == []


def test_listed_telegram_user_can_approve(tmp_path: Path) -> None:
    svc, root, pid, st = staged(tmp_path, frozenset({"telegram:42"}))
    out, _ = run(svc, APPROVE, ["telegram:42"], platform="telegram", source=Source("42"))
    assert out.startswith("Published")


def test_nothing_waiting_and_bad_arguments(tmp_path: Path) -> None:
    svc, root, pid, st = staged(tmp_path)
    assert run(svc, APPROVE, [], args="junk")[0].startswith("Usage")
    run(svc, APPROVE, [])
    assert run(svc, APPROVE, [])[0] == "No Workroom release is waiting for approval."
