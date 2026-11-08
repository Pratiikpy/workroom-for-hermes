"""Measure the claim reader on real earnings-release prose.

    python claims_bench.py <folder of .txt press releases> [out.json]

Three measurements, none of which needs a person to label anything:
  coverage      of the sentences that carry a direction or comparison word and at least one figure, how many does the grammar read;
  consistency   a company's own sentence is true about its own numbers, so every claim read from it must hold on its own figures;
  stability     the reading must not depend on the digits: replace the figures with others and the same claims must be read.
Failures are printed in full so they can be judged by eye; the judgments are recorded in EVIDENCE.md.
"""

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from workroom.workroom_core.meaning.claims import _CUE, figures_in, holds, read_claims  # noqa: E402

SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


def sentences(raw: str) -> list[str]:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", raw)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("|", "#", "*", "-", ">", "Title:", "URL Source", "Markdown")) or len(line) < 40:
            continue
        for s in SENT.split(line):
            s = re.sub(r"\s+", " ", s).strip()
            if 30 <= len(s) <= 600:
                out.append(s)
    return list(dict.fromkeys(out))


def with_figures_replaced(text: str, figs, rng: random.Random) -> str:
    out, pos = [], 0
    for f in figs:
        out.append(text[pos:f.start])
        digits = re.search(r"[0-9][0-9,]*\.?[0-9]*", f.raw)
        new = f"{rng.randint(11, 99)}.{rng.randint(1, 9)}" if digits and "." in digits.group(0) else str(rng.randint(11, 999))
        out.append(re.sub(r"[0-9][0-9,]*\.?[0-9]*", new, f.raw, count=1))
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


def main() -> None:
    folder = Path(sys.argv[1])
    rng = random.Random(7)
    files = sorted(folder.glob("*.txt"))
    all_s = [s for f in files for s in sentences(f.read_text(encoding="utf-8", errors="replace"))]
    cue_s = [s for s in all_s if _CUE.search(s) and figures_in(s)]
    read, unread, inconsistent, unstable, patterns = [], [], [], [], {}
    claims_total = 0
    for s in cue_s:
        figs = figures_in(s)
        r = read_claims(s, figs)
        if r.claims:
            read.append(s)
        else:
            unread.append((s, r.not_checked))
        vals = [f.value for f in figs]
        for c in r.claims:
            claims_total += 1
            patterns[c.pattern] = patterns.get(c.pattern, 0) + 1
            h = holds(c, vals)
            if h is False:
                inconsistent.append((s, c.pattern, c.cue, c.a, c.b))
        mutated = with_figures_replaced(s, figs, rng)
        r2 = read_claims(mutated)
        if [(c.pattern, c.relation, c.a, c.b) for c in r.claims] != [(c.pattern, c.relation, c.a, c.b) for c in r2.claims]:
            unstable.append((s, mutated))
    result = {"releases": len(files), "sentences": len(all_s), "with_cue_and_figure": len(cue_s), "read": len(read), "coverage": round(len(read) / max(1, len(cue_s)), 3),
              "claims": claims_total, "by_pattern": patterns, "inconsistent_on_own_figures": len(inconsistent), "unstable_under_new_digits": len(unstable)}
    print(json.dumps(result, indent=1))
    print("\n--- INCONSISTENT (a company's own sentence read as false):")
    for row in inconsistent[:40]:
        print(" *", row[0][:260], "|", row[1:], "")
    print("\n--- UNSTABLE:")
    for s, m in unstable[:15]:
        print(" *", s[:200], "\n   ->", m[:200])
    print("\n--- UNREAD (sample of 60):")
    for s, nc in rng.sample(unread, min(60, len(unread))):
        print(" *", s[:240])
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps({**result, "inconsistent": inconsistent, "unstable": unstable, "unread": [u[0] for u in unread]}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
