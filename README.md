# Workroom for Hermes

**Keep your reports and decks in step with the numbers behind them.**

Workroom links every number in your Word, PowerPoint and Excel files to the spreadsheet cell it came from. When a source changes it shows exactly which numbers in which files are affected, updates only those, keeps your own edits, and publishes one release that you approve and can restore. Nothing is written to your files until you approve.

> **Status: version 0.4.0, an early release.** What has been proven and what has not is stated plainly in [Evidence](docs/EVIDENCE.md) and [Limits](docs/LIMITS.md). The most important limit: on reports it had not seen, the links Workroom makes by itself were right in 357 of 360 judged cases, but the first import of a large report still asks a great many questions (3,841 on one blind run, about 88% of them real), so setting up a big report still takes real work.

![The change map in Hermes Desktop: changed source cells on the left, the places in each document they reach on the right](docs/screenshots/00-hero-change-map.png)

## Quick start

1. Use Hermes 0.23.0 or later and enable the Workroom plugin. In Hermes Desktop a **WORKROOM** tab appears once the plugin is switched on.
2. First time here? Choose **Make the sample project**. It builds a small workbook and board deck in Workroom's own storage, never in your folders, so you can try the whole loop safely.
3. With your own files: enter a folder that holds the workbook and the report or deck, then **Find links**, **Check the sources**, **Prepare release**, and **Approve and publish**. **Past releases** restores any of them.

Run the bundled self-test from the agent with the `workroom_selftest` tool. Development: `pip install -r requirements-dev.txt`, then `python -m pytest tests -q`. More: [glossary](docs/GLOSSARY.md), [contributing](CONTRIBUTING.md), [security policy](SECURITY.md), [changelog](CHANGELOG.md).

## Screenshots

These are from a real Hermes Desktop v0.23.0 session on Windows (not mockups), taken on a clean folder.

1. Find the links: each number in the deck is linked to the cell it came from. ![Find links](docs/screenshots/01-find-links.png)
2. Review what would change and approve exactly that release. ![Review and approve](docs/screenshots/02-review-and-approve.png)
3. Published, with a backup kept and the release listed under Past releases. ![Published](docs/screenshots/03-published-and-past-releases.png)
4. The Changes inbox: one card per changed source cell, with every place it reaches. ![Changes inbox](docs/screenshots/04-changes-inbox.png)
5. Before and after, drawn by PowerPoint from a private copy. ![Before and after](docs/screenshots/05-before-and-after.png)
6. Creating a file from sources: every figure listed with its cell, nothing written until approval. ![Create release](docs/screenshots/06-create-release.png)
7. The page editor floating over a session. ![Page editor](docs/screenshots/07-page-editor.png)
8. The change map: changed source cells on the left, the places they reach on the right. ![Change map](docs/screenshots/08-change-map.png)
9. Selecting a place shows its finding and lights its one link. ![Change map, finding](docs/screenshots/09-change-map-finding.png)

The whole first-run loop (make the sample, approve the deck, a new quarter arrives, see what changes, approve the update) is in [`docs/demo/first-run.gif`](docs/demo/first-run.gif).

## A room around your documents (Windows only so far)

Beyond keeping documents in step with their sources, Workroom gives every project folder a shared room that the agent works inside and you stay in charge of. Each piece below is built, tested and listed with its evidence in [`bench/EVIDENCE.md`](bench/EVIDENCE.md); what is not verified is named next to it.

