# Protocol for holdout 1: the Victorian Department of Energy, Environment and Climate Action (DEECA) annual report 2024-25 (written 9 Nov 2026, before any run)

Why this set. WIN_PLAN v3 step B asks for fresh pairs from unrelated authors, frozen before tuning. DEECA is a different department from the Victorian Public Sector Commission (the two development pairs). It is still a Victorian government body, so it follows the same state reporting directions: this is a weakness of the holdout (similar conventions), stated here. It is a later year (2024-25) and about ten times the size.

Data (public, downloaded from deeca.vic.gov.au on 9 Nov 2026; kept outside the repository, hashes sealed here):
- `report.docx`: ca258cb3c8c9218a38b6d8b4509555894d889c0bd72505255bdb3170d03b9dc3
- `financial_statements.docx`: cbb97db0dc29c53d348f41d52fa19de830834d061dae2405fefbfccfac7763b5
- `datavic_budget_outcomes.xlsx`: 3d4b55595f1d7857b82fb4d8927c5807db83f413f23b961f42126ebe4e179970
- `datavic_environment.xlsx`: d1c3a97e673325f2a9d71276fb51342d9751187276e6d762a72de1cae644983c
- `datavic_feed_in.xlsx`: a13dbd19e8edb629a6cf952730aa0b2fb2cfd9ec5095a3add6789c0e278bcd73
- `datavic_financial.xlsx`: c7ea9b15def55dc8104797e191c7b935dfdd3dfdfc204fc32fdf6773ceec279c
- `datavic_people.xlsx`: e95ccb3dc153b65f192460e246ad22284be3f6ff41447b31b6505ea714143252

Pairs. H1a: `financial_statements.docx` with `datavic_financial.xlsx` (same period, the natural pair). H1b: `report.docx` with all five workbooks together in one project (an annual report draws on many sources, as a real owner would hold them). Cross-period and PowerPoint cases are separate holdouts.

Rules. The files were not opened or read before this protocol. The product code is that of commit ccf76c3 (only this protocol and the harness are added; no product file changes between this protocol and the run). One run per pair with `bench/verify/holdout_run.py`, reported as it comes out; anything fixed afterwards is non-blind and labelled so, and the set then joins the development data (a new holdout is needed for a further blind claim).

What is measured, per pair, with every number counted from the output file and none typed by hand. (1) The five buckets over every figure found: linked automatically, asked, listed as coincidence, no source found, plus the run time. (2) Precision of the automatic links: a seeded random sample of up to 120 (all if fewer), seed 20261109, drawn by the harness. (3) Recall check: a seeded sample of up to 80 figures with no source, adjudicated for whether a correct source cell exists in the workbooks; a seeded sample of up to 60 asked figures (is the right cell among the candidates shown) and up to 40 coincidences. (4) Adjudication is done twice and kept apart: by the builder (reading the context and the source cell) and by one independent reader who has not seen the matcher, its reasons or its scores, only the sentence, the figure and the candidate cell with its headings and value; disagreements are reported, not smoothed. (5) The error rate is stated with its sample size and a 95% Wilson upper bound; zero wrong in n is "at most about 3/n" and never "no errors". (6) Time and the count of owner decisions the first import would need are taken from the buckets (asked + coincidences are counted as unresolved, not as solved).

Not covered: PowerPoint, charts, prose claims, second and third cycles, the release test on this set, people other than the builder using it. The builder wrote the matcher, which is why an independent reader is used for the adjudication.
