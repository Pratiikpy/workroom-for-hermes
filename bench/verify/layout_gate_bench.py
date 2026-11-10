"""Layout gate measured on seeded faults and on clean slides, then on real decks other people made.

    python layout_gate_bench.py [seed]

Part 1: 210 slides each carrying ONE injected fault (seven kinds, 30 each, sizes and positions drawn from a seeded generator) and 210 clean slides drawn
from the same generator with no fault. Reports, per kind, how many faults the gate blocked or warned with the right kind, and how many clean slides it
flagged. The faults and the gate were written by the same author: this measures the gate against its own definition of a fault, not against a human's
eye; part 2 is the check against files nobody here made.
Part 2: every .pptx under the given corpus folders; counts findings per deck and prints the first few for inspection.
"""

import collections
import io
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from workroom.workroom_core.layout_gate import check_pptx  # noqa: E402

WORDS = "revenue margin growth demand region quarter customers budget forecast delivery operations people safety water energy".split()
PER_KIND = 30
KINDS = ["overflow", "small_text", "off_slide", "contrast", "overlap", "table_height", "empty_title"]


def sentence(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n)).capitalize() + "."


def add_text(slide, rng, text, left, top, width, height, size, color="111827", name="Body", wrap=True):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tb.name = name
    tb.text_frame.word_wrap = wrap
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = text
    r.font.size, r.font.name = Pt(size), "Calibri"
    r.font.color.rgb = RGBColor.from_string(color)
    return tb


def clean_slide(slide, rng):
    """A plausible slide: a title and one or two body boxes that fit, a small source line; positions vary, nothing overlaps."""
    title = slide.shapes.title
    title.left, title.top, title.width, title.height = Inches(0.7), Inches(0.4), Inches(11.9), Inches(0.9)
    title.text_frame.text = sentence(rng, rng.randint(2, 5))
    title.text_frame.paragraphs[0].runs[0].font.size = Pt(rng.choice([28, 30, 32]))
    top = 1.6
    for _ in range(rng.randint(1, 3)):
        size = rng.choice([16, 18, 20])
        width = rng.choice([5.5, 8.0, 11.9])
        chars_per_line = width * 72 / (size * 0.5)
        n_words = rng.randint(4, 10)
        text = sentence(rng, n_words)
        lines = max(1, int(len(text) / chars_per_line) + 1)
        height = lines * size * 1.3 / 72 + 0.3
        add_text(slide, rng, text, 0.7, top, width, height, size)
        top += height + 0.25
    add_text(slide, rng, "Source: department workbook", 0.7, 6.8, 8.0, 0.4, rng.choice([12, 12, 14]), "595959", "Source")


def faulty_slide(slide, rng, kind):
    clean_slide(slide, rng)
    if kind == "overflow":
        add_text(slide, rng, " ".join(sentence(rng, 12) for _ in range(rng.randint(10, 25))), 0.7, 4.0, rng.choice([4.0, 6.0, 8.0]), rng.choice([0.5, 0.8, 1.0]), rng.choice([18, 20, 24]), name="Overflowing")
    elif kind == "small_text":
        add_text(slide, rng, sentence(rng, 8), 0.7, 5.2, 8.0, 0.4, rng.choice([6, 7, 8]), name="Tiny")
    elif kind == "off_slide":
        left = rng.choice([12.0, 12.8, 13.6, 14.5])
        add_text(slide, rng, sentence(rng, 6), left, 5.0, 3.0, 0.6, 18, name="Off")
    elif kind == "contrast":
        bg = rng.choice(["FFFFFF", "F5F5F5"])
        fg = rng.choice(["E6E6E6", "D9D9D9", "CFCFCF", "FFFF99"])
        shp = slide.shapes.add_shape(1, Inches(0.7), Inches(5.0), Inches(8), Inches(0.9))
        shp.fill.solid()
        shp.fill.fore_color.rgb = RGBColor.from_string(bg)
        shp.name = "Callout"
        tf = shp.text_frame
        r = tf.paragraphs[0].add_run()
        r.text = sentence(rng, 6)
        r.font.size, r.font.name = Pt(20), "Calibri"
        r.font.color.rgb = RGBColor.from_string(fg)
    elif kind == "overlap":
        add_text(slide, rng, sentence(rng, 10), 0.7, 1.6, 8.0, 0.9, 20, name="Collides")
        add_text(slide, rng, sentence(rng, 10), 1.0, 1.9, 8.0, 0.9, 20, name="Collided")
    elif kind == "table_height":
        rows = rng.randint(16, 26)
        tbl = slide.shapes.add_table(rows, 3, Inches(0.7), Inches(1.6), Inches(11.9), Inches(0.4 * rows)).table
        for r in range(rows):
            for c in range(3):
                tbl.cell(r, c).text = rng.choice(WORDS)
    elif kind == "empty_title":
        slide.shapes.title.text_frame.paragraphs[0].runs[0].text = ""


def build(rng, kind):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    (clean_slide if kind is None else (lambda s, r: faulty_slide(s, r, kind)))(slide, rng)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20261110
    rng = random.Random(seed)
    caught: collections.Counter = collections.Counter()
    missed: collections.defaultdict = collections.defaultdict(list)
    for kind in KINDS:
        for _ in range(PER_KIND):
            data = build(rng, kind)
            found = {f.kind for f in check_pptx(data)}
            if kind in found:
                caught[kind] += 1
            else:
                missed[kind].append(sorted(found))
    total = PER_KIND * len(KINDS)
    print(f"seed {seed}: faults caught {sum(caught.values())}/{total} ({100 * sum(caught.values()) / total:.1f}%)")
    for kind in KINDS:
        print(f"  {kind:14s} {caught[kind]}/{PER_KIND}  other findings on the misses: {missed[kind][:3]}")
    flagged = 0
    why: collections.Counter = collections.Counter()
    for _ in range(total):
        findings = check_pptx(build(rng, None))
        if findings:
            flagged += 1
            why.update(f.kind for f in findings)
    print(f"clean slides flagged {flagged}/{total} ({100 * flagged / total:.1f}%) {dict(why)}")
    folders = [Path(a) for a in sys.argv[2:]]
    if folders:
        decks = sorted(p for f in folders for p in f.rglob("*.pptx"))
        by_kind: collections.Counter = collections.Counter()
        flagged_decks = errors = 0
        examples = []
        for p in decks:
            try:
                fs = check_pptx(p.read_bytes())
            except Exception:  # noqa: BLE001
                errors += 1
                continue
            if fs:
                flagged_decks += 1
                by_kind.update(f.kind for f in fs)
                if len(examples) < 12:
                    examples.append((p.name, fs[0].slide, fs[0].kind, fs[0].message[:110]))
        print(f"real decks: {len(decks)} read, {errors} unreadable, {flagged_decks} with findings; findings by kind {dict(by_kind)}")
        for e in examples:
            print("  ", e)


if __name__ == "__main__":
    main()
