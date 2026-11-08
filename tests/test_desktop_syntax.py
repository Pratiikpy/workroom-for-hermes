import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "desktop" / "plugin.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_desktop_script_parses_as_an_es_module(tmp_path: Path) -> None:
    copy = tmp_path / "plugin.mjs"
    copy.write_text(PLUGIN.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(copy)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
