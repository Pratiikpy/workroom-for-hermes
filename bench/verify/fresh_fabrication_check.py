"""A fresh, judge-free check of figure proof on what a real agent wrote, using only that run's own web results as evidence.

    python fresh_fabrication_check.py <task.jsonl> [<task.jsonl> ...]

Truth is mechanical: a figure the agent wrote is 'present' when its digits appear in the text of the web results it read, and 'absent' otherwise. The proof is
compared with that truth. These runs were not used to tune any rule. 'Present' by digits is a weak test (a number can appear in the wrong place), so a figure
marked supported while absent is the failure that matters most; a figure absent from the evidence that is NOT shown as supported is the success.
"""

import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from workroom.workroom_core.figure_proof import Evidence, check_text, result_text  # noqa: E402


def digits(raw: str) -> str:
    return re.sub(r"\D", "", raw).lstrip("0")


def main() -> None:
    total = collections.Counter()
    for path in sys.argv[1:]:
        items: list[Evidence] = []
        final = ""
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "tool_result" and str(e.get("name", "")).startswith(("web_", "read_file", "terminal")):
                items.append(Evidence(len(items) + 1, e["name"], "", 0.0, result_text(e.get("output")), "tool"))
            for key in ("content", "text", "message", "final"):
                if isinstance(e.get(key), str) and len(e[key]) > 200:
                    final = e[key]
        blob = re.sub(r"[,\s]", "", " ".join(i.text for i in items))
        counts = collections.Counter()
        for p in check_text(final, items):
            d = digits(p.raw)
            if len(d) < 2:
                continue
            present = d in re.sub(r"\D", "", blob) or digits(p.raw.replace(",", "")) in blob
            supported = p.state in ("sourced", "calculated")
            counts[("present" if present else "absent", "supported" if supported else "not supported")] += 1
        print(Path(path).name, dict(counts))
        total.update(counts)
    absent = total[("absent", "supported")] + total[("absent", "not supported")]
    present = total[("present", "supported")] + total[("present", "not supported")]
    print(f"figures absent from the evidence: {absent}, of which shown as supported: {total[('absent', 'supported')]}")
    print(f"figures present in the evidence: {present}, of which shown as supported: {total[('present', 'supported')]}")


if __name__ == "__main__":
    main()
