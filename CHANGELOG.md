# Changelog

## 0.4.0

Added
- Review room: a Word report or PowerPoint deck is drawn as Office draws it, with every linked figure marked on its page, as it stands and as it would be after the release, and a card behind each mark saying where the figure came from. Read-only. Needs Microsoft Office (or LibreOffice, untested here) and the pypdfium2 library; without them a structural list says it is not a drawing.
- Reporting recipe: the owner approves one model report, and a copy of it inherits its links, each checked again. Agents can propose and read the status; only the owner installs it.
- Column questions: when a report table column fits two workbook columns about equally, one question for the column instead of one per figure; the answer is the owner's and is remembered for copies.
- Columns placed by their order: a report table that is a block of a sheet is matched column by column in the sheet's order, when every best assignment agrees and nearly every figure equals its cell. This also corrects links that value alone made to another period.
- Release record: a readable record of every published release (changes with source cells, files by hash, checks that ran or could not run, who approved, how to restore), in the Past releases list and as a read-only agent tool.
- A table that lost a source is not half-updated: none of its figures is rewritten and the release lists them as blocked.
- Window refresh: a copy of last period's report can be rolled against a workbook whose window of periods has slid, from the headings its links were inherited under; years printed as numbers are read as headings; headings are compared without footnote marks; rewritten figures follow the document's thousands and bracket style; prior-period figures the workbook now gives differently are listed as restated before release; a dash beside linked figures whose workbook cell now holds a value is listed (never written).
- Evidence: two holdout sets of public Victorian department reports, judged by an independent reader, and the scripts to repeat them (`bench/verify/HOLDOUT1_RESULT.md`, `HOLDOUT2_RESULT.md`).

Fixed
- Word paragraphs that open a page were not read at all (a cache marker Word writes into the first run of a page).
- The "000" of `$'000` was read as a quantity.
- Figures typed into workbook cells as text with a footnote mark ("14,263(i)") were invisible.
- A merged heading now heads every column or row it spans.
- A dated balance label ("Balance at 1 July 2024") steps by a year when rolling forward instead of by a month.
- Section headings that Word styles under another name ("5.1.1Reconciliation...") are read as sections; a source sheet named after the section breaks ties between equal cells.
- A change in the text ("decreased by") is no longer linked to a balance; a table row heading in the report has to be a heading of the cell; a short number does not borrow the workbook's "$000" to become a candidate.
- Matching is about six times faster on large reports and gives the same order every time for equal scores.

Changed
- A figure in a table cell is never set aside as a coincidence; short numbers in sentences with little behind them still are.

## 0.3.0

Added
- Change map: the Changes inbox drawn as a graph of changed source cells and the places they reach, with the finding and evidence for each place.
- Source-health findings: a release that would mix new and old numbers because part of the workbook is missing, or that follows a cell moving by 100 times or becoming zero, must be acknowledged before approval.
- Coincidences: short numbers that equal a cell only by chance are listed apart instead of being asked about.
- Table alignment: a column of a report table that agrees, row by row, with one column of one source sheet is linked as a whole, with the same checks on every cell; on a real report this took the questions from 244 to 129.
- Reading rules: section and note numbers, numbered headings and Notes columns are not figures; a figure a thousand times away from its cell needs a named unit; dashes and unit marks are not headings.
- A link is asked about, not accepted, when the text and the cell's headings use opposite words (opening and closing, assets and liabilities, receipts and payments and similar).
- A column of dotted note numbers is a column of references even when its Notes heading is in another part of a split table.
- Word files with more than one body element are refused instead of edited.
- The shell guard reads the script a command runs.

Fixed
- Quarter forms such as "third quarter" and "1Q" were never recognised (a regular expression had been corrupted).
- Two approvals of one release arriving together could both publish it.
- Rewritten figures rounded halves to the even neighbour instead of the way the spreadsheet displays them.
- A document missing from the folder for a moment lost its links.
- Charts already in a deck were never linked; Strict Open XML, hidden columns and sheets, and cells without positions were read wrongly.

Changed
- Version numbers agree across the plugin, the dashboard manifest and the core.
- The Desktop screen is reorganised: the tracked-changes option sits beside Prepare release, rolling forward lives inside step 2, findings are listed once, the changes view scrolls into view, and the severity label "Check" is now "Read first".
- The README is a front page; evidence and limits moved to `docs/`.

## 0.2.0

Creation of Word, PowerPoint and Excel files from a description with every figure linked; visual pages; project instructions; scheduled checks; roll forward; the meaning layer (calculated numbers, claims that stop being true, stale notes).

## 0.1.0

The editing kernel, link discovery, the journaled release controller with restore and recovery, owner-only approval from Desktop and Telegram, read-only agent tools and the first Desktop screen.
