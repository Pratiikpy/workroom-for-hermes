from workroom.workroom_core import selftest


def test_the_bundled_selftest_passes_and_is_deterministic() -> None:
    a = selftest.run(seed=7, books=10)
    b = selftest.run(seed=7, books=10)
    assert a["passed"] and a == b
    assert a["release_recovery"]["recovered_to_all_new"] == a["release_recovery"]["crash_points"] == 15
    assert a["matching"]["accepted_wrong"] == 0 and a["matching"]["decoys_accepted"] == 0
