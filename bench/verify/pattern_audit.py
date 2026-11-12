"""Time every literal pattern in the plugin's source (module level or inline) on hostile inputs.

    python pattern_audit.py [size]

Patterns are read from the source with ast: every string constant passed as the first argument of a re.* call. Each is run with search and finditer (and match, when the
code calls match or fullmatch) over runs of single characters and of short units from the pattern itself. Anything slower than LIMIT is printed with its file and line.
"""
import ast
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000
LIMIT = 0.04
BASE = list(" \n\t.,;:'\"<>()[]{}/\|*?-_=+#$%&@!0123456789aA") + ["\n\n", "; cd ", "cd ", "<script", "<a", "1,", "1.", "1 ", "$1", "a.", "a b ", ". ", "\r\n", "git ", "#", "# 1", "| ", "http://a", "a/", "..", "0.0", "1e", "- ", "**", "a:", "a=", "Jan ", "Q1 "]
FUNCS = {"compile", "sub", "subn", "search", "match", "fullmatch", "findall", "finditer", "split"}
found = []
for path in list((ROOT / "workroom_core").rglob("*.py")) + list((ROOT / "adapters").rglob("*.py")) + list((ROOT / "dashboard").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")) + [ROOT / "__init__.py"]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.func.attr in FUNCS and node.args:
            arg = node.args[0]
            parts = []
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                parts = [arg.value]
            elif isinstance(arg, ast.JoinedStr):
                continue
            if not parts:
                continue
            flags = 0
            for extra in list(node.args[1:]) + [k.value for k in node.keywords if k.arg == "flags"]:
                for name in re.findall(r"re\.([A-Z]+)", ast.unparse(extra)):
                    flags |= getattr(re, name, 0)
            found.append((path.relative_to(ROOT).as_posix(), node.lineno, node.func.attr, parts[0], flags))
print(len(found), "literal patterns", flush=True)
slow = 0
for file, line, how, pattern, flags in found:
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        continue
    words = re.findall(r"[A-Za-z<][A-Za-z_-]{1,12}", pattern)[:20]
    worst = (0.0, "", "")
    for unit in BASE + words + [w + " " for w in words]:
        text = unit * (SIZE // len(unit))
        for label, fn in (("search", rx.search), ("match", rx.match), ("finditer", lambda t: sum(1 for _ in rx.finditer(t)))):
            started = time.perf_counter()
            fn(text)
            took = time.perf_counter() - started
            if took > worst[0]:
                worst = (took, unit, label)
        if worst[0] > 0.3:
            break
    if worst[0] > LIMIT:
        slow += 1
        print(f"{worst[0] * 1000:8.0f} ms  {file}:{line}  re.{how}  {worst[2]} on {worst[1]!r}   {pattern[:90]}", flush=True)
print("slow:", slow)
