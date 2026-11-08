"""How often does the calculation finder "explain" a percentage that is NOT calculated from anything? (the coincidence rate)

    python calc_null_bench.py <fred csv folder> [trials]

Each trial writes a deck from real data in which the percent figures are replaced by random values, then asks the finder to explain them.
A random value is explained only by coincidence, so the explained fraction measures how often the finder would be wrong. The same is run
for the true percentages (recall). Whole-number percentages are reported separately: they coincide far more often, and the finder asks
for the owner's choice on them instead of accepting them.
"""

import random
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cycles as c  # noqa: E402
from workroom.workroom_core.project import Project  # noqa: E402


def explained(kind, folder: Path, replace) -> tuple[int, int, int]:
    root = Path(tempfile.mkdtemp())
    kind.workbook(root, 0)
    kind.build(root)
    state = Path(tempfile.mkdtemp())
    if replace is not None:
        from pptx import Presentation

        prs = Presentation(root / kind.file)
        for slide in prs.slides:
            for sh in slide.shapes:
                if sh.has_text_frame and sh.name.startswith("A "):
                    para = sh.text_frame.paragraphs[0]
                    para.runs[0].text = re.sub(r"(up|down) [\d.]+%", lambda m: f"{m.group(1)} {replace()}%", para.runs[0].text)
        prs.save(str(root / kind.file))
    proj = Project(root, state)
    proj.discover()
    scan = proj.calculations()
    mine = [x for x in scan.candidates if "reached" in x.sentence]
    certain = [x for x in mine if x.certainty == "certain"]
    unexplained = [u for u in scan.unexplained if "reached" in u.get("sentence", "")]
    return len(mine), len(certain), len(unexplained)


def main() -> None:
    folder = Path(sys.argv[1])
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    rng = random.Random(11)
    kind = c.QuarterlyDeck(folder, "Q1 2025", "Q3 2026")
    totals = {"decimal": [0, 0, 0], "whole": [0, 0, 0]}
    for label, make in (("decimal", lambda: f"{rng.uniform(0.2, 9.9):.1f}"), ("whole", lambda: str(rng.randint(1, 9)))):
        for _ in range(trials // 10):
            a, b, u = explained(kind, folder, make)
            totals[label][0] += a
            totals[label][1] += b
            totals[label][2] += u
    true_a, true_b, true_u = explained(kind, folder, None)
    sentences_per_trial = 3
    for label, (a, b, u) in totals.items():
        n = (trials // 10) * sentences_per_trial
        print(f"random {label} percentages: {n} written, {a} explained by coincidence ({a / n:.1%}), {b} of them accepted as certain ({b / n:.1%}), {u} reported as unexplained")
    print(f"true percentages in sentences: {sentences_per_trial}, {true_a} explained, {true_b} certain, {true_u} unexplained")


if __name__ == "__main__":
    main()
