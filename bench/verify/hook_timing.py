"""Time every hook the plugin registers on hostile inputs, end to end.

    python hook_timing.py [size]

The plugin is registered against a recording context with a real Service on a temporary data folder and one registered project (a deck, a protected .env, a report
in Markdown). Every registered hook is then called with large hostile text in each place a model can put text: the command, inline code, a written file's content,
a tool result, the model's reply and the user's message. Prints the slowest call per hook and fails if any call takes longer than LIMIT seconds.
"""

import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 300_000
LIMIT = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
UNITS = ["A", "\n", "\n\n", " ", "\t\n", "; cd ", "cd ", "<", "<script", "<style", "<a ", "1 ", "1,", "1.", "1.5 ", "$1,000 ", "7\n", "9;", "12% ", "a.pptx ", "pptx", "*", ".", "git ", "open(", "'", '"', "(", "{", "[",
         "f(", "Jan ", "Q1 2026 ", "I created a deck. ", "report.docx ", "rm ", "/", "\\", "a/", "-", "#", "| 1 ", "0", "10px ", "é", "x=1;"]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wr_hooktime_"))
    proj = tmp / "proj"
    proj.mkdir()
    (proj / "deck.pptx").write_bytes(b"PK\x03\x04")
    (proj / ".env").write_text("KEY=1")
    (proj / "report.md").write_text("# Report\nRevenue was 4.2 million.\n")

    storage = types.ModuleType("plugins.plugin_storage")
    storage.plugin_data_dir = lambda name: tmp / "data"
    plugins = types.ModuleType("plugins")
    plugins.plugin_storage = storage
    sys.modules.setdefault("plugins", plugins)
    sys.modules["plugins.plugin_storage"] = storage

    import workroom
    from workroom.adapters import tools

    hooks: list[tuple[str, object]] = []

    class Ctx:
        def register_hook(self, name, fn):
            hooks.append((name, fn))

        def get_config(self, key, default=None):
            return default

        def __getattr__(self, name):
            return lambda *a, **k: None

    workroom.register(Ctx())
    pid = tools.service().add_project(str(proj))["project"]
    print(len(hooks), "hooks registered; project", pid, "size", SIZE)
    worst_all = 0.0
    for name, fn in hooks:
        worst = (0.0, "")
        for unit in UNITS:
            blob = unit * (SIZE // len(unit))
            calls = [
                dict(tool_name="terminal", args={"command": blob, "workdir": str(proj)}, result=blob),
                dict(tool_name="terminal", args={"command": "cd . && echo hi", "workdir": str(proj)}, result=blob),
                dict(tool_name="execute_code", args={"code": blob}, result=blob),
                dict(tool_name="write_file", args={"path": str(proj / "notes.html"), "content": blob}, result="ok"),
                dict(tool_name="write_file", args={"path": str(proj / "data.csv"), "content": blob}, result="ok"),
                dict(tool_name="patch", args={"path": str(proj / "report.md"), "patch": blob}, result="ok"),
                dict(tool_name="read_file", args={"path": str(proj / "report.md")}, result=blob),
                dict(tool_name="web_search", args={"query": "x"}, result=blob),
                dict(response_text=blob), dict(user_message=blob), dict(changed_paths=[str(proj / "report.md")], attempt=0),
            ]
            for i, kw in enumerate(calls):
                kw = {**kw, "session_id": "s1", "task_id": "t1", "tool_call_id": f"c{i}"}
                if "content" in kw.get("args", {}):
                    Path(kw["args"]["path"]).write_text(blob, encoding="utf-8")
                started = time.perf_counter()
                try:
                    fn(**kw)
                except TypeError:
                    continue
                except Exception as exc:  # noqa: BLE001  a hook that raises is reported, not hidden
                    print("  raised", name, type(exc).__name__, str(exc)[:80])
                took = time.perf_counter() - started
                if took > worst[0]:
                    worst = (took, f"call {i} on {unit!r}")
                if took > LIMIT:
                    print(f"  SLOW {took * 1000:8.0f} ms  {name}  {getattr(fn, '__qualname__', fn)}  call {i} on {unit!r}", flush=True)
        worst_all = max(worst_all, worst[0])
        print(f"{worst[0] * 1000:8.0f} ms  {name:22s} {getattr(fn, '__qualname__', '')}  ({worst[1]})", flush=True)
    print("worst", round(worst_all * 1000), "ms")
    sys.exit(1 if worst_all > LIMIT else 0)


if __name__ == "__main__":
    main()
