import json
import shutil
from pathlib import Path

import pytest

from workroom.tests.test_flagship_headless import change_source, make_deck, make_workbook
from workroom.workroom_core.service import Service, ServiceError
from workroom.workroom_core.store.manifest import MANIFEST_NAME, Manifest

RECOVERY = "recovery mode"


def published(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "results.xlsx").write_bytes(make_workbook())
    (root / "deck.pptx").write_bytes(make_deck())
    svc = Service(tmp_path / "data")
    pid = svc.add_project(str(root))["project"]
    svc.discover(pid)
    change_source(root, "C2", 150)
    st = svc.stage(pid)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    return svc, pid, root, tmp_path / "data"


def try_stage(svc: Service, pid: str, root: Path, value: float) -> None:
    change_source(root, "C2", value)
    svc.stage(pid)


def test_a_normal_release_writes_a_verified_manifest_and_allows_the_next_release(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    m = Manifest(root / MANIFEST_NAME, svc._key, pid)
    assert m.counter() == 1 and m.published()[0].data["principal"]
    try_stage(svc, pid, root, 170)


def test_an_edited_entry_is_refused(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    doc = json.loads((root / MANIFEST_NAME).read_text())
    doc["entries"][0]["data"]["principal"] = "someone:else"
    (root / MANIFEST_NAME).write_text(json.dumps(doc))
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)


def test_removing_the_entries_is_refused_even_with_a_fixed_head(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    doc = json.loads((root / MANIFEST_NAME).read_text())
    doc.update(entries=[], head="0" * 64, counter=0)
    (root / MANIFEST_NAME).write_text(json.dumps(doc))
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)  # valid by itself, but its counter disagrees with the journal and the anchor


def test_a_manifest_signed_with_another_key_is_refused(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    forged = Manifest(tmp_path / "forged.json", b"x" * 32, pid)
    forged.append("published", {"release_id": "r", "digest": "d", "principal": "attacker", "files": {}})
    shutil.copy(tmp_path / "forged.json", root / MANIFEST_NAME)
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)


def test_a_manifest_copied_from_another_project_is_refused(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    other = Manifest(tmp_path / "other.json", svc._key, "another-project")
    other.append("published", {"release_id": "r", "digest": "d", "principal": "p", "files": {}})
    shutil.copy(tmp_path / "other.json", root / MANIFEST_NAME)
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)


def test_duplicated_entries_are_refused(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    doc = json.loads((root / MANIFEST_NAME).read_text())
    doc["entries"].append(doc["entries"][0])
    (root / MANIFEST_NAME).write_text(json.dumps(doc))
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)


def test_rolling_back_only_the_manifest_is_refused(tmp_path: Path) -> None:
    svc, pid, root, _ = published(tmp_path)
    old = (root / MANIFEST_NAME).read_bytes()
    change_source(root, "C2", 170)
    st = svc.stage(pid)
    svc.approve_and_publish(pid, st["release_id"], st["digest"])
    (root / MANIFEST_NAME).write_bytes(old)
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 190)


def test_rolling_back_only_the_journal_is_refused(tmp_path: Path) -> None:
    svc, pid, root, data = published(tmp_path)
    journal = data / "projects" / pid / "journal.db"
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(journal) + suffix)
        if p.exists():
            p.unlink()
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(Service(data), pid, root, 170)


def test_a_tampered_anchor_is_refused(tmp_path: Path) -> None:
    svc, pid, root, data = published(tmp_path)
    anchor = data / "projects" / pid / "anchor.json"
    d = json.loads(anchor.read_text())
    d["counter"] = 0
    anchor.write_text(json.dumps(d))
    with pytest.raises(ServiceError, match=RECOVERY):
        try_stage(svc, pid, root, 170)


def test_a_consistent_rollback_of_every_copy_is_NOT_detected_a_documented_limit(tmp_path: Path) -> None:
    svc, pid, root, data = published(tmp_path)
    shutil.rmtree(data / "projects" / pid)
    (root / MANIFEST_NAME).unlink()
    # all mirrors now agree that no release was ever published; a MAC proves authenticity, not freshness
    fresh = Service(data)
    proj, ctl = fresh._open(pid)
    fresh._integrity(pid, proj, ctl)  # accepted: this test pins the limit stated in manifest.py and the threat model
