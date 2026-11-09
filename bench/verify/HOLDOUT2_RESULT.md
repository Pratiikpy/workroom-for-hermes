# Holdout 2 result: Victorian Department of Health annual report 2024-25 (run 9 Nov 2026, product code at commit `8bef889`, sealed in `675f16b`)

The one set the builder had not seen when the matcher was last changed. One blind run, one independent reader (seeded samples as in `HOLDOUT1_PROTOCOL.md`), no tuning before the run. Report: the Word annual report with its nine data workbooks in one project. Public files, kept outside the repository, sealed by hash in `HOLDOUT2_PROTOCOL.md`.

## What the blind run did

| Bucket | Figures | Share |
|---|---|---|
| Found | 8,829 | |
| Linked automatically | 3,221 | 36.5% |
| Asked | 3,841 | 43.5% |
| Listed apart (short numbers with little behind them) | 1,490 | 16.9% |
| No source found | 277 | 3.1% |

Run time 297 s on this machine (56 s after a later speed-up that changes no decision).

## How right it was (independent reader)

| Measure | Result | 95% interval |
|---|---|---|
| Automatic links judged correct | 120 of 120 | 96.9 to 100 |
| Asked figures that had the right cell among the candidates | 53 of 60 | 77.8 to 94.2 |
| Listed apart that really had a source | 7 of 40 (six table cells and one sentence) | 8.7 to 32.0 |
| "No source found" that did have one | 21 of 80 | 17.9 to 36.8 |

What this says without softening:

- **The links Workroom makes alone were right in every sampled case on a report it had not seen.** Together with holdout 1 (237 of 240) that is 357 of 360 judged correct (99.2%, 95% interval 97.6 to 99.8). It is not "never wrong": the later work found six wrong automatic links in one table of this report that the sample did not contain (see below), about 0.2% of its 3,221.
- **The first import is still heavy.** 3,841 questions, about 88% of them real (about 3,400): a report that is mostly small tables of counts and zeros, where the same figure sits in many cells. This is the product's weakest measured point, and it is a coverage problem, not a correctness one.
- **The "listed apart" bucket was not safe.** About a sixth of it had a source, all but one of those in tables. A table figure is a claim about its row, so table figures are no longer set aside that way.
- About a quarter of "no source found" had a source (typed-in text figures, label mismatches).

## What was changed afterwards (non-blind from here: this set is now development data)

- **Columns placed by their order** (`workroom_core/match/tables.py`). A report table is usually a block copied from a sheet, so its columns run in the sheet's order. The report's columns are matched to the sheet's by how many rows agree, assigned in increasing order, and a column is placed only when every best assignment gives it the same source column and at least 90% of its figures equal its cell. This turned 1,051 more figures into automatic links and corrected six links that value alone had made to another period's column (a "June 2025 men" figure linked to "June 2024 men" because the two happened to be equal).
- A figure in a table cell is never set aside as chance (the listed-apart rule now applies to sentences only).
- Matcher speed (297 s to about 50 s) with identical decisions, and a fixed order for equal scores.

Effect on this report: automatic 3,221 to 4,307 (48.8%); asked 3,841 to 3,632; listed apart 1,490 to 613. Of the 53 real asked figures in the reader's sample, 25 became automatic links on the reader's own cell and none became a wrong one.

An independent reader then judged a fresh seeded sample of the links that are automatic now and were not in the blind run: **160 of 160 correct** (120 from this report, 40 from the DEECA statements). Caveat that matters: 118 of the 120 from this report sit in one 89-row table, so the independent decisions behind that number are far fewer than 160; three of the 40 statement links were judged "the same quantity" on something other than an exact label (a figure repeated in a second sheet).

## Not covered

PowerPoint and Excel-only documents; charts; the release step on this set; second and third cycles; people other than the builder; a third report from an unrelated author (the Department of Education files could not be downloaded from this machine: the host closes the connection). All three unseen-or-development sets are Victorian departments following the same reporting rules.
