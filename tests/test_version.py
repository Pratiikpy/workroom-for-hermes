"""One version number everywhere: the plugin manifest, the dashboard manifest and the core."""
import json
from pathlib import Path

from workroom.workroom_core import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_the_plugin_dashboard_and_core_agree_on_the_version() -> None:
    plugin = next(line.split(":", 1)[1].strip() for line in (ROOT / "plugin.yaml").read_text(encoding="utf-8").splitlines() if line.startswith("version:"))
    dashboard = json.loads((ROOT / "dashboard" / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert plugin == dashboard == VERSION
    assert f"## {VERSION}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), "the changelog has an entry for this version"
