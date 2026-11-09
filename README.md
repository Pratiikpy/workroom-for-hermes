# Workroom for Hermes

Workroom keeps your reports and decks in step with the numbers they came from, and only changes what must change.

You point it at a folder of Office files. It reads the numbers in your decks and Word reports, links each one to the spreadsheet cell it came from, and, when the source changes, prepares one release that shows exactly what will change. Nothing is written until you approve it. Your own edits are never overwritten, and a release can be restored from the Past releases list as long as you have not worked in those files since.

Status: early build (version 0.2.0). Everything below says what has and has not been tested. The evidence is in [`bench/EVIDENCE.md`](bench/EVIDENCE.md); every claim here cites a line there.

## Screenshots

These are from a real Hermes Desktop v0.23.0 session on Windows (not mockups), taken on a clean folder.

1. Find the links: each number in the deck is tied to the cell it came from. ![Find links](docs/screenshots/01-find-links.png)
2. Review what would change and approve exactly that release. ![Review and approve](docs/screenshots/02-review-and-approve.png)
3. Published, with a backup kept and the release listed under Past releases. ![Published](docs/screenshots/03-published-and-past-releases.png)
4. The Changes inbox: one card per changed source cell, with every place it reaches. ![Changes inbox](docs/screenshots/04-changes-inbox.png)
5. Before and after, drawn by PowerPoint from a private copy. ![Before and after](docs/screenshots/05-before-and-after.png)
6. Creating a file from sources: every figure listed with its cell, nothing written until approval. ![Create release](docs/screenshots/06-create-release.png)
7. The page editor floating over a session. ![Page editor](docs/screenshots/07-page-editor.png)
8. The change map: changed source cells on the left, the places they reach on the right. ![Change map](docs/screenshots/08-change-map.png)
9. Selecting a place shows its finding and lights its one link. ![Change map, finding](docs/screenshots/09-change-map-finding.png)

The whole first-run loop (make the sample, approve the deck, a new quarter arrives, see what changes, approve the update) is in [`docs/demo/first-run.gif`](docs/demo/first-run.gif).

## How it works

1. **Find the links.** Workroom reads decks (.pptx), reports (.docx) and workbooks (.xlsx) and links each number to a source cell using the value, the words around it, the period and the units. Equal numbers never create a link by themselves. When it is not sure, it asks you; it never guesses.
2. **See what would change.** When a source cell changes, you see every place it reaches, old value and new value, before anything is written.
3. **Approve one release.** For Word you can choose to release changes as real tracked changes, so a reviewer accepts or rejects each one. Approval is bound to the exact set of changes. A change made by hand in a document after the release was prepared stops the release. A hand-edited sentence is held, not overwritten.
4. **Publish and recover.** Files are replaced under a journal; a crash at any point recovers to the new state, and a backup of every replaced file is kept; the Past releases list restores a release, refusing if those files changed since.

Ask Why: for any linked number, Workroom says which cell it came from, which labels and period matched, the value now and at the last release, and what would happen if the source changed.

## The change map

Under "See what would change", **Map** draws the Changes inbox as a graph. Every box and line is a link the project holds, not a picture of it: on the left the source cells that changed (a dashed red box when a cell no longer holds a number), on the right the places in each document they reach, coloured by what will happen (will update, held for you, source missing), with a red or amber "!" where a finding needs your check. Select a box to follow its links: the old and new value, the sentence, why it will or will not change, and the finding with its evidence. "Show this file in its folder" uses the Desktop's reveal door. It works from the keyboard (Tab, Enter, Escape), and **List** is the same information as text.

What it does not draw: a calculated figure is its own box on the left (the inbox does not list the cells it was calculated from, so no lines are invented to them); at most 80 places are drawn, and the list has all of them; in a window narrower than 700 px the list is shown first. Tested against the project's own tie table (every drawn line is a link, every changed link is drawn), in a real browser with the real Desktop script, and driven in the real Hermes Desktop v0.23.0 on Windows (9 of 9 checks). Not clicked in the real Desktop: "Show this file in its folder".

## What a change means

A changed number is not the whole change. After an update Workroom reads what the new numbers do to the words around them and lists what needs your eyes before you approve.

