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


def test_the_chat_card_describes_a_create_release_as_a_new_file_with_its_figures(tmp_path: Path) -> None:
    from workroom.tests.test_create_flow import SPEC, _svc

    svc, pid, root = _svc(tmp_path)
    staged_ = svc.create_from_spec(pid, SPEC)
    out, asked = run(svc, APPROVE, [], platform="local", args=f"{pid} {staged_['release_id']}")
    assert "will create reports/q2.pptx" in asked[0] and "tied to its source" in asked[0] and "number(s) will change" not in asked[0]
    assert "$175" in asked[0] and "results.xlsx!Results!C2" in asked[0]
    assert "Created reports/q2.pptx" in out and (root / "reports/q2.pptx").exists()


def test_the_chat_card_describes_an_edited_page_and_an_export(tmp_path: Path) -> None:
    from workroom.tests.test_scene_flow import SPEC as SCENE_SPEC
    from workroom.tests.test_create_flow import _svc

    svc, pid, root = _svc(tmp_path)
    made = svc.create_from_spec(pid, SCENE_SPEC)
    svc.approve_and_publish(pid, made["release_id"], made["digest"])
    svc.scene_apply(pid, "pages/q2.scene.json", 0, [{"op": "update", "id": "title", "set": {"x": 90}}])
    saved = svc.scene_save(pid, "pages/q2.scene.json")
    out, asked = run(svc, CANCEL, [], platform="local", args=f"{pid} {saved['release_id']}")
    assert "edits to pages/q2.scene.json" in asked[0] and "number(s) will change" not in asked[0]
    assert out == "Nothing was changed."


def test_watch_command_prints_the_wrapper_and_the_cron_line_without_changing_anything(tmp_path: Path) -> None:
    from workroom.adapters.commands import make_watch_command

    svc, root, pid, _ = staged(tmp_path)
    out = make_watch_command(lambda: svc)(pid)
    assert "hermes cron create" in out and "--no-agent" in out and f"workroom-watch-{pid}.py" in out and pid in out
    assert "never approves" in out
    assert "not a known project" in make_watch_command(lambda: svc)("nope")
    assert "Usage" in make_watch_command(lambda: svc)("")


def test_a_chat_user_who_is_not_an_approver_cannot_approve_a_create_release_or_see_its_card(tmp_path: Path) -> None:
    from workroom.tests.test_create_flow import SPEC, _workbook

    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root, 175)
    svc = Service(tmp_path / "state", frozenset({"telegram:111"}))
    pid = svc.add_project(str(root))["project"]
    staged_ = svc.create_from_spec(pid, SPEC)
    out, asked = run(svc, APPROVE, ["telegram:111"], platform="telegram", source=Source("999"), args=f"{pid} {staged_['release_id']}")
    assert "not allowed to approve" in out and asked == [], "no card is shown and no question is asked"
    assert not (root / "reports/q2.pptx").exists() and svc.awaiting(pid), "nothing was written and the release is still waiting"
    ok, asked2 = run(svc, APPROVE, ["telegram:111"], platform="telegram", source=Source("111"), args=f"{pid} {staged_['release_id']}")
    assert "Created reports/q2.pptx" in ok and asked2 and (root / "reports/q2.pptx").exists()
