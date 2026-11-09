# Evidence

Every claim in the README is backed by a dated row in [`bench/EVIDENCE.md`](../bench/EVIDENCE.md) with what was measured, on what, and what was not verified. This page is the readable summary. Numbers come from result files; nothing here is typed from memory. Where something was tested only by the people who built it, the caveat column says so.

| Claim | Result | Caveat |
|---|---|---|
| Untouched parts identical after an edit | 144 of 144 PowerPoint packages, 106 of 106 Word packages | public test corpora, not messy business files |
| One number edited in a real file, nothing else moved | 77 decks, 39 Word documents, 161 embedded workbooks, 0 failures | text and numeric constants; small files |
| Links accepted automatically were correct | 951 of 951 chart points in the matcher benchmark on real decks (95% interval 0.996 to 1.0) | the matcher alone, on a favourable corpus (labels come from the same workbook); charts already in a deck are linked by the product only since 9 Nov, measured in the table below |
| Same-valued decoy sentences linked | 0 of 988 synthetic decoys | synthetic and optimistic |
| Release recovers after a crash | 16 of 16 injected crash points | simulated process death on Windows; not a power-off test |
| Head to head, one figure changes in a deck | complete and 0 collateral parts changed; office-desk 6/6 text but no chart; Hermes' bundled skill missed a target and touched the decoy | one synthetic scenario; PowerPoint only; see `bench/HEAD_TO_HEAD.md` |
| Read-only agent cannot reach write tools | 8 of 8 out-of-scope tools refused by Hermes' real dispatch; a live model (Gemini 2.5 Flash) told to approve, publish or edit directly refused and the file was unchanged | one adversarial run; one model |
| Automatic links on real earnings releases | 0 clearly wrong in 97 read by hand; 56 of 58 decided correct by an independent model judge (60 sampled of 265) | 10 SEC filings converted to Word; 265 of 6,636 numbers linked automatically, 2,433 sent to a person, the rest have no source cell |
| Word tracked changes open in real Microsoft Word | accept-all gives the new text, reject-all gives the original, 4 revisions by "Workroom", on 2 files | Word on Windows only; 16 of 16 real corpus files also validate in OfficeCLI |
| Update cycles on real public data | 22 cycles on three projects (FRED and World Bank series; a deck, and two Word reports in layouts Workroom did not author): 0 silent errors, 80 differences all reported to the owner, 0 false alarms; all 22 releases restored byte for byte | the templates, documents and the simulated owner are mine; made with python libraries, not by a person in Office; one language; no restated past periods |
| Edits checked by readers that share none of Workroom's code | 26 decks edited: python-pptx sees exactly the edits, Microsoft's Open XML SDK validator reports no new error (26 of 26), the real PowerPoint object model sees the same changes (23 of 23) | public test decks with few numbers; PowerPoint on Windows; Word and Excel edits not run through the validator |
| A calculated number is not accepted by coincidence | random percentages written into sentences: 0 of 120 accepted as certain (5% of one-decimal and 55% of whole-number ones fit some calculation and were left to the owner); the 3 true ones were certain | one deck layout |
| Approval from a real Telegram chat | release card with buttons shown, Approve published it, Cancel changed nothing, a sender not in `approvers` was refused | one throwaway bot, one owner account; Discord and Slack not run |

### Files other people made (9 Nov 2026)

Until 8 Nov the evidence used documents, workbooks and an owner that I generated. This table is the first run against files made by other people and read back with the real Word, Excel and PowerPoint. Public corpora (Apache POI and LibreOffice test data) were split by file hash into a development half and a sealed half before any result was read; the sealed half was run once, before the last fixes. Details, caveats and errata: `bench/EVIDENCE.md` (rows dated 9 Nov) and `bench/verify/FOREIGN_ERRATA.md`.

