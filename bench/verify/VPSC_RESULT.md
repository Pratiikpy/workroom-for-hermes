# Result: the first independently authored report-and-workbook pair (9 Nov 2026)

Protocol: `VPSC_PROTOCOL.md`, committed before the run. Data: the Victorian Public Sector Commission's 2020-21 annual report (accessible Word version, 85 pages, 1,373,925
bytes, sha256 starting 97bc58f5) and its financial statements workbook (29 sheets, 81,612 bytes, sha256 starting fdd8fd76), both downloaded from the Commission's own
"Report resources and other formats" page with the owner's permission. Result files are in `research/corpus/real_pairs/` (not in the repository).

## What was run, and the one harness problem

The harness failed twice before it produced anything, both times because of the harness (it read the wrong keys of the explain result, and it did not save partial
results). No Workroom code changed between those failures and the first reported run, so the first reported run is the blind one. Its numbers are in the first column.
After reading it, two reader rules were added (below); the second column is a rerun after that fix and is **not blind**.

| | Blind run | After the reader fix (not blind) |
|---|---|---|
| Figures found in the report | 1,127 | 1,072 |
| Linked automatically | 226 (20.0%) | 220 (20.5%) |
| Sent to the owner to confirm | 586 (52.0%) | 543 (50.7%) |
| No source cell in the workbook | 315 (27.9%) | 309 (28.8%) |
| Time to find links | 0.8 s | 0.9 s |

## Precision of the automatic links (blind run)

- The first 60 in document order were read by hand against the report's row and column headings and the workbook's: 60 right, 0 wrong. Three of them are note numbers
  ("4.1", "4.2", "6.2") in a Notes column that were linked to the matching note number in the workbook: the same value and heading, but a reference, not a figure.
- Links 61 to 226 were compared mechanically (the report's row heading against the workbook's row label, token overlap of at least one half): 156 passed; the 10 that did
  not were read by hand: 10 right, 0 wrong (three more note or section numbers; one label gap where the workbook's row label sits in another column; two "$12 million"
  and "$10 million" sentences that correctly round 11,774,728 and 9,866,554). The 156 that passed were **not** read one by one.
- A year check on every link: where the report's heading carries a year and the workbook has a year header above the linked cell (83 links), the two agree in all 83. In
  138 links the report's heading carries no year, so the check could not be made, and in 5 the workbook has no year header.
- So: 0 wrong in the 70 links read by hand (95% upper bound on the wrong rate about 4%), 0 disagreements in 83 year checks, and 6 links that are right by value and heading
  but point at reference numbers rather than figures. One pair is one data point, not a rate.

## The release test (blind run)

For 10 automatically linked figures whose source cell is a constant (the Total expenses, Net result, Other economic flows, Total assets and Total liabilities lines, for 2021 and 2020), the cell
was changed in the workbook's XML, one release was staged (20 changes, no findings) and published, and the report was read back. Exactly 20 paragraphs changed, all of them the
linked figures (each of the 10 figures appears twice in the report), each rewritten as the spreadsheet displays it (half away from zero, brackets kept for negatives:
`(2,462,649)` became `(3,693,973)`), and every other paragraph is identical. The real Word opened the released file (4,216 paragraphs). Not covered: which of the 20
places a person would want changed; the report's prose claims; PowerPoint, charts, roll-forward.

## What the run showed, and what was done about it (after seeing the result)

1. Section and note numbers were treated as figures: 55 of the 1,127 found "figures" were references ("Section 4", "Note 2", "4.1 Property, plant and equipment" as a
   heading, a Notes column), and six of them were linked automatically. Fixed with three rules: a number directly after a reference word (section, note, table, page and
   so on) is skipped; the number that opens a heading, or a short paragraph that reads like a numbered heading, is skipped; a table's Notes column is skipped. Tests in
   `tests/test_numbers.py` and `tests/test_docx.py`. The rerun drops exactly those six links and no other.
2. **The owner would have been asked about half of everything.** 543 to 586 confirmations on an 85-page report is not a light job. Most of them are numbers the workbook
   does not contain in the same form (counts, percentages and workforce figures from outside the financial statements, other tables) or that appear in several places; the
   product shows which, but it does not yet rank them by consequence or confirm them in bulk by pattern. This is the main finding of the run and it is not fixed.
3. Automatic links were right where they were made; the cost of that care is the 20% automation rate. The earlier 65% (695 of 1,069) was on workbooks built from the
   documents themselves and should not be quoted as the real-world rate.
