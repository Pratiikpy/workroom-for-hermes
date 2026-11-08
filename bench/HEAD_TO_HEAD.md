# Head-to-head: one figure changes, the deck must follow (PowerPoint, identical input file and task for every engine)

Scenario (`research/bakeoff/corpus.py`, variant `base`): a deck whose headline sentence, KPI, table, chart and speaker notes all carry the revenue figures; a decoy shape repeats the same text; a person has hand-edited chart styling and a workbook note. Six text targets, two notes edits and one chart point must change; nothing else may.
Measured 7 Nov 2026 with `research/bakeoff/run.py` (engines E1 to E5), `baseline_officedesk.py` (M5) and `baseline_hermes.py` (M4). Same file, same task, same checker. One synthetic scenario family; PowerPoint only; each cell is a single run, not a distribution.

| Engine | Targets | Decoy untouched | Notes | Chart cache | Chart workbook | Human workbook note kept | Run formatting kept | Parts changed outside the edit | Validator |
|---|---|---|---|---|---|---|---|---|---|
| **Workroom kernel (shipped code)** | 6/6 | yes | 2/2 | yes | yes | yes | yes | 0 | pass |
| Stream-copy prototype (E3) | 6/6 | yes | 2/2 | yes | yes | yes | yes | 0 | pass |
| office-desk 0.1.1 (shape edit + deck-wide replace) | 6/6 | yes | 2/2 | **no** (no chart operation) | **no** | yes | yes | 0 | pass |
| Hermes bundled Office skill (`pptx_edit.py`) | 5/6 | **no** | 2/2 | yes | yes | **no** | yes | 4 | pass |
| python-pptx, careful use (E2) | 6/6 | yes | 2/2 | yes | yes | yes | yes | 4 | pass |
| python-pptx, naive replace (E1) | 6/6 | **no** | 2/2 | yes | yes | **no** | **no** | 4 | pass |
| OfficeCLI 1.0.160 (E4) | 5/6 (old value left in a target) | yes | 2/2 | yes | yes | yes | yes | 5 | pass |

Reading it fairly: office-desk is safe on text and loses only on the chart (it has no chart operation, which is also a design choice). python-pptx used carefully matches on content but rewrites 4 package-plumbing parts (a semantic no-op, yet more than the 0 the kernel changes). The Workroom kernel is the only row that is complete and changes nothing else. What this does NOT show: Word and Excel head-to-heads, messy business decks, Claude's Office add-ins (closed, not run), any speed advantage that matters (all engines except OfficeCLI take under 50 ms), and the layers above the editor (links, contracts, release) where the competitors have nothing to compare against.

## Second variant: the figure is split across formatting runs (`split-runs`)
Same task, but the number to change is broken across several text runs with different formatting. Results are the same for every engine as in the table above (Workroom kernel 6/6, decoy untouched, notes 2/2, chart and workbook ok, 0 collateral parts; office-desk 6/6 text, no chart update; bundled skill 5/6 and decoy touched; OfficeCLI 5/6). Two variants of one synthetic family still make this a narrow comparison, not a general ranking.
