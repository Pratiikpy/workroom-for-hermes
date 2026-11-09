# Column questions: one question per report table column (9 Nov 2026)

When a column of a report table fits two or more workbook columns about equally, Workroom now asks once for the column, with the alternatives and their headings, instead of once for every figure. The answer is the owner's (`choose_column`, an owner route; there is no agent tool for it); it is remembered for copies of the report; every row of the column that agrees with the chosen column is then linked, a row that disagrees stays a question, and a tie between two source rows is settled by the closer row heading or left as a question.

## Measured on DEECA 2024-25 (development data from here on)

| | Statements x financial workbook | Annual report x five workbooks |
|---|---|---|
| Figures asked (after the reader fixes) | 995 | 1,125 |
| Column questions | 36, covering 236 of the 995 | 0 (its questions are prose figures, not table columns) |
| If every question is answered with its first alternative | 223 more links, asked figures 1,231 to 1,008 | no change |

Answering with the first alternative is **not** a safe default and is not what the product does. Against the independent reader's answers, of 24 figures that were really asked and were then linked this way, 10 got the reader's cell and 14 did not. Most of the 14 are the same figure in another table of the workbook (a note repeats the primary statement; a "Carrying amount" column equals a "Level 3" column), which is exactly why a person has to choose: the report table is the Level 3 table, not the carrying amount table. So the saving is real only as a count of questions: 36 questions the owner has to read and answer, against 236 figure questions, and the answer carries meaning that no rule can supply.

Said plainly: asked figures are still 995 for a first import of the statements, and 24% of them are covered by column questions. The rest are figures with several equal cells in different sheets or prose numbers. Grouping by whole table and sheet was tried first and withdrawn: confirming a group "yes" would have locked a cell the reader did not accept in 14 of 22 real cases.