- **Claims that stopped being true.** "Up from", "grew from X to Y", "exceeded", "record", "rose to" and "held steady at" are checked against the figures. A sentence that was true and is now false is flagged with the numbers that show it; its words are never rewritten for you. An unqualified "rose" is judged against the previous period, and against the year earlier when the sentence says so.
- **Calculated numbers.** A percent change, margin, difference or total that the sources reproduce is found by arithmetic, shown with its formula, and follows its sources once you accept it. It never changes sign silently: an "up 8%" that would become a fall is held. When several calculations fit, none is chosen for you.
- **Places the editor does not rewrite.** A number in speaker notes, chart text or a picture description that still shows an old value, a chart whose axis is fixed below a new value, and a figure in a changed sentence that nothing updates are reported, and stay reported until you change them or dismiss them.
- **A workbook that moves.** Each link remembers the headings of its source cell. If rows or columns are inserted or a window of periods slides along, the link follows its cell; when it cannot tell, it asks you and says why.
- **Charts already in a deck.** Each point is linked to its cell by the chart's series name and category, written to the chart and its embedded workbook together, and held when a person changed it or when the embedded cell is a formula.
- **A source that looks wrong.** If some figures lost their source cell while others are updated from the same workbook (a region, period or sheet is probably missing), or a source cell moved by a factor of 100 or more or became zero (the usual signature of a unit slip or a paste over the wrong range), the release carries a "Check" finding naming them. It does not refuse: it asks the owner to acknowledge it before approval. Not checked: types, value ranges, row counts, period coverage as a set.
- **Approval.** Findings marked "Check" must be acknowledged before the release can be approved, in the Desktop screen and in chat. A decision to dismiss a finding is remembered, so the same question is not asked every cycle.

## Roll forward

When the workbook has the next period, "Roll forward one period" in the Desktop screen (or the `workroom_roll_forward` tool) prepares one release that moves every linked figure to the same row's next column or row and advances the period words beside them, in the style they were written in: Q3 2026 to Q4 2026, Mar 2026 to Apr 2026, FY2025 to FY2026. It is refused, naming each figure, when a figure has no value for the next period. You approve once, and one restore undoes the whole roll. A number you roll or correct by hand stays managed. Chart periods and period words inside speaker notes are not rolled; the first is listed, the second is reported.

## Create, then keep in step

Workroom can also make the file, so its figures are tied to their sources from the first second instead of being matched later.

- **Create.** The agent writes a *spec* (text with `{fact:format}` slots for every figure) instead of an Office file. Workroom checks it, builds a PowerPoint deck (text, tables, KPI cards, native charts), a Word report or an Excel workbook (tied number cells, your formulas kept) in a separate process, and stages it as a release. Nothing is written until you approve, and Restore removes exactly what was created. Every figure carries a receipt: which cell, which concept and period, which unit and format. A percent shown as money, a Q3 figure placed next to Q2 words, or a cell the labels do not support is refused before anything is staged.
- **Brand.** A `brand.json` in the project (accent, ink, muted colours as six hex digits, a font name), or colour and font tokens read from a `DESIGN.md` (primary, text, muted, font family; nothing else in the file is used), themes the decks Workroom creates, unless a spec sets its own. `brand.json` wins over `DESIGN.md`. Decks only for now; Word reports and visual pages are not themed.
- **Changes inbox.** One card per changed source cell, listing every place it reaches with its sentence and what will happen: update, hold (you edited it, or it cannot be written faithfully) or blocked (the source is gone).
- **Before and after.** Under a prepared release, on Windows with PowerPoint installed, Workroom can draw the changed slides as they are now and as they will be after approval (it renders a private copy; your file is not touched). Elsewhere it says pictures are unavailable.
- **Visual pages.** A page of shapes and text (`*.scene.json`) with tied text, an editor in the Desktop (draw, move with snapping, resize, nudge, undo and redo, text edit, align, layers, comment to the agent), and exports to SVG, HTML and native PowerPoint shapes. Edits are a draft; saving stages a release for you to approve.
- **Project instructions.** `workroom.md`, `AGENTS.md` and `CLAUDE.md` in a project are shown to the agent only after you read and authorise their exact text, and they can never change who approves or what needs approval.
- **Try the sample.** On a first run, one click makes a sample project in Workroom's own storage, stages its deck for your approval, and lets you pretend a new quarter arrived.