- **Room.** Sources, memory the agent proposes and you approve or reject (with where it came from), and rules such as protected paths. Only you decide; the agent can propose.
- **Undo for the agent's file changes.** A copy of each file is kept before the agent changes it, and Restore puts it back. Changes made by shell commands are covered for the common cases (rm, mv, cp, sed -i, redirects) and not for everything.
- **Made tab.** Every file the agent produced, with a preview, a comparison with the version before, and approval of the exact version you accept. One inbox across all projects lists what waits for you.
- **Figure proof.** Each figure in the agent's text is marked *supported by a source*, *calculation verified* or *not verified*, from what the agent actually read in this session. It never says "true". On the test set the rule that flags a figure with no source did not reach its 95% bar; the measured numbers are in the evidence file.
- **Decks drawn without Office.** A deck or report is drawn from its own shapes and text, so the preview works with no Office program installed. It is a structural drawing, not a typeset page.
- **Layout check for decks the agent builds.** Overflowing text, tiny text, off-slide shapes, low contrast and overlaps are found before you see the deck. On 210 seeded faults it found all 210 and flagged none of 210 clean slides, but those faults were written by the same author; on files other people made the false-alarm rate is not verified.
- **Point-to-edit.** Change a few words in one place of a deck or report: only that shape or paragraph is touched, every other part of the file stays byte-identical, a figure linked to a source is refused, and you approve the result. 50 of 50 edits on real files had no collateral change.
- **Signed proof of a release, also inside the file.** A copy of the released Word, PowerPoint or Excel file can carry its own signed record. It survives the real Office programs opening and saving it, but a program that rewrites the file makes the content check fail, by design: the record proves the released version.
- **Scheduled checks.** A Hermes cron job prepares a release when a source changes and never approves or publishes it.

![The Made tab: a memo with each figure marked supported or not verified, and the evidence for the selected figure](docs/screenshots/10-made-tab-figure-proof.png)

![A deck drawn from its own shapes with no Office program, shown for approval](docs/screenshots/11-deck-drawn-without-office.png)

## How it works

1. **Find the links.** Workroom reads decks (.pptx), reports (.docx) and workbooks (.xlsx) and links each number to a source cell using the value, the words around it, the period and the units. Equal numbers never create a link by themselves. When it is not sure, it asks you; it never guesses.
2. **See what would change.** When a source cell changes, you see every place it reaches, old value and new value, before anything is written.
3. **Approve one release.** For Word you can choose to release changes as real tracked changes, so a reviewer accepts or rejects each one. Approval is bound to the exact set of changes. A change made by hand in a document after the release was prepared stops the release. A hand-edited sentence is held, not overwritten.
4. **Publish and recover.** Files are replaced under a journal; a crash at any point recovers to the new state, and a backup of every replaced file is kept; the Past releases list restores a release, refusing if those files changed since.

Ask Why: for any linked number, Workroom says which cell it came from, which labels and period matched, the value now and at the last release, and what would happen if the source changed.

## The change map

Under "See what would change", **Map** draws the Changes inbox as a graph. Every box and line is a link the project holds, not a picture of it: on the left the source cells that changed (a dashed red box when a cell no longer holds a number), on the right the places in each document they reach, coloured by what will happen (will update, held for you, source missing), with a red or amber "!" where a finding needs your check. Select a box to follow its links: the old and new value, the sentence, why it will or will not change, and the finding with its evidence. "Show this file in its folder" uses the Desktop's reveal door. It works from the keyboard (Tab, Enter, Escape), and **List** is the same information as text.

What it does not draw: a calculated figure is its own box on the left (the inbox does not list the cells it was calculated from, so no lines are invented to them); at most 80 places are drawn, and the list has all of them; in a window narrower than 700 px the list is shown first. Tested against the project's own link table (every drawn line is a link, every changed link is drawn), in a real browser with the real Desktop script, and driven in the real Hermes Desktop v0.23.0 on Windows (9 of 9 checks). Not clicked in the real Desktop: "Show this file in its folder".

## The review room

Under "Review the documents" the report or deck is drawn as Microsoft Office draws it, with every linked figure marked on its page: blue for the figures that change, green linked, purple needs you, amber your own edit (protected), red held back. A switch shows the page as it is now or as it would be after the release; choosing a mark says where the figure came from. Nothing is changed by looking. It needs Office on the machine (LibreOffice is supported in code and untested here); without it a list says it is not a drawing of the document.

## Recipes, column questions and the release record

- **Recipe.** Approve one report as the model for a recurring report; a copy of it inherits its links, each checked again, so last month's file is linked to the workbook in one step. Only the owner can approve it.
- **Column questions.** When a column of a report table fits two workbook columns about equally, you are asked once for the column ("this is the Level 3 column, not the carrying amount") instead of once for each figure. Every row is still checked against the column you chose.
- **Release record.** Every published release has a readable record: what changed with its source cell, the files by hash, the checks that ran or could not run, who approved it, how to restore it. It is evidence for you, not a signed statement.

## What a change means

A changed number is not the whole change. After an update Workroom reads what the new numbers do to the words around them and lists what needs your eyes before you approve.

