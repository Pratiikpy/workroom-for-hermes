# Reporting recipe on real documents (9 Nov 2026)

What was built: the owner's approved snapshot of one model report's links (`workroom_core/recipe.py`). A copy of the model found in the project inherits those links as ordinary links; each is then checked by the same rules as any link (the figure must still be where the model had it or have the same words around it, a source that moved is followed by its headings, a changed figure is held, anything that does not fit is dropped or asked). Agents may propose a recipe (`workroom_recipe_propose`) and read the status (`workroom_recipe_status`, in the read-only toolset); only the owner route (`recipe-approve`) installs it, bound to the digest the owner was shown, and it is refused if the model changed after the proposal. Ten tests in `tests/test_recipe.py`.

## Measured on Victorian DEECA 2023-24 statements and workbook, then the 2024-25 workbook dropped in under the same file name (`recipe_cycle.py`)

| | Count |
|---|---|
| Figures in the model report | 4,660 |
| Links made in cycle 1 (accepted) | 3,030 |
| Left out of the recipe (not accepted or confirmed) | 1,412 |
| Copy of the model next to the new workbook: links inherited and still accepted | 2,119 of 3,030 (70%) |
| Inherited links turned into questions, mostly "more than one cell has its old headings" (270) or the source moved with several candidates | 882 |
| Inherited links dropped because the source is gone | 29 |
| Baseline, no recipe: the same copy matched by value against the new workbook | 1,444 accepted, 971 asked, 1,864 no source |

## Not achieved, said plainly

The refresh itself was not scored. In an annual statement the workbook slides: this year's file holds 2025 and 2024 columns and "Balance at 1 July 2024" rows where last year's held 2024 and 2023. A copy's links follow their headings, so the year columns stay on the same year and the balance rows (whose old date no longer exists) keep their address. Rolling that mixture forward is correctly refused ("has no 1 Jul 2025 value"): half of it is already in the new window. So no release was produced and nothing was compared with the department's published 2024-25 report. What was fixed on the way: a dated label such as "Balance at 1 July 2023" or "as at 30 June 2025" is now a period that steps by a year (it used to be read as a month and blocked the roll with "no Aug 2023 value").

What would make this refresh work, not built: a window-aware refresh for sliding annual workbooks that moves the whole link set together (comparative columns become the new prior year, current becomes the new year) instead of per-figure relocation. The flow that works today is the one the tests cover: a copy of last period's report, the workbook updated in place, links inherited, one release.
