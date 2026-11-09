# Protocol for the first independently authored workbook-and-report pair (written 9 Nov 2026, before any result was read)

Data. `Victorian-Public-Sector-Commission-Annual-Report-2020-21.docx` (accessible Word version, 85 pages, 1,373,925 bytes) and `VPSC-financial-statements-2020-21.xlsx`
(financial statements, 29 sheets, 81,612 bytes), both published by the Victorian Public Sector Commission on its own site as the report's "Report resources and other
formats". The two were written by the same agency for different purposes; neither was built from the other by me, and neither was looked at before this protocol.

Rules. Workroom is run on the pair as it is, with no change to the code between reading this protocol and the result. The run is reported as it comes out. Anything
fixed afterwards is labelled as a fix made after seeing the result, and a rerun after a fix is not blind.

What is measured, in order.
1. Find links: how many figures Workroom finds in the report, how many it links automatically, how many it asks about, how many have no source cell, and the time.
2. Precision of the automatic links: every one is read by hand against its sentence, the cell it points at and that cell's row and column headings, and marked right,
   wrong or unclear. Wrong links are listed in full. Nothing is sampled: if there are more than 60, the first 60 in document order are read and the rest are counted.
3. A release: for up to 10 automatically linked figures whose source cell is a constant, the workbook cell is changed (by editing the cell's value in the file's XML, so
   no other cell loses its saved value), Workroom stages and publishes the release with the owner acknowledgement, and the report is read back with python-docx and
   opened in the real Word. The only text that may differ is the linked figures; any other difference is a failure.
4. Owner effort: the number of figures Workroom asked about, as a count and as a share of the figures it found.

What is not covered: PowerPoint, charts, roll-forward, a second period (only one year's pair was confirmed to exist in this form), figures in tables whose source is a
formula cell, and any judgement about whether the report's claims are true. One pair is one data point, not a rate.
