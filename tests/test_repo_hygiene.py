"""The repository ships readable source only: no compiled binary, no bytecode, no key or token file."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BINARY = (".dll", ".exe", ".so", ".dylib", ".pyc", ".pyd", ".o", ".a", ".class", ".jar", ".wasm", ".node", ".bin", ".pdb")
SECRET_NAMES = (".env", "secrets.json", "id_rsa", "credentials.json")


def _tracked() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True, env={"PATH": __import__("os").environ.get("PATH", "")})
    return out.stdout.splitlines()


def test_no_compiled_binary_or_bytecode_is_tracked() -> None:
    bad = [f for f in _tracked() if f.lower().endswith(BINARY)]
    assert bad == [], f"compiled files must not be committed: {bad[:5]}"


def test_no_secret_looking_file_is_tracked() -> None:
    bad = [f for f in _tracked() if Path(f).name in SECRET_NAMES or Path(f).name.endswith((".pem", ".key"))]
    assert bad == [], bad