Evidence for each is in `bench/EVIDENCE.md` (rows dated 8 Nov 2026). What is not verified is listed in the same rows: a real model (Gemini) has driven the creation and page tools in only one or two runs per scenario (it found a real defect, since fixed: typed-by-hand figures), so there is no repeatability data, the page editor passed automated keyboard, contrast and touch-event tests but has not been used with a real screen reader or a physical touch device, and the new Desktop screens were run on Windows only (the test suite also passes on macOS and Linux in CI).

## Schedule it

`/workroom-watch <project>` prints a two-line recipe for Hermes cron: a small wrapper script and a `hermes cron create ... --no-agent` line. On each run Workroom checks the sources and, if something changed, prepares one release and tells you where to approve it; if nothing changed it says nothing. No model is involved and nothing is ever approved or published by the schedule. Tested through the real Hermes scheduler on Windows (see the 8 Nov evidence row); delivery to a chat and sleep catch-up are not yet tested.

## What the agent can and cannot do

The agent gets tools to register a folder, find links, preview a refresh, prepare a release, explain a number, run the self-test, list source cells, create files from a spec, read and edit visual pages as drafts, export pages, read authorised instructions and propose changes to `workroom.md`. It can also prepare a roll-forward release (`workroom_roll_forward`) and list the calculated numbers it finds (`workroom_find_calculations`), and it can read what a change means because the findings travel with every prepared release. **No Workroom tool approves or publishes.** Only the owner, through an authenticated Hermes session in the Desktop screen or the in-chat release card, can approve. A verifying sub-agent can be given only the read-only toolset `workroom_ro` (plan, explain, selftest, sources, pages, where-used, what-if).

That is a guarantee about Workroom's tools and its editor, and it stops there. An agent that is also given a general shell, file-write or code-execution tool runs as the same operating-system user as the owner: it could edit an Office file directly or read the signing key. Workroom blocks the common ways (its write guard refuses Hermes file-write tools on Office files in a project and sends shell commands that look like writes, including the script a command runs, to your approval prompt), but a pattern guard is a heuristic, not a boundary. Where the guarantee has to hold, give checking agents `workroom_ro` and no shell.

## Honest guarantees

- Discovery writes nothing to your documents.
- A release changes only the numbers it lists. Untouched parts of a document keep byte-identical compressed content (tested on 144 PowerPoint and 106 Word packages from public test corpora).
- A stale file, a replayed or expired approval, an approval for a different set of changes, or an altered saved history stops the release. Approving or restoring takes a per-project lock, so two approvals of one release arriving together publish it once.
- It cannot stop another program from changing a file while Workroom is not running. It detects that by hash.
- It does not recalculate Excel formulas itself. Edited workbooks are flagged to recalculate when opened.

## Evidence (summary; details and caveats in `bench/EVIDENCE.md`)

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
| The 22 update cycles on real data, rerun after a defect these files exposed | 119 owner actions (was 135), 0 silent errors | templates and owner are mine |

## Known limits and what is not tested

