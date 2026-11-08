from workroom.workroom_core.status import collect_status


def test_status_reports_skeleton_stage() -> None:
    status = collect_status(data_dir="x")
    assert status["ready"] is True
    assert status["stage"] == "skeleton"
    assert status["data_dir"] == "x"
