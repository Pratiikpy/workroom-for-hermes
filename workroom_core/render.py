"""Real pages of an Office document, from the Office installed on this machine (Windows), turned into pictures with the figures located on them.

Word and PowerPoint save a private copy of the file as a PDF; the PDF is drawn with pdfium (an optional dependency) and the text layer says where each
figure sits on its page. Nothing here changes a document: the file is copied to a temporary folder and opened read-only and windowless. Where Office
or pdfium is missing, callers get None and show a structural view that says it is not a drawing of the document.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .childenv import child_env

TIMEOUT_SECONDS = 180
MAX_PAGES = 400

_WORD = r'''
$ErrorActionPreference = "Stop"
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$app.DisplayAlerts = 0
try {
  $doc = $app.Documents.Open($env:WORKROOM_RENDER_SRC, $false, $true, $false)
  $doc.ExportAsFixedFormat($env:WORKROOM_RENDER_OUT, 17)
  $doc.Close($false)
} finally { $app.Quit() }
'''

_POWERPOINT = r'''
$ErrorActionPreference = "Stop"
$app = New-Object -ComObject PowerPoint.Application
try {
  $pres = $app.Presentations.Open($env:WORKROOM_RENDER_SRC, $true, $false, $false)
  $pres.SaveAs($env:WORKROOM_RENDER_OUT, 32)
  $pres.Close()
} finally { $app.Quit() }
'''


@dataclass(frozen=True)
class Box:
    """A rectangle on a page, as fractions of the page width and height (top left is 0, 0)."""
    page: int
    x: float
    y: float
    w: float
    h: float


def _powershell() -> Path | None:
    exe = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return exe if exe.is_file() else None


def _registered(prog_id: str) -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id))
        return True
    except OSError:
        return False


def _soffice() -> str | None:
    """LibreOffice, when installed: the way to draw a document on a machine without Microsoft Office."""
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for candidate in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(candidate).is_file():
            return candidate
    return None


def _ms_office_available(suffix: str) -> bool:
    if _powershell() is None:
        return False
    return _registered("Word.Application") if suffix.lower() == ".docx" else _registered("PowerPoint.Application") if suffix.lower() == ".pptx" else False


def engine(suffix: str) -> str | None:
    """Who would draw a document of this kind here: "Microsoft Office", "LibreOffice" or None. Microsoft Office is preferred where both exist."""
    if suffix.lower() not in (".docx", ".pptx"):
        return None
    if _ms_office_available(suffix):
        return "Microsoft Office"
    return "LibreOffice" if _soffice() else None


def office_available(suffix: str) -> bool:
    return engine(suffix) is not None


def pdfium_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        return False
    return True


def available(suffix: str) -> bool:
    return office_available(suffix) and pdfium_available()


def office_to_pdf(path: Path) -> bytes | None:
    """The PDF that Microsoft Office (or, without it, LibreOffice) makes of a private copy of ``path``, or None."""
    suffix = path.suffix.lower()
    who = engine(suffix)
    if who is None:
        return None
    work = Path(tempfile.mkdtemp(prefix="workroom-render-"))
    try:
        copy = work / ("copy" + suffix)
        shutil.copyfile(path, copy)
        out = work / "copy.pdf"
        if who == "LibreOffice":
            profile = work / "profile"
            done = subprocess.run([str(_soffice()), f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf", "--outdir", str(work), str(copy)],
                                  text=True, capture_output=True, timeout=TIMEOUT_SECONDS, env=child_env("office"))
        else:
            env = child_env("office", WORKROOM_RENDER_SRC=str(copy), WORKROOM_RENDER_OUT=str(out))
            done = subprocess.run([str(_powershell()), "-NoProfile", "-NonInteractive", "-Command", _WORD if suffix == ".docx" else _POWERPOINT],
                                  text=True, capture_output=True, timeout=TIMEOUT_SECONDS, env=env)
        if done.returncode != 0 or not out.is_file():
            return None
        return out.read_bytes()
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        return len(doc)
    finally:
        doc.close()


def page_png(pdf: bytes, page: int, width_px: int = 900) -> tuple[bytes, int, int]:
    """One page (1-based) drawn at ``width_px`` wide: (PNG bytes, width, height)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    try:
        pg = doc[page - 1]
        w, _h = pg.get_size()
        image = pg.render(scale=width_px / w).to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), image.width, image.height
    finally:
        doc.close()


def locate(pdf: bytes, needles: list[str]) -> dict[str, list[Box]]:
    """Where each piece of text is drawn, in reading order, from the PDF's text layer. A piece that is not found maps to an empty list."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    out: dict[str, list[Box]] = {n: [] for n in needles}
    try:
        for index in range(min(len(doc), MAX_PAGES)):
            page = doc[index]
            width, height = page.get_size()
            text = page.get_textpage()
            try:
                for needle in set(needles):
                    if not needle:
                        continue
                    finder = text.search(needle, match_case=True, match_whole_word=False)
                    while True:
                        hit = finder.get_next()
                        if hit is None:
                            break
                        start, count = hit
                        for k in range(text.count_rects(start, count)):
                            left, bottom, right, top = text.get_rect(k)
                            out[needle].append(Box(index + 1, left / width, 1 - top / height, (right - left) / width, (top - bottom) / height))
            finally:
                text.close()
            page.close()
    finally:
        doc.close()
    return out