- Run end to end in the real Hermes Desktop (v0.23.0, Windows) on small synthetic projects (light and dark, wide and narrow). The files other people made were driven through the service, the real Office apps, Telegram and Hermes' dispatcher, not through the Desktop page.
- Nothing from professional finance work was available to test on: the foreign files are the user's own documents and public test suites, which hold few numbers.
- Agent runs: a 3B local model and, on 9 Nov, hosted Gemini models (free tier, so one run per scenario on whichever model had quota) drove the real Hermes agent. The capable models used the tools sensibly, prepared releases, refused to approve and ignored a planted instruction; one of them, told to skip approval, got around the shell guard by writing a script and running it by name (the guard now reads such scripts; the real-model rerun was cut off by the rate limit). Five scenarios, one run each: no repeatability data.
- Numbers are read in English and US or Indian digit grouping. A decimal comma (189,45) and a European 1.234,56 are skipped, never edited; claims are English only.
- A workbook whose rows are told apart only by a number ("Store 101") makes the owner confirm the links instead of linking them automatically; a figure that differs from its cell by a factor of 1,000 or more is linked automatically only when the text or the cell's headings name that unit; otherwise the owner is asked.
- Charts are linked only when a sheet is embedded behind them; a chart whose data is typed into it, or lives in an external file, is left alone.
- A file written by a program that never calculated its formulas holds no values for them; Workroom says how many and asks you to open and save the file in Excel.
- Claims are read in English from a closed set of wordings. Anything else is listed as not checked, never guessed. Company earnings releases mostly state amounts ("grew 31%") without naming the baseline, so there Workroom checks a claim only when the percentage is a calculated figure it manages.
- A sentence is judged false only on its own figures or on the workbook's series; a claim that depends on outside knowledge is out of reach.
- Rolling forward needs the next period to be in the workbook and the periods to be readable headings (quarters, halves, fiscal years, months). Chart periods are not rolled.
- The update-cycle trials above use documents and an owner I simulated, on real public data, in one language.
- Measured on real earnings releases (see the table) but not on other kinds of messy business documents or other languages. On hand-written paraphrase tests the matcher never linked wrongly and, with a small built-in finance synonym list, resolved 94% by itself (that number is contaminated: the list was written after seeing the test wording; real gain unmeasured).
- The suite passes on Windows, macOS and Linux with Python 3.11 and 3.14 in GitHub Actions; the Hermes Desktop run itself was only done on Windows.
- A Word file whose main document holds more than one body element (Word shows only the first) is refused rather than edited. Word comments are never edited (human review text). Complex Excel models are tested by real Excel restructuring and by reading public workbooks, not on a large finance model.
- Messaging approval was run through a real Telegram bot (see the table); Discord and Slack, and a refusal using a second real person's account, were not run.
- A consistent rollback of every copy of Workroom's state to an older valid point is not detected (a signature proves authenticity, not freshness).
- The agent's file-write tools are blocked on Office files inside registered projects; a shell command that looks like it writes one is sent to your approval prompt (a heuristic that a determined script can evade).
- The signing key is readable by any program running as you, including an agent with a shell tool: the approval boundary stops the agent's Workroom tools, not a hostile process on your own account.
- Plugin-host isolation (`plugins.isolation: host`): Hermes' static audit calls Workroom host-ready, but it has not been run inside a real plugin host.
- Claude's Microsoft 365 add-ins were not run for comparison.

## Install and run

Requires Hermes 0.23.0 or later. Enable the plugin; Hermes installs its dependencies (`lxml`, `python-pptx`, `python-docx`). In Desktop, switch Workroom on under Plugins: Hermes keeps a package's Desktop screens off until you do, so a WORKROOM tab appears only after that. Run the self-test from the agent with the `workroom_selftest` tool.

Development: `pip install -r requirements-dev.txt` then `python -m pytest tests -q`.

## Disclosure

- Dependencies installed by Hermes: `lxml` (reading and patching Office files), `python-pptx` and `python-docx` (building decks and reports; `XlsxWriter`, which python-pptx brings, writes workbooks). Test-only: pytest, openpyxl, Playwright.
- Programs Workroom starts, all local, none with network access of its own:
  1. a Python child process (same interpreter as Hermes, 60 second limit, scrubbed environment) that runs only `workroom_core/build/worker.py` to build a file from a validated spec; it receives no project paths and no secrets and contains no network code (the operating system does not enforce that);
  2. on Windows, the system `icacls` tool once, to make Workroom's own signing-key file readable only by your account;
  3. on Windows with PowerPoint installed, and only when you press "Show before and after", PowerShell drives PowerPoint on a private temporary copy of a deck to draw slide pictures; the copy is deleted afterwards;
  4. nothing else: Workroom never starts a scheduled job itself (`/workroom-watch` only prints the lines you can save for Hermes cron).
- No network access, no secrets read from files or the environment, no binaries, no self-update. A `pre_tool_call` hook blocks the agent's file-write tools on Office files in registered projects and sends suspicious shell commands to your approval prompt.
- Files read and written: inside the folders you register (documents; `brand.json` and the colour and font tokens of `DESIGN.md`; `workroom.md`, `AGENTS.md` and `CLAUDE.md` only as text for you to authorise; a `workroom.manifest.json` history file per project; files you approve Workroom to create), and in the plugin data directory (state, backups, a signing key file kept for this plugin only). Nothing else on your computer is read.
- The scripts under `bench/` (benchmarks, the real-Desktop driver, and a small .NET console tool that runs Microsoft's Open XML SDK validator) are for testing only. The plugin never runs them, and no compiled file is committed.
- See `NOTICE.md` for sources and credits.
