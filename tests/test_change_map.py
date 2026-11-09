"""The change map is the Changes inbox as a graph, and every edge in it is a link the project really holds."""
from pathlib import Path

from xlsxwriter import Workbook

from workroom.tests.test_calculations import _deck
from workroom.tests.test_source_health import LINES, _workbook
from workroom.workroom_core.service import Service


def _service(tmp_path: Path, lines=LINES) -> tuple[Service, str, Path]:
    root = tmp_path / "proj"
    root.mkdir()
    _workbook(root, 14_000_000)
    _deck(root, lines)
    svc = Service(tmp_path / "state")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    return svc, pid, root


def _independent_expectation(svc: Service, pid: str, root: Path) -> dict[int, tuple[str, str, str]]:
    """Which links the workbook now disagrees with, read straight from the tie table and the workbook, not from the inbox."""
    from workroom.workroom_core.ooxml.package import open_package
    from workroom.workroom_core.ooxml.xlsx import index_workbook

    cells = {(c.file, c.sheet, c.ref): c.value for c in index_workbook(open_package((root / "results.xlsx").read_bytes()), file="results.xlsx")}
    proj, _ = svc._open(pid)
    out = {}
    for t in proj.ties(("accepted", "confirmed", "held")):
        now = cells.get((t.src_file, t.sheet, t.ref))
        if now is None or now != t.linked_value:
            out[t.id] = (t.src_file, t.sheet, t.ref)
    svc._close_opened()
    return out


def test_every_edge_is_a_link_the_project_holds_and_every_changed_link_is_an_edge(tmp_path: Path) -> None:
    svc, pid, root = _service(tmp_path)
    assert svc.change_map(pid)["edges"] == [], "nothing changed, so nothing is drawn"
    _workbook(root, 15_000_000)
    m = svc.change_map(pid)
    expected = _independent_expectation(svc, pid, root)
    assert sorted(e["tie_id"] for e in m["elements"]) == sorted(expected)
    assert len(m["edges"]) == len(m["elements"]) == len(expected) == 1
    source = next(s for s in m["sources"] if s["id"] == m["edges"][0]["from"])
    assert (source["file"], source["sheet"], source["ref"]) == next(iter(expected.values()))
    assert (source["old"], source["new"]) == (14_000_000, 15_000_000)
    el = m["elements"][0]
    assert el["state"] == "update" and el["before"] == "$14.0 million" and el["after"] == "$15.0 million"
    assert m["totals"] == {"sources": 1, "documents": 1, "places": 1, "update": 1, "held": 0, "blocked": 0}
    assert m["documents"][0]["name"] == "board.pptx" and m["documents"][0]["elements"] == 1


def test_a_missing_source_is_drawn_as_its_own_node_and_its_place_as_blocked(tmp_path: Path) -> None:
    svc, pid, root = _service(tmp_path)
    _workbook(root, 15_000_000, income=None)
    m = svc.change_map(pid)
    expected = _independent_expectation(svc, pid, root)
    assert sorted(e["tie_id"] for e in m["elements"]) == sorted(expected) and len(expected) == 2
    states = {e["tie_id"]: e["state"] for e in m["elements"]}
    assert sorted(states.values()) == ["blocked", "update"]
    ghost = next(s for s in m["sources"] if s["missing"])
    assert ghost["kind"] == "missing" and (ghost["sheet"], ghost["ref"]) == ("Results", "C3") and ghost["new"] is None
    blocked = next(e for e in m["elements"] if e["state"] == "blocked")
    assert blocked["source"] == ghost["id"]
    assert m["totals"]["blocked"] == 1 and m["totals"]["update"] == 1


def test_a_finding_is_attached_to_the_place_it_is_about_and_the_rest_are_listed_apart(tmp_path: Path) -> None:
    svc, pid, root = _service(tmp_path)
    _workbook(root, 14_000_000_000)  # a thousand times: raises the implausible-move finding on the first figure's place
    m = svc.change_map(pid)
    finding = next(f for f in m["findings"] if f["kind"] == "source_implausible")
    attached = [e for e in m["elements"] if finding["id"] in e["flags"]]
    assert len(attached) == 1 and attached[0]["before"] == "$14.0 million"
    assert finding["id"] not in m["unattached_findings"]
    assert all(finding["id"] not in e["flags"] for e in m["elements"] if e is not attached[0])


def test_the_map_route_is_declared_on_the_dashboard_api() -> None:
    src = (Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py").read_text(encoding="utf-8")
    assert '@router.post("/change-map")' in src
