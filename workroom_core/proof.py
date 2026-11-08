"""Rendered before and after proof for presentation changes, using the PowerPoint installed on the machine (Windows only, optional).

The file to render is copied into a private temporary folder and opened read-only and windowless, so neither the live file nor a staged
release is touched. When PowerPoint is missing or fails, callers get None and say so; nothing is guessed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 90
MAX_SLIDES = 4

_SCRIPT = r'''
param([string]$Src, [string]$Out, [string]$Slides)
$ErrorActionPreference = "Stop"
$app = New-Object -ComObject PowerPoint.Application
try {
  $pres = $app.Presentations.Open($Src, $true, $false, $false)
  foreach ($n in ($Slides -split ",")) {
    $i = [int]$n
    if ($i -ge 1 -and $i -le $pres.Slides.Count) { $pres.Slides.Item($i).Export((Join-Path $Out ("slide" + $i + ".png")), "PNG", 960, 540) }
  }
  $pres.Close()
} finally { $app.Quit() }
'''


def available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Test-Path 'Registry::HKEY_CLASSES_ROOT\\PowerPoint.Application'"],
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip().lower() == "true"
    except (OSError, subprocess.TimeoutExpired):
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
        script = work / "render.ps1"
        script.write_text(_SCRIPT, encoding="utf-8")
        out = work / "png"
        out.mkdir()
        done = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Src", str(copy), "-Out", str(out), "-Slides", ",".join(map(str, wanted))],
                              capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        if done.returncode != 0:
            return None
        return {n: (out / f"slide{n}.png").read_bytes() for n in wanted if (out / f"slide{n}.png").is_file()}
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
