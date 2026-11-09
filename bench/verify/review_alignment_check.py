"""How often does a mark sit on the right line of the page? The check uses the page, not the matcher: the text of the line under each mark must hold the words of
the figure's own row heading (tables) or of its sentence (prose).

    python review_alignment_check.py <report.docx> <report.pdf> [sample size]
"""

import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pypdfium2 as pdfium  # noqa: E402

from workroom.workroom_core import review  # noqa: E402
from workroom.workroom_core.match.engine import tokens  # noqa: E402
from workroom.workroom_core.ooxml.docx import Doc  # noqa: E402


def main() -> None:
    docx, pdf_path = Path(sys.argv[1]), Path(sys.argv[2])
    sample = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    pdf = pdf_path.read_bytes()
    mentions = list(Doc(docx.read_bytes()).mentions())
    placed = review._pdf_numbers(pdf)
    mapping = review.align([m.number.raw for m in mentions], [raw for _p, raw, _b in placed])
    print(f"figures in the document {len(mentions)}, in the pdf {len(placed)}, placed {len(mapping)} ({100 * len(mapping) / len(mentions):.1f}%)")
    rng = random.Random(7)
    chosen = rng.sample(sorted(mapping), min(sample, len(mapping)))
    doc = pdfium.PdfDocument(pdf)
    ok = bad = unknown = 0
    wrong = []
    for i in chosen:
        m = mentions[i]
        page_no, raw, boxes = placed[mapping[i]]
        if not boxes:
            unknown += 1
            continue
        want = {t for t in tokens(m.row_head or m.context[0]) if t[0].isalpha()}
        if not want:
            unknown += 1
            continue
        page = doc[page_no - 1]
        w, h = page.get_size()
        b = boxes[0]
        top, bottom = (1 - b.y) * h + 2, (1 - b.y - b.h) * h - 2
        text = page.get_textpage()
        line = text.get_text_bounded(0, bottom, w, top)
        text.close()
        have = set(tokens(line))
        first = [t for t in tokens(m.row_head or m.context[0]) if t[0].isalpha()][:3]  # a row heading may wrap onto the line above: its first words are on this line
        share = len(want & have) / len(want)
        if share >= 0.5 or (first and all(t in have for t in first[:2])) or any(f in have for f in first[:1]):
            ok += 1
        else:
            bad += 1
            wrong.append((raw, sorted(want)[:4], re.sub(r"\s+", " ", line)[:70], page_no))
    print(f"sampled {len(chosen)}: on the right line {ok}, not {bad}, could not tell {unknown}")
    for w in wrong[:10]:
        print("   not on the right line:", w)


if __name__ == "__main__":
    main()
