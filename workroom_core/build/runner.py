"""Run the builder in a separate process with a time limit and an output cap. The spec is untrusted data, never code."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..childenv import child_env

WORKER = Path(__file__).with_name("worker.py")
TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 40_000_000


class BuildError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _dependency_paths() -> str:
    """Where the builder's own libraries live, so the child process can import them without inheriting the host's whole environment.

    Inside Hermes the plugin's dependencies sit in a generated environment that the host puts on its import path; a child started with a
    scrubbed environment would not see it."""
    import importlib.util

    dirs: list[str] = []
    for mod in ("pptx", "docx", "lxml", "PIL", "xlsxwriter", "typing_extensions"):
        spec = importlib.util.find_spec(mod)
        if spec is None:
            continue
        origin = spec.origin or (list(spec.submodule_search_locations or [""])[0])
        top = Path(origin).resolve().parent if spec.submodule_search_locations else Path(origin).resolve().parent
        base = top.parent if spec.submodule_search_locations else top
        if str(base) not in dirs:
            dirs.append(str(base))
    return os.pathsep.join(dirs)


def build_file(resolved_spec: dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> bytes:
    """Build the Office file for an already validated and resolved spec. Raises BuildError; never returns a partial file."""
    env = child_env(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=_dependency_paths())
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-P", str(WORKER)],
            input=json.dumps({"spec": resolved_spec}).encode("utf-8"),
            capture_output=True, timeout=timeout, env=env, cwd=str(WORKER.parent.parent.parent.parent),
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildError("timeout", f"the builder did not finish within {timeout:.0f} seconds") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise BuildError("build_failed", f"the builder stopped unexpectedly: {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    if len(proc.stdout) > MAX_OUTPUT_BYTES:
        raise BuildError("too_large", "the built file is larger than the limit")
    try:
        reply = json.loads(proc.stdout)
    except ValueError as exc:
        raise BuildError("build_failed", "the builder returned something unreadable") from exc
    if not reply.get("ok"):
        raise BuildError(reply.get("code", "build_failed"), reply.get("error", "the build failed"))
    return base64.b64decode(reply["file"])


def build_scene_pptx(scene: dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> bytes:
    """Export a validated scene as a one-slide deck of native shapes."""
    from ..scene.model import validate_scene

    issues = validate_scene(scene)
    if issues:
        raise BuildError("bad_scene", issues[0].message)
    return build_file({"kind": "scene_pptx", "scene": scene}, timeout)
