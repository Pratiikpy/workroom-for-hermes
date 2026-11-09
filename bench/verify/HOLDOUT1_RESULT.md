# Holdout 1 result: Victorian Department of Energy, Environment and Climate Action (DEECA) 2024-25 (run 9 Nov 2026, commit `ccf76c3` code, protocol `4e7f990`)

Read this with `HOLDOUT1_PROTOCOL.md`, written before the run. Two pairs, one blind run each, sampled with a fixed seed, judged by one independent reader who saw only the sentence, the figure and the candidate cell (never the matcher's reasons). The builder cross-read part of the sample (see below). Files are public; they are kept outside the repository and sealed by hash in the protocol.

## 1. What the blind run did

| Bucket (every figure found) | H1a financial statements x financial workbook | H1b annual report x five workbooks |
|---|---|---|
| Figures found | 4,670 | 3,609 |
| Linked automatically | 2,609 (55.9%) | 239 (6.6%) |
| Asked | 1,885 (40.4%) | 2,615 (72.5%) |
| Listed apart (coincidence) | 42 | 279 |
| No source found | 134 | 476 |
| Time | 15 s | 12 s |

## 2. How right it was (independent reader, seeded samples)

| Measure | H1a | H1b |
|---|---|---|
| Automatic links judged correct | 118 of 120 (98.3%, 95% interval 94.1 to 99.5) | 119 of 120 (99.2%, 95.4 to 99.9) |
| Pooled automatic links | 237 of 240 (98.8%, 96.4 to 99.6). Three wrong links in 240. | |
| Asked figures that had the right cell among the candidates | 42 of 60 (70%, 57.5 to 80.1) | 6 of 60 (10%, 4.7 to 20.1) |
| Listed apart that really had no source | 40 of 40 | 40 of 40 |
| "No source found" that did have a source | 17 of 80 (21%, 13.7 to 31.4) | 9 of 80 (11%, 6.0 to 20.0) |

The three wrong automatic links: `890` (a net gain of (14) in the Fire and Emergency column linked to the Environment column, which holds the same value), `2964` (a Level 3 subtotal linked to a closing balance of the same value on another sheet), `2648` (the prose "$14.9 million" in a sentence about a decrease linked to the 2024 balance of derivative instruments, which is a level, not the movement).

What the numbers say, without softening:

- The links Workroom makes by itself are right about 98 to 99 times in 100 on this family of documents. That is a measured rate with its sample size, not "no mistakes". It is far better than the second development pair (6 wrong in 181) and the two groups of documents are not the same population.
- **The first import is not light.** H1a asked 1,885 questions, about 1,300 of them real (the right cell was among the candidates) and about 560 noise; H1b asked 2,615, of which about 260 were real and about 2,350 noise. The noise is small numbers in prose that equal some cell by chance (25 incidents, 7 projects) and, in the statements, the "000" of every `$'000` heading read as a number. A person facing 2,615 questions to find 260 real ones would stop.
- Recall holes: in the statements, figures typed into workbook cells as text with a footnote mark ("14,263(i)") were invisible to the matcher, and the documents themselves state a few figures that the workbook holds as text.

## 3. Two defects found in the readers by this run

1. **Word paragraphs that open a page were not read.** A run that carries Word's `lastRenderedPageBreak` marker (a cache of where Word last broke the page) was treated as holding a break, so the first run of every paragraph that began a page was skipped: its figures and its heading text were invisible. In the statements this hid 16 figures and, more importantly, section headings such as "5.1.1 Reconciliation of movements in carrying values" (their numbers and words are what a source sheet is named after).
2. The `000` of `$'000` was read as a quantity: 328 of the 4,670 "figures" in the statements were these marks (the figure count falls to 4,342 when they are dropped, 4,358 with the page-break fix).

## 4. What was changed afterwards (non-blind from here: DEECA is now development data)

Fixed because this run showed it, each with a test in `tests/test_holdout_fixes.py`, `tests/test_docx.py` and `tests/test_numbers.py`:

- A run of zeros is the thousands mark, never a quantity.
- Runs holding only Word's page-break cache are plain text.
- A paragraph that reads as a numbered section heading ("5.1.1Reconciliation...") is the section whatever its style is called; a source sheet named after that section (sheet "5.1.1", or "Balance sheet" under "Balance sheet as at...") breaks ties between equal cells; a closest cell off the named sheet is not accepted when a cell on it fits too.
- A table row heading in the document has to be a row or column heading of the cell (tables are often turned on their side), else the link is asked.
- Merged headings head every column or row they span.
- A figure typed as text with a footnote mark is a source number; a bare year with a mark stays a heading.
- A change in the text ("decreased by") is not linked to a balance cell.
- A short number does not borrow the workbook's `$000` heading to become a candidate: the document has to name the unit. A longer figure with words behind it is still offered.
- A short number with little behind it (below 0.3 of the cell's headings named) is listed apart rather than asked.

Effect on the 400 figures the reader judged, re-scored against the reader's answers (`holdout_compare.py`): statements, automatic links 2,609 to 2,971, asked 1,885 to 995, listed apart 42 to 236; annual report, automatic 239 to 343, asked 2,615 to 1,125, listed apart 279 to 1,723, found-in-footnote cells now linked. Of the 118 correct automatic links in the statements sample, 112 stay automatic and 6 become questions; of 42 real questions, 13 became correct automatic links; both earlier wrong links are no longer wrong automatic links. The cost is real: some previously correct automatic links are now asked (6 of the 118 in the statements sample, 8 of the 120 in the annual report sample).

These later numbers are **not blind**. The claim that survives is the blind one in section 2. The reduction in questions counts figures moved into "listed apart" as unresolved, not as solved; in the sampled "listed apart" figures, 0 of 100 had a source, but the enlarged bucket has not been re-checked by an independent reader and must be before it is trusted.

## 5. What was not covered

PowerPoint and Excel-only documents; charts; the release step on this set; second and third cycles; the time a person would need; the builder cross-read H1b's 120 automatic links fully and H1a's first 30 only, so for H1a the independent reader is the only complete judge. Both pairs are from one department and state conventions similar to the development pairs. Holdout 2 (Department of Health) is sealed and has not been run.