| Question | Result | Caveat |
|---|---|---|
| Edit three numbers in a file I did not make; is anything else touched, and does the real app agree? | the user's own Word and PowerPoint files: 41 of 41 edited files ok; public development halves: 38 ok, 1 failed; SEALED (run once): 30 ok, 3 failed | most public test files hold no numbers; the failures were found, explained and fixed afterwards (errata E-007) |
| Links on those documents | 695 of 1069 figures linked automatically with row labels, 0 wrong; values only: 0 linked, 0 wrong (with no row labels it asks about every figure; an earlier "3 linked, 2 wrong" came from a run before a fix and is superseded, errata E-009); SEALED: 101 links, 0 wrong | the workbook behind each document is built by me from the document's own figures |
| Update the sources, release, read the document back from the real app | 165 figures in 42 documents updated correctly, 0 wrong; SEALED: 43 figures, 0 wrong | Windows; Word and PowerPoint |
| Three cycles with a person editing in the real Word between them | 14 documents passed, 0 failed; a retyped figure stayed as typed | few documents had enough numbers to run it |
| Charts already in a deck | 26 decks, 170 chart points linked (112 automatically, 0 wrong), 76 changed points read back from the real PowerPoint, 0 wrong; SEALED: 248 linked, 0 wrong in the real PowerPoint | small public decks; points are written only where a sheet is embedded behind the chart; the sealed run reported 4 wrong links that were a harness mapping error and one chart whose data lives outside the file (errata E-007) |
| The source workbook restructured by the real Excel | 12 of 12 operations followed correctly or asked, none silently wrong | one project layout |
| Workbook reader against the real Excel | 328 public workbooks compared; 0 value mismatches; cells Excel has and Workroom lacks: 0 development, 4 sealed workbooks (a pivot table the file does not store, formulas with no saved value, an ISO-typed date); one extra cell each in 2 sealed workbooks, not investigated. A workbook that first looked like 200 extra cells was the comparison harness failing on protected sheets (errata E-009) | Excel's typing of dates is not a reliable oracle; these reruns are not blind |
| How long it takes | reading a project of 4 documents against a 105,000-cell workbook went from 207 s to 11 s | one layout; some workbooks whose rows differ only by a number now ask instead of linking |
| An independently authored pair: a government agency's 2020-21 annual report (Word, 85 pages) and its own financial statements workbook | blind run: 1,127 figures found, 226 linked automatically (20%), 586 sent to the owner (52%), 315 with no source cell; 0 wrong in the 70 links read by hand, 0 of 83 year checks disagree; releasing 10 changed cells rewrote exactly 20 paragraphs (every other paragraph identical), and the real Word opened the file | one pair, one blind run; the 156 links that passed a mechanical heading check were not read one by one; automation was 20%, so the owner confirms about half of a real report's figures; section and note numbers were wrongly treated as figures and are now skipped (after seeing the result, so the rerun is not blind); `bench/verify/VPSC_RESULT.md` |
| The 22 update cycles on real data, rerun after a defect these files exposed | 119 owner actions (was 135), 0 silent errors | templates and owner are mine |

## The two independently authored reports

Both come from one government agency, were downloaded from its own site, and were run once, blind, against a protocol committed before the run ([protocol 1](../bench/verify/VPSC_PROTOCOL.md), [result 1](../bench/verify/VPSC_RESULT.md), [protocol 2](../bench/verify/VPSC2_PROTOCOL.md), [result 2](../bench/verify/VPSC2_RESULT.md)).

| | Report against its own year's workbook | Last year's report against this year's workbook |
|---|---|---|
| Figures found | 1,127 | 1,133 |
| Linked automatically (blind run) | 226 (20%) | 181 (16%) |
| Wrong by label among the links read by hand | 0 of 70 | 6 of 181 (closing figure linked to an opening cell), 3 unclear |
| Release of 10 changed cells | exactly 20 paragraphs rewritten, nothing else | exactly 20 paragraphs rewritten, nothing else |

After reading each result, rules were added (headings and note numbers are not figures; dashes are not headings; short numbers that match a cell by chance are listed apart; opposite words on an equal value are asked about; a table column that agrees row by row with one source column is linked as a whole). With them, the first report goes to 340 automatic links and 129 questions of 1,072 figures, and the second to 171 and 219 of 1,129. These later numbers are not blind. Two reports from one agency are two data points, not a rate.

## Reports the builder had not seen (9 Nov 2026)

| Claim | Result | Caveat |
|---|---|---|
| Automatic links are right on unseen reports | 357 of 360 judged correct by an independent reader (99.2%, 95% interval 97.6 to 99.8); the three misses are named in `bench/verify/HOLDOUT1_RESULT.md` | Word only, four documents from one government; samples of 120 per report; a later fix found six more wrong links in one table of the second report, about 0.2% of its automatic links |
| The first import is light | Not yet: 3,841 questions on the Health report's blind run (about 88% real), 1,885 on the first statements report | development work since then cut these (see `HOLDOUT2_RESULT.md`) but the figures after tuning are not blind |
| The review room draws the real page and marks the right figures | Real Hermes Desktop 9 of 9 checks; 182-page report drawn in 30 s, 99.6% of figures placed, 96% pass a line check | Windows and Microsoft Office; LibreOffice, macOS, Linux, dark mode and screen readers not checked |
| A table that lost a source is not half-updated | Tested on a generated report | not measured on real documents |