- **Claims that stopped being true.** "Up from", "grew from X to Y", "exceeded", "record", "rose to" and "held steady at" are checked against the figures. A sentence that was true and is now false is flagged with the numbers that show it; its words are never rewritten for you. An unqualified "rose" is judged against the previous period, and against the year earlier when the sentence says so.
- **Calculated numbers.** A percent change, margin, difference or total that the sources reproduce is found by arithmetic, shown with its formula, and follows its sources once you accept it. It never changes sign silently: an "up 8%" that would become a fall is held. When several calculations fit, none is chosen for you.
- **Places the editor does not rewrite.** A number in speaker notes, chart text or a picture description that still shows an old value, a chart whose axis is fixed below a new value, and a figure in a changed sentence that nothing updates are reported, and stay reported until you change them or dismiss them.
- **A workbook that moves.** Each link remembers the headings of its source cell. If rows or columns are inserted or a window of periods slides along, the link follows its cell; when it cannot tell, it asks you and says why.
- **Charts already in a deck.** Each point is linked to its cell by the chart's series name and category, written to the chart and its embedded workbook together, and held when a person changed it or when the embedded cell is a formula.
- **A source that looks wrong.** If some figures lost their source cell while others are updated from the same workbook (a region, period or sheet is probably missing), or a source cell moved by a factor of 100 or more or became zero (the usual signature of a unit slip or a paste over the wrong range), the release carries a "Read first" finding naming them. It does not refuse: it asks the owner to acknowledge it before approval. Not checked: types, value ranges, row counts, period coverage as a set.
- **Approval.** Findings marked "Read first" must be acknowledged before the release can be approved, in the Desktop screen and in chat. A decision to dismiss a finding is remembered, so the same question is not asked every cycle.

## Roll forward

When the workbook has the next period, "Roll forward one period" in the Desktop screen (or the `workroom_roll_forward` tool) prepares one release that moves every linked figure to the same row's next column or row and advances the period words beside them, in the style they were written in: Q3 2026 to Q4 2026, Mar 2026 to Apr 2026, FY2025 to FY2026. It is refused, naming each figure, when a figure has no value for the next period. You approve once, and one restore undoes the whole roll. A number you roll or correct by hand stays managed. Chart periods and period words inside speaker notes are not rolled; the first is listed, the second is reported.

## Create, then keep in step

Workroom can also make the file, so its numbers are linked to their sources from the first second instead of being matched later.

- **Create.** The agent writes a *spec* (text with `{fact:format}` slots for every figure) instead of an Office file. Workroom checks it, builds a PowerPoint deck (text, tables, KPI cards, native charts), a Word report or an Excel workbook (tied number cells, your formulas kept) in a separate process, and stages it as a release. Nothing is written until you approve, and Restore removes exactly what was created. Every figure carries a receipt: which cell, which concept and period, which unit and format. A percent shown as money, a Q3 figure placed next to Q2 words, or a cell the labels do not support is refused before anything is staged.
- **Brand.** A `brand.json` in the project (accent, ink, muted colours as six hex digits, a font name), or colour and font tokens read from a `DESIGN.md` (primary, text, muted, font family; nothing else in the file is used), themes the decks Workroom creates, unless a spec sets its own. `brand.json` wins over `DESIGN.md`. Decks only for now; Word reports and visual pages are not themed.
- **Changes inbox.** One card per changed source cell, listing every place it reaches with its sentence and what will happen: update, hold (you edited it, or it cannot be written faithfully) or blocked (the source is gone).
- **Before and after.** Under a prepared release, on Windows with PowerPoint installed, Workroom can draw the changed slides as they are now and as they will be after approval (it renders a private copy; your file is not touched). Elsewhere it says pictures are unavailable.
- **Visual pages.** A page of shapes and text (`*.scene.json`) with linked text, an editor in the Desktop (draw, move with snapping, resize, nudge, undo and redo, text edit, align, layers, comment to the agent), and exports to SVG, HTML and native PowerPoint shapes. Edits are a draft; saving stages a release for you to approve.
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

## Evidence at a glance

