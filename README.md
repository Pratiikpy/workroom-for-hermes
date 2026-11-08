# Workroom for Hermes

Workroom keeps your reports and decks in step with the numbers they came from, and only changes what must change.

You point it at a folder of Office files. It reads the numbers in your decks and Word reports, links each one to the spreadsheet cell it came from, and, when the source changes, prepares one release that shows exactly what will change. Nothing is written until you approve it. Your own edits are never overwritten, and a release can be restored from the Past releases list as long as you have not worked in those files since.

Status: early build (version 0.1.0). Everything below says what has and has not been tested. The evidence is in [`bench/EVIDENCE.md`](bench/EVIDENCE.md); every claim here cites a line there.

## Screenshots

These are from a real Hermes Desktop v0.23.0 session on Windows (not mockups), taken on a clean folder.

1. Find the links: each number in the deck is tied to the cell it came from. ![Find links](docs/screenshots/01-find-links.png)
2. Review what would change and approve exactly that release. ![Review and approve](docs/screenshots/02-review-and-approve.png)
3. Published, with a backup kept and the release listed under Past releases. ![Published](docs/screenshots/03-published-and-past-releases.png)
4. The Changes inbox: one card per changed source cell, with every place it reaches. ![Changes inbox](docs/screenshots/04-changes-inbox.png)
5. Before and after, drawn by PowerPoint from a private copy. ![Before and after](docs/screenshots/05-before-and-after.png)
6. Creating a file from sources: every figure listed with its cell, nothing written until approval. ![Create release](docs/screenshots/06-create-release.png)
7. The page editor floating over a session. ![Page editor](docs/screenshots/07-page-editor.png)

The whole first-run loop (make the sample, approve the deck, a new quarter arrives, see what changes, approve the update) is in [`docs/demo/first-run.gif`](docs/demo/first-run.gif).

## How it works

1. **Find the links.** Workroom reads decks (.pptx), reports (.docx) and workbooks (.xlsx) and links each number to a source cell using the value, the words around it, the period and the units. Equal numbers never create a link by themselves. When it is not sure, it asks you; it never guesses.
2. **See what would change.** When a source cell changes, you see every place it reaches, old value and new value, before anything is written.
3. **Approve one release.** For Word you can choose to release changes as real tracked changes, so a reviewer accepts or rejects each one. Approval is bound to the exact set of changes. A change made by hand in a document after the release was prepared stops the release. A hand-edited sentence is held, not overwritten.
4. **Publish and recover.** Files are replaced under a journal; a crash at any point recovers to the new state, and a backup of every replaced file is kept; the Past releases list restores a release, refusing if those files changed since.

Ask Why: for any linked number, Workroom says which cell it came from, which labels and period matched, the value now and at the last release, and what would happen if the source changed.

## Create, then keep in step

Workroom can also make the file, so its figures are tied to their sources from the first second instead of being matched later.

- **Create.** The agent writes a *spec* (text with `{fact:format}` slots for every figure) instead of an Office file. Workroom checks it, builds a PowerPoint deck (text, tables, KPI cards, native charts), a Word report or an Excel workbook (tied number cells, your formulas kept) in a separate process, and stages it as a release. Nothing is written until you approve, and Restore removes exactly what was created. Every figure carries a receipt: which cell, which concept and period, which unit and format. A percent shown as money, a Q3 figure placed next to Q2 words, or a cell the labels do not support is refused before anything is staged.
- **Brand.** A `brand.json` in the project (accent, ink, muted colours as six hex digits, a font name), or colour and font tokens read from a `DESIGN.md` (primary, text, muted, font family; nothing else in the file is used), themes the decks Workroom creates, unless a spec sets its own. `brand.json` wins over `DESIGN.md`. Decks only for now; Word reports and visual pages are not themed.
- **Changes inbox.** One card per changed source cell, listing every place it reaches with its sentence and what will happen: update, hold (you edited it, or it cannot be written faithfully) or blocked (the source is gone).
- **Before and after.** Under a prepared release, on Windows with PowerPoint installed, Workroom can draw the changed slides as they are now and as they will be after approval (it renders a private copy; your file is not touched). Elsewhere it says pictures are unavailable.
- **Visual pages.** A page of shapes and text (`*.scene.json`) with tied text, an editor in the Desktop (draw, move with snapping, resize, nudge, undo and redo, text edit, align, layers, comment to the agent), and exports to SVG, HTML and native PowerPoint shapes. Edits are a draft; saving stages a release for you to approve.
- **Project instructions.** `workroom.md`, `AGENTS.md` and `CLAUDE.md` in a project are shown to the agent only after you read and authorise their exact text, and they can never change who approves or what needs approval.
- **Try the sample.** On a first run, one click makes a sample project in Workroom's own storage, stages its deck for your approval, and lets you pretend a new quarter arrived.

Evidence for each is in `bench/EVIDENCE.md` (rows dated 8 Nov 2026). What is not verified is listed in the same rows: no third-party model has driven the creation tools yet, the page editor passed automated keyboard, contrast and touch-event tests but has not been used with a real screen reader or a physical touch device, and the new Desktop screens were run on Windows only (the test suite also passes on macOS and Linux in CI).

