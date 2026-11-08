"""Rendered before and after proof for presentation changes, using the PowerPoint installed on the machine (Windows only, optional).

The file to render is copied into a private temporary folder and opened read-only and windowless, so neither the live file nor a staged
release is touched. When PowerPoint is missing or fails, callers get None and say so; nothing is guessed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .childenv import child_env

TIMEOUT_SECONDS = 90
MAX_SLIDES = 4

# The script is passed to PowerShell as the command text, so no script file is run and no execution-policy override is needed.
# The paths arrive as environment variables, never spliced into the script text.
_SCRIPT = r'''
$ErrorActionPreference = "Stop"
$src = $env:WORKROOM_PROOF_SRC; $out = $env:WORKROOM_PROOF_OUT; $slides = $env:WORKROOM_PROOF_SLIDES
$app = New-Object -ComObject PowerPoint.Application
try {
  $pres = $app.Presentations.Open($src, $true, $false, $false)
  foreach ($n in ($slides -split ",")) {
    $i = [int]$n
    if ($i -ge 1 -and $i -le $pres.Slides.Count) { $pres.Slides.Item($i).Export((Join-Path $out ("slide" + $i + ".png")), "PNG", 960, 540) }
  }
  $pres.Close()
} finally { $app.Quit() }
'''


def _powershell() -> Path | None:
    exe = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return exe if exe.is_file() else None


def available() -> bool:
    if sys.platform != "win32" or _powershell() is None:
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "PowerPoint.Application"))
        return True
    except OSError:
        return False


def render_slides(pptx: Path, slides: list[int]) -> dict[int, bytes] | None:
    """PNG bytes for the requested slide numbers (at most four), or None when PowerPoint cannot render them."""
    if not available():
        return None
    wanted = sorted({int(s) for s in slides if isinstance(s, int) and 1 <= s <= 1000})[:MAX_SLIDES]
    if not wanted:
        return {}
    work = Path(tempfile.mkdtemp(prefix="workroom-proof-"))
    try:
        copy = work / "copy.pptx"
        shutil.copyfile(pptx, copy)
        out = work / "png"
        out.mkdir()
        env = child_env("office", WORKROOM_PROOF_SRC=str(copy), WORKROOM_PROOF_OUT=str(out), WORKROOM_PROOF_SLIDES=",".join(map(str, wanted)))
        done = subprocess.run([str(_powershell()), "-NoProfile", "-NonInteractive", "-Command", _SCRIPT], text=True,
                              capture_output=True, timeout=TIMEOUT_SECONDS, env=env)
        if done.returncode != 0:
            return None
        return {n: (out / f"slide{n}.png").read_bytes() for n in wanted if (out / f"slide{n}.png").is_file()}
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
