"""Helper agents started by the main agent are recorded in the Room of the project the session works in, from Hermes's own subagent events."""

from pathlib import Path

from workroom.adapters import session_cwd
from workroom.adapters.crew import files_touched, make_crew_hooks
from workroom.tests.test_room import project


def hooks(svc):
    return make_crew_hooks(lambda: svc.projects(), lambda pid, kind, **kw: svc.crew_event(pid, kind, **kw))


def test_a_helper_is_recorded_from_start_to_stop_with_the_files_it_touched(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    start, stop = hooks(svc)
    session_cwd.use(lambda: str(root))
    try:
        start(parent_session_id="p1", child_subagent_id="c1", child_role="researcher", child_goal="Read the quarterly workbook and summarise it")
        working = svc.room_overview(pid)["crew"]
        assert [c["status"] for c in working] == ["working"] and working[0]["role"] == "researcher"
        history = [{"tool_name": "write_file", "tool_input": {"targets": {"path": str(root / "notes" / "summary.md")}}},
                   {"tool_name": "read_file", "tool_input": {"targets": {"path": str(root / "results.xlsx")}}},
                   {"tool_name": "write_file", "tool_input": {"targets": {"path": str(tmp_path / "elsewhere" / "other.md")}}},
                   {"tool_name": "write_file", "tool_input": {"targets": {"path": "../climbs-out.md"}}}]
        stop(parent_session_id="p1", child_subagent_id="c1", child_status="completed", child_summary="Revenue rose 12%.", duration_ms=4200, tool_call_history=history)
    finally:
        session_cwd.use(None)
    done = svc.room_overview(pid)["crew"]
    assert len(done) == 1 and done[0]["status"] == "completed" and done[0]["summary"] == "Revenue rose 12%." and done[0]["duration_ms"] == 4200
    assert done[0]["files"] == ["notes/summary.md"]  # only a file inside the project that a writing tool named
    assert [e["event"] for e in svc.room_overview(pid)["audit"] if e["event"].startswith("crew")] == ["crew_start", "crew_stop"]


def test_a_session_outside_every_project_records_nothing_and_a_broken_event_never_raises(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    start, stop = hooks(svc)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    session_cwd.use(lambda: str(outside))
    try:
        assert start(parent_session_id="p", child_subagent_id="c", child_role="x", child_goal="g") is None
        assert stop(parent_session_id="p", child_subagent_id="c", child_status="completed", tool_call_history="not a list") is None
    finally:
        session_cwd.use(None)
    assert svc.room_overview(pid)["crew"] == []
    assert files_touched(None, root) == [] and files_touched([{"tool_name": "write_file"}, 5], root) == []


def test_two_helpers_stop_in_either_order_and_each_closes_its_own_row(tmp_path: Path) -> None:
    root, svc, pid = project(tmp_path)
    start, stop = hooks(svc)
    session_cwd.use(lambda: str(root))
    try:
        start(parent_session_id="p", child_subagent_id="a", child_role="writer", child_goal="Draft")
        start(parent_session_id="p", child_subagent_id="b", child_role="checker", child_goal="Check")
        stop(parent_session_id="p", child_subagent_id="b", child_status="failed", child_summary="no access")
        stop(parent_session_id="p", child_subagent_id="a", child_status="completed", child_summary="drafted")
    finally:
        session_cwd.use(None)
    by_role = {c["role"]: c for c in svc.room_overview(pid)["crew"]}
    assert by_role["checker"]["status"] == "failed" and by_role["writer"]["status"] == "completed" and by_role["writer"]["summary"] == "drafted"
