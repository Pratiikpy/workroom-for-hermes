"""Adversarial paths for create releases: nothing may be written outside the project, onto Workroom's own files, or to a name Windows treats specially."""
import os
import sys
from pathlib import Path

import pytest

from workroom.tests.test_create_flow import SPEC, _svc

BS, NUL, LF = chr(92), chr(0), chr(10)
BAD = ["../evil.pptx", "a/../../evil.pptx", "/abs.pptx", "C:/evil.pptx", "C:evil.pptx", "pages" + BS + "x.pptx", "x.pptx.", "x.pptx ", "CON.pptx", "nul.pptx",
       "a/PRN.pptx", "x" + NUL + ".pptx", "workroom.manifest.json.pptx", ".workroom/x.pptx", "a//b.pptx", "", ".pptx", "x" * 300 + ".pptx", "dir/", "x.PPTX" + LF]


@pytest.mark.parametrize("path", BAD)
def test_hostile_create_paths_are_refused_and_nothing_is_written(tmp_path: Path, path: str) -> None:
    svc, pid, root = _svc(tmp_path)
    out = svc.create_from_spec(pid, {**SPEC, "path": path})
    assert out["state"] == "refused", (path, out)
    assert not [p for p in tmp_path.rglob("*") if p.name.endswith("evil.pptx")]
    assert not any(p.name.lower().startswith(("con", "nul", "prn")) for p in root.rglob("*"))


@pytest.mark.skipif(sys.platform == "win32" and not os.environ.get("WORKROOM_TEST_SYMLINKS"), reason="creating symlinks needs privileges on Windows")
def test_a_symlinked_folder_cannot_be_used_to_escape_the_project(tmp_path: Path) -> None:
    svc, pid, root = _svc(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    out = svc.create_from_spec(pid, {**SPEC, "path": "link/x.pptx"})
    if out["state"] == "awaiting_approval":
        with pytest.raises(Exception):
            svc.approve_and_publish(pid, out["release_id"], out["digest"])
    assert not (outside / "x.pptx").exists()