| Question | What was measured | Caveat |
|---|---|---|
| Does an update touch only what it should? | Untouched parts stayed byte-identical in 250 of 250 public Word and PowerPoint packages; a release of 10 changed cells on a real government report rewrote exactly the 20 places it should and nothing else | public files and one independent report; Windows |
| Does the real software agree? | Word, Excel and PowerPoint open and read back every released file; Microsoft's Open XML validator reports no new error | Windows only |
| Are automatic links right on reports it had not seen? | 357 of 360 judged correct by an independent reader across two sets of public Victorian department reports (99.2%, 95% interval 97.6 to 99.8) | Word only, one government; see [Evidence](docs/EVIDENCE.md) |
| Are automatic links right? | Two independent reports from one agency: 0 wrong in 70 read by hand on the first; on the second (last year's report against this year's workbook) 6 wrong by label and 3 unclear of 181, all of which the reader now guards against or asks about | the guards were written after seeing those results, so they are not yet tested blind; the links not read by hand were checked mechanically only |
| Does it recover? | 16 of 16 injected crash points recover; restore is byte for byte | simulated process death, not a power cut |
| Can the agent publish? | No Workroom tool approves or publishes; capable hosted models refused, ignored a planted instruction and left files unchanged | one run each; a shell guard was bypassed once and hardened, see [Limits](docs/LIMITS.md) |

Full tables, caveats and the dated record: [Evidence](docs/EVIDENCE.md).

## What it does not do yet

- **Large first imports take real work.** On a report that is mostly small tables of counts, the blind run asked 3,841 questions (about 88% real); column questions and column order cut that on the files we tuned on, but not yet on a new one.
- **Four independent reports from one government have been measured, all Word.** No independent PowerPoint deck and no unrelated author yet; most other tests used documents and workbooks built for testing.
- **Windows is the tested desktop.** The suite also passes on macOS and Linux; the Hermes Desktop screens and the Office checks were run on Windows only.
- **The agent boundary covers Workroom's tools.** A shell guard stops the common ways around approval; it is a heuristic, not isolation.
- **Claims are read in English**, from a fixed set of wordings; anything else is listed as not checked.

The complete list is in [Limits](docs/LIMITS.md).

## Disclosure

- Dependencies installed by Hermes: `lxml` (reading and patching Office files), `python-pptx` and `python-docx` (building decks and reports; `XlsxWriter`, which python-pptx brings, writes workbooks). `pypdfium2` and `Pillow` (drawing the pages of a document in the review room: Office saves a private copy as a PDF and pdfium draws it; without them the room lists the figures instead). Test-only: pytest, openpyxl, Playwright.
- Programs Workroom starts, all local, none with network access of its own:
  1. a Python child process (same interpreter as Hermes, 60 second limit, scrubbed environment) that runs only `workroom_core/build/worker.py` to build a file from a validated spec; it receives no project paths and no secrets and contains no network code (the operating system does not enforce that);
  2. on Windows, the system `icacls` tool once, to make Workroom's own signing-key file readable only by your account;
  3. on Windows with PowerPoint installed, and only when you press "Show before and after", PowerShell drives PowerPoint on a private temporary copy of a deck to draw slide pictures; the copy is deleted afterwards;
  4. nothing else: Workroom never starts a scheduled job itself (`/workroom-watch` only prints the lines you can save for Hermes cron).
- No network access, no secrets read from files or the environment, no binaries, no self-update. A `pre_tool_call` hook blocks the agent's file-write tools on Office files in registered projects and sends suspicious shell commands to your approval prompt.
- Files read and written: inside the folders you register (documents; `brand.json` and the colour and font tokens of `DESIGN.md`; `workroom.md`, `AGENTS.md` and `CLAUDE.md` only as text for you to authorise; a `workroom.manifest.json` history file per project; files you approve Workroom to create), and in the plugin data directory (state, backups, a signing key file kept for this plugin only). Nothing else on your computer is read.
- The scripts under `bench/` (benchmarks, the real-Desktop driver, and a small .NET console tool that runs Microsoft's Open XML SDK validator) are for testing only. The plugin never runs them, and no compiled file is committed. One of them, `bench/verify/agent_dispatch.py`, imports two private Hermes modules to drive Hermes's own tool dispatcher; the catalog validator warns about it, and the plugin itself never imports it or those modules.
- See `NOTICE.md` for sources and credits.

## Licence

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
