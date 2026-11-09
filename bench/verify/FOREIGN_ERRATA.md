# Errata for the foreign-document evidence

Dated entries, appended. A correction is a new entry that points at the old one; nothing here is edited after the fact. The sealed halves are
described in `foreign_seal_poi.json` and `foreign_seal_lo.json` (SHA-256 of each list is in the file).

## E-001 (2026-11-09): the workbook comparison touched the sealed half before the seal was committed

`foreign_xlsx.py` was started on all 364 public workbooks (Apache POI) before `foreign_seal_poi.json` was written and committed. The run finished
after the seal commit, and its aggregate counts (over both halves) were printed to the terminal before I looked at any per-file row. I read per-file
rows of the development half only and fixed three reader defects from them (Strict Open XML, cells without positions, hidden columns and sheets). The
sealed half of the workbook comparison is therefore **not blind in aggregate**; it is re-run once, after the last fix, and reported with this caveat.
The Word and PowerPoint edit checks, the chart checks and the link checks on the public corpora were started after the seal.

## E-002 (2026-11-09): the user's own documents are development data

The 69 unique Word, Excel and PowerPoint files found under the user's `Downloads` folder (OneDrive cloud placeholders cannot be read without
downloading them and were left alone) were used to find and fix defects, so they are **development** data. They are described in counts only; their
names and contents are not copied into the repository.

## E-003 (2026-11-09): the link classification was refined after its first output

`foreign_ties.py` first labelled an automatic link "wrong" whenever it did not land on the very cell the harness had written for that figure. Reading
nine such cases showed that in each the harness had written the figure twice (once with a label, once with none) and the engine had chosen the cell whose
label appears in the paragraph. The classifier now calls those `linked_equivalent` (another cell holds the same figure and its label words are in the
paragraph) and, in the labelled run, `unlabelled_ambiguous_linked` (the harness row had no words at all). This refinement was made on development
data only and after seeing its output. Reported counts name these classes; no row was moved from "wrong" to a better class without being in one of them.

## E-004 (2026-11-09): the workbooks behind the documents are mine

Links, updates and three-cycle runs on foreign documents use a workbook that `foreign_ties.py` builds from the document's own figures. The document is
foreign; the workbook is not. "Labelled" mode writes the words before each figure as the row label and is favourable to the matcher; "bare" mode writes
figures only and is the lower bound. Neither is a workbook an analyst wrote.

## E-005 (2026-11-09): the oracle for "false alarm" disagreed with a reasonable flag

In the December-to-January monthly trial one flagged sentence ("0.0 is a calculated change that would turn the other way") was counted a false alarm
because the trial's template wrote the same text. A change of exactly zero beside "up" or "down" has no direction; the flag is defensible. The count is
reported as it came out (1 in that run) and not adjusted.

## E-006 (2026-11-09): a defect found by the foreign documents changed numbers I had already published

After 8 Nov the update-cycle trials were reported with 135 owner actions over 22 cycles. Realignment after a release (a defect found on 9 Nov, see the
ledger) was demoting links to "confirm" in any paragraph holding an unlinked number; on the monthly report that was inflating the owner's work. The same
trials rerun after the fix: 119 owner actions over the same 22 cycles, 0 silent errors, 0 false alarms in both. The 8 Nov figure is superseded, not
deleted.

## E-007 (2026-11-09): the sealed halves were run once, on commit f6e1746; what they showed, and what was fixed afterwards

The sealed halves of both public corpora were run once on commit `f6e17461dbff9ae610b68dfe9ff6807d25b81120` (frozen: no change to `workroom_core` between the
last development rerun and the start of that run). Their results are reported exactly as they came out. They exposed problems that the development half
had not: numbers inside Word field results (page numbers, tables of contents) were treated as editable text; a figure written without its leading zero
(".5") was rewritten with one; chart points were linked in charts whose data lives outside the file; formulas with no saved value were dropped
without a word. Each was fixed afterwards (commit `c9fdd5b`) with a test. Those fixes were made after seeing the sealed failures, so rerunning the same
files proves only that the fix works, not that the product is right on unseen files; the post-fix reruns are labelled that way in the ledger.
Three sealed items were not product defects: one chart "wrong link" was the harness mapping a chart's third series to the wrong workbook column; one
edit "failure" was two single-digit shapes whose texts collide in a text-multiset comparison; the workbook cells Excel reported that the file does not
contain come from a pivot table that Excel regenerates when it opens the file. One item stays unexplained and open: a workbook (`CVLKRA-KYC_Download_File_Structure_V3.1.xlsx`) where Workroom indexes
200 more numeric cells than Excel reports, all plain numbers, with no value mismatch.

## E-008 (2026-11-09): reruns after the post-seal fixes (commit c9fdd5b)

On the development data again: the user's files 41 ok and 0 failed in the real-app edit check; the POI development half 19 ok and 1 failed. The one failure
is `MultipleBodyBug.docx`, a deliberately malformed file with three `<w:body>` elements of which Word shows only the first; Workroom edits the second, which
Word does not display. It is recorded as a malformed-input case, not fixed. Of the sealed files that failed, the Word document whose edit Word could not
see no longer offers an edit (its only number was a page-number field result), the deck whose ".5" became "0.6" now passes, and the chart whose data lives
outside the file is no longer linked. These reruns are not blind (E-007). The agent runs with the local model were repeated with the project id in the
prompt after the first set of runs overwrote an earlier report that had shown the roll-forward tool being called; only the later reports are kept.

## E-009 (2026-11-09): the values-only link result was stale, and the workbook that did not match was an oracle limit

Two corrections after GPT review 10. (1) The readiness report and the README quoted "values only: 3 linked, 2 wrong" from `ties_own_bare3.json`, a run made
before the commit that refuses a link made from digits alone. The same 1,069 figures rerun with the current code (`ties_own_bare5.json`) give 0 linked automatically,
0 wrong. The earlier numbers are superseded, not deleted. (2) Errata E-007 left one public workbook unexplained (Workroom 505 numeric cells, Excel 305). The cause was
the comparison harness, not Workroom: the sheets are protected, `SpecialCells` raises on a protected sheet, and the harness counted zero. With a fallback to the used
range, Excel reports 505, equal to Workroom and to openpyxl. Both public workbook sets were rerun with the fixed harness (ledger row of the same date); two
one-cell differences in the sealed set remain and have not been investigated one by one. These reruns are not blind: the harness was changed after the sealed
workbooks had been compared.
