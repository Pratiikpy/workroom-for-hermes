"""A target file held open exclusively (like Office with the file open): publish must fail cleanly and leave every file as before."""
import ctypes, json, sys, tempfile
from ctypes import wintypes
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workroom.tests.test_book import workbook
from workroom.workroom_core.ooxml.xlsx import patch_numeric_cell
from workroom.workroom_core.service import Service, ServiceError

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.restype = wintypes.HANDLE
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
t = Path(tempfile.mkdtemp()); root = t / "p"; (root / "data").mkdir(parents=True)
(root / "data" / "d.xlsx").write_bytes(workbook(120, .25)); (root / "a.xlsx").write_bytes(workbook(120, .25)); (root / "b.xlsx").write_bytes(workbook(120, .25))
(root / "workroom.json").write_text(json.dumps({"targets": ["a.xlsx", "b.xlsx"]}))
svc = Service(t / "s"); pid = svc.add_project(str(root))["project"]; svc.discover(pid)
src = root / "data" / "d.xlsx"; src.write_bytes(patch_numeric_cell(src.read_bytes(), "Results", "C2", 150))
st = svc.stage(pid)
before = {n: (root / n).read_bytes() for n in ("a.xlsx", "b.xlsx")}
h = k.CreateFileW(str(root / "b.xlsx"), 0x80000000, 0, None, 3, 0x80, None)  # read, share none
print("handle ok:", h not in (None, wintypes.HANDLE(-1).value))
try:
    r = svc.approve_and_publish(pid, st["release_id"], st["digest"]); print("published?!", r)
except Exception as e:
    print("refused:", type(e).__name__, str(e)[:120])
k.CloseHandle(h)
print("files unchanged while locked:", all((root / n).read_bytes() == before[n] for n in before))
try:
    print("after unlock, retry:", svc.approve_and_publish(pid, st["release_id"], st["digest"]).get("state"))
except Exception as e:
    print("retry:", type(e).__name__, str(e)[:160])
print("tmp leftovers:", [p.name for p in root.rglob("*.tmp")])
