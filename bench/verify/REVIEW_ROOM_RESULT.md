# The review room (9 Nov 2026)

What it is: the Workroom tab now shows a Word report or PowerPoint deck as Office draws it, with every linked figure marked on its page, as it stands and as it would be after the release, with the reason behind each mark. Nothing is changed by looking. Built on the Hermes Desktop's own plugin surface (a section of the Workroom tab; the Desktop's preview rail does not render Office files, see `research/hermes/preview_and_toolsets_2026-11-09.md`).

How: Word or PowerPoint (or, where Microsoft Office is missing, LibreOffice) saves a private copy of the file as a PDF; pdfium draws the page; the PDF's text layer says where each figure is; the document's figures are lined up with the page's figures in reading order (`workroom_core/review.py`). A figure that cannot be placed has no mark and is never given a guessed one. Marks: changes (blue), linked (green), needs you (purple), your edit, protected (amber), blocked (red). Without any Office, a structural list says in its own label that it is not a drawing of the document.

## Verified

- Real Hermes Desktop, driven as a person would (`desktop_review.py`, 7 of 7): add a project, find links, change the workbook underneath, open the review room, see the drawn Word page with the marks after the release, switch to the page as it is now, pick a figure and read where it came from, and the report file is byte-identical afterwards; no page or console error. Screenshots `bench/ui_shots/desktop_review_01..03`.
- A PowerPoint slide is drawn and marked the same way.
- A real 182-page Victorian statement (DEECA 2024-25): Word made the PDF in 30 s, pdfium read 5,352 figures from its text layer in 1 s, 4,340 of the document's 4,358 figures (99.6%) were placed. Checked against the page itself (`review_alignment_check.py`): in a random sample of 584, 562 (96%) sit on a line that carries their row heading or sentence; of the 22 the conservative check did not pass, the first 10 were read by eye and all were on the right line (a wrapped heading or a figure inside a sentence). So no wrong mark was found, and the claim is "96% pass a line check, none of 10 failures read were wrong", not "never wrong".
- Only the project's own documents can be asked for (path tests); the drawn files and PDFs live in the project's own state folder; the drawing is cached by file hash.
- 7 tests in `tests/test_review.py` (the drawing ones are skipped on a machine without Word and pdfium).

## Not verified, said plainly

- LibreOffice: the invocation is tested with a stand-in program only; it has not been run against a real LibreOffice, and the macOS and Linux Desktop were not run. Tried on 10 Nov: installing LibreOffice and running the suite inside WSL Ubuntu (the apt update hung and then the Windows system volume filled to a few megabytes, so the run was abandoned and about 1 GB of caches was cleared); Docker and winget were not tried for the same reason (1.7 GB free before the attempt). Needs disk space, not a code change.
- Dark mode: checked once with Chromium's dark colour scheme switched on (`desktop_review_05_dark.png`: the Desktop followed it, the page stays white as a document page does, marks and card stay readable); the Desktop's own theme picker was not driven. Narrow windows and screen-reader use were not checked; the marks are keyboard buttons with spoken labels and the figures are also listed under the page.
- Speed on first use: a large report takes about 30 s to draw once, then it is cached.
- A document edited in Word while the room is open is redrawn only when the files change (the cache is keyed by their bytes and times).
- "Select a figure and ask for a change" is not built as an edit: asking Hermes about a figure puts a read-only question in the message box. Changing a figure is done by changing its source; that keeps every write on the approved release path.
