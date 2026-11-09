# Result: the second independently authored pair (9 Nov 2026): last period's report, this period's workbook

Protocol: `VPSC2_PROTOCOL.md`, committed before the run. Data: the Victorian Public Sector Commission's 2019-20 annual report (accessible Word version, 1,514,221 bytes, sha256
starting b661301a, downloaded from the Commission's own site with the owner's permission) against its 2020-21 financial statements workbook (the one used in the first pair).
The report's 2020 figures should meet the workbook's 2020 column; its 2019 figures have no source in this workbook. No change to Workroom between the protocol and the run.

| | Blind run | After two reader fixes (not blind) |
|---|---|---|
| Figures found | 1,133 | 1,129 |
| Linked automatically | 181 (16.0%) | 171 (15.1%) |
| Sent to the owner to confirm | 213 (18.8%) | 219 (19.4%) |
| Listed apart as coincidences (not asked) | 219 (19.3%) | 219 (19.4%) |
| No source cell | 520 (45.9%) | 520 (46.1%) |
| Time to find links | 0.8 s | 0.8 s |

Most of the "no source" figures are the report's 2019 comparatives, its workforce and performance tables and its prose, none of which is in a financial-statements workbook for
the following year. That was expected from the protocol; it is a feature of the scenario, not a measured failure.

## Precision of the automatic links (blind run)

- The first 60 in document order were read by hand against both sets of headings: 60 right by value and heading, of which five are note numbers ("5.2", "6.1", "5.3", "5.5",
  "6.2") in the balance sheet's Notes column linked to the workbook's matching note numbers (right by value, but references, not figures).
- Links 61 to 181 were compared mechanically (report row heading against workbook row label); the comparison flagged 70 as weak, all read by hand. Result: **6 links were wrong by
  label**: a figure under "Closing balance" in the report linked to the same value under "Opening balance" in the workbook (an accounting identity, since one year's closing is
  the next year's opening, but not the same figure); **3 were unclear** (a prose sentence about a table, "Depreciation" linked to "Right of use buildings", "Non-current lease
  liabilities" linked to "Total Borrowings", each with an equal value); the rest were right. The 51 links the comparison did not flag were not read one by one.
- Year check where both sides carry a year: 35 links, 1 disagreement, which on reading is right ("Opening balance, 1 July 2019" is the workbook's 2020 opening).
- So on this pair the blind run had **6 wrong and 3 unclear of 181 automatic links** (about 5% at most among those read), against 0 of 70 on the first pair. Taken together the two
  pairs say precision is high but not perfect, and that the failure that matters is a weak label plus an equal value, not a number read wrongly.

## The release test (blind run)

10 constant cells of the workbook's 2020 column were changed, one release was staged (20 changes, no findings) and published, and the report was read back: exactly 20 paragraphs
changed, all of them the linked figures; every other paragraph identical; the real Word opened the file (3,149 paragraphs). Not covered: which places a person would want
changed; restated figures (the fourth measure in the protocol, listing report figures whose heading and year match a workbook cell with a different value, was **not done**).

## What the run showed, and what was done after seeing it (not blind)

1. **Opposite words on an equal value.** A guard now sends a link to the owner when the text and the cell's headings use opposite words (opening and closing, receipts and
   payments, assets and liabilities, income and expenses, increase and decrease, gain and loss, current and non-current, and a few more) and neither word appears on the other
   side. It removed exactly the 6 closing-against-opening links and nothing else. Test in `tests/test_match_guards.py`.
2. **A column of note numbers with no Notes heading.** A long table split across pages left the Notes heading in another table, so note numbers ("5.2", "6.1") were read as
   figures. A column in which every filled cell is a dotted number (at least three rows) is now a column of references. It removed exactly the 4 note links. Test in
   `tests/test_docx.py`.
3. The first pair's counts did not change (340 automatic, 129 asked).
4. Still open: the 3 unclear links (a weak label with an equal value; table alignment does not reach them because their rows' headings differ from the workbook's), and
   restatements, which this scenario is exactly the place to look for.
