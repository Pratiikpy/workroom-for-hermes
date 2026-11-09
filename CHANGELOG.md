# Changelog

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