## Schedule it

`/workroom-watch <project>` prints a two-line recipe for Hermes cron: a small wrapper script and a `hermes cron create ... --no-agent` line. On each run Workroom checks the sources and, if something changed, prepares one release and tells you where to approve it; if nothing changed it says nothing. No model is involved and nothing is ever approved or published by the schedule. Tested through the real Hermes scheduler on Windows (see the 8 Nov evidence row); delivery to a chat and sleep catch-up are not yet tested.

## What the agent can and cannot do

The agent gets tools to register a folder, find links, preview a refresh, prepare a release, explain a number, run the self-test, list source cells, create files from a spec, read and edit visual pages as drafts, export pages, read authorised instructions and propose changes to `workroom.md`. **No tool approves or publishes.** Only the owner, through an authenticated Hermes session in the Desktop screen or the in-chat release card, can approve. A verifying sub-agent can be given only the read-only toolset `workroom_ro` (plan, explain, selftest).

## Honest guarantees

- Discovery writes nothing to your documents.
- A release changes only the numbers it lists. Untouched parts of a document keep byte-identical compressed content (tested on 144 PowerPoint and 106 Word packages from public test corpora).
- A stale file, a replayed or expired approval, an approval for a different set of changes, or an altered saved history stops the release.
- It cannot stop another program from changing a file while Workroom is not running. It detects that by hash.
- It does not recalculate Excel formulas itself. Edited workbooks are flagged to recalculate when opened.

## Evidence (summary; details and caveats in `bench/EVIDENCE.md`)

| Claim | Result | Caveat |
|---|---|---|
| Untouched parts identical after an edit | 144 of 144 PowerPoint packages, 106 of 106 Word packages | public test corpora, not messy business files |
| One number edited in a real file, nothing else moved | 77 decks, 39 Word documents, 161 embedded workbooks, 0 failures | text and numeric constants; small files |
| Links accepted automatically were correct | 951 of 951 on real chart decks (95% interval 0.996 to 1.0) | favourable corpus: labels come from the same workbook |
| Same-valued decoy sentences linked | 0 of 988 synthetic decoys | synthetic and optimistic |
| Release recovers after a crash | 16 of 16 injected crash points | simulated process death on Windows; not a power-off test |
| Head to head, one figure changes in a deck | complete and 0 collateral parts changed; office-desk 6/6 text but no chart; Hermes' bundled skill missed a target and touched the decoy | one synthetic scenario; PowerPoint only; see `bench/HEAD_TO_HEAD.md` |
| Read-only agent cannot reach write tools | 8 of 8 out-of-scope tools refused by Hermes' real dispatch; a live model (Gemini 2.5 Flash) told to approve, publish or edit directly refused and the file was unchanged | one adversarial run; one model |
| Automatic links on real earnings releases | 0 clearly wrong in 97 read by hand; 56 of 58 decided correct by an independent model judge (60 sampled of 265) | 10 SEC filings converted to Word; 265 of 6,636 numbers linked automatically, 2,433 sent to a person, the rest have no source cell |
| Word tracked changes open in real Microsoft Word | accept-all gives the new text, reject-all gives the original, 4 revisions by "Workroom", on 2 files | Word on Windows only; 16 of 16 real corpus files also validate in OfficeCLI |
| Approval from a real Telegram chat | release card with buttons shown, Approve published it, Cancel changed nothing, a sender not in `approvers` was refused | one throwaway bot, one owner account; Discord and Slack not run |

## Known limits and what is not tested

- Run end to end in the real Hermes Desktop (v0.23.0, Windows) on a small synthetic project only; not yet on a user's own documents.
- Measured on real earnings releases (see the table) but not on other kinds of messy business documents or other languages. On hand-written paraphrase tests the matcher never linked wrongly and, with a small built-in finance synonym list, resolved 94% by itself (that number is contaminated: the list was written after seeing the test wording; real gain unmeasured).
- The suite passes on Windows, macOS and Linux with Python 3.11 and 3.14 in GitHub Actions; the Hermes Desktop run itself was only done on Windows.
- Word comments are never edited (human review text). Complex Excel models are untested.
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

- Dependencies installed by Hermes: `lxml` (reading and patching Office files), `python-pptx` and `python-docx` (building new decks and reports from a spec, in a separate child process with a 60 second limit and a scrubbed environment). Test-only: pytest, openpyxl.
- The child process starts with the same Python as Hermes and runs only `workroom_core/build/worker.py`, which reads one JSON request and returns one file; it receives no project paths and no secrets, and contains no network code (the operating system does not enforce that; the child is not sandboxed beyond a scrubbed environment and a time limit).
- No network access, no secrets read from files or the environment, no binaries, no self-update. One shell command: on Windows it runs the system `icacls` tool once to make Workroom's own signing-key file readable only by your account. A `pre_tool_call` hook blocks the agent's file-write tools on Office files in registered projects and sends suspicious shell commands to your approval prompt.
- Files read and written: inside the folders you register (documents, plus a `workroom.manifest.json` history file per project), and in the plugin data directory (state, backups, a signing key file kept for this plugin only). Nothing else on your computer is read.
- See `NOTICE.md` for sources and credits.
