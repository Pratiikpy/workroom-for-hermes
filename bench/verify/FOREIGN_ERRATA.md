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
