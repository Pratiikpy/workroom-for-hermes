# Protocol for holdout 2: the Victorian Department of Health annual report 2024-25 (sealed 9 Nov 2026; deliberately NOT run yet)

Purpose. Holdout 1 (DEECA) was run blind and read; any fix made because of it makes DEECA development data. This second set was downloaded and sealed before any fix, so a later claim of precision can rest on files the matcher was not shaped by. Weakness stated: also a Victorian department, so the reporting conventions are similar to DEECA's and the VPSC pairs.

Data (public, health.vic.gov.au, downloaded 9 Nov 2026, kept outside the repository, hashes sealed):
- `budget-portfolio-outcomes.xlsx`: dccf221b91c899725c39e4ba24110438ee71b6539064ba5dabc6d1ed7a65ab3e
- `capital-projects-completed.xlsx`: d324e7670435a6491f38ade797e9a8c1109b1d6e5d6b0120678021c2721fd7f3
- `environmental-performance-reporting.xlsx`: 4646218a09c3a143813dd79ec9bf7f8e51979b1f4294a3045922c20bd4d0cc5b
- `financial-statements.xlsx`: be63ec7db8e6712a56c543821d02e6b397ec4f0628a58de38da825cad6679e5a
- `other-disclosures.xlsx`: 0e0e24e4603afe4f23a21f25378f8437cba265059f99dd4538d011c3831a880a
- `performance-reporting-non-financial.xlsx`: 7109ca4ef547bbc26e039e41e1deadc414a1941d6750d9f3bc39e897b96bef3f
- `portfolio-performance-reporting-financial.xlsx`: c3b69c2b514084e69f23994e99ce6ddc42301e4e62be148de26278993e852129
- `procurement-incl-ict-advertising.xlsx`: fbe2ee9e31fde3c2b2bd3efc38baf0bcab1b68af15e5b084e4377b87107c5267
- `report.docx`: 0cbc417a1eac00471209b6d44fb400efde1bb90db5827f7032d5ff6b9c3e9259
- `workforce-and-ohs.xlsx`: 3f8151b8dd950a348ca7bf630b382ee0921104cc9e7c1831436c099357d27d37

Pair. `report.docx` (the annual report, Word) with all nine workbooks together in one project.

Rules. The files have not been opened or read. Run once with `bench/verify/holdout_run.py`, after the step B and F changes are finished and frozen at a named commit; adjudicate as in `HOLDOUT1_PROTOCOL.md` (same seed, same sample sizes, builder and one independent reader, 95% Wilson bound). If a fix is made after reading this set, it is development data from then on.
