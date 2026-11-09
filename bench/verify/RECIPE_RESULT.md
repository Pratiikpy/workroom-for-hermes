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

## The window refresh (built later the same day), and what it did on the real statements

A copy of last period's report against a workbook whose window of periods has slid (this year's file holds 2025 and 2024 where last year's held 2024 and 2023) can now be refreshed in one roll: `workroom_roll_forward` / the Desktop route take `window: true`. Inherited links remember the headings they were made under (`intent_labels`) and keep them until a release is prepared or rolled, so a roll starts from "last year's 2024 column" and finds "this year's 2025 column" by its headings, even though last year's 2023 column no longer exists. Figures whose new period the workbook lacks keep their old numbers and the release lists them; figures with no single period in their headings are left as written; a cell that holds only a year advances with its column. Two generated reports pass end to end (figures rewritten, the year headings moved with them, nothing left out of step afterwards; a workbook that lacks the newest year rolls what it can and says so).

On the real DEECA statements it did **not** work at scale: 97 figures rolled and 51 were held back of about 3,200 inherited links, then an ordinary refresh brought 12 more up to date and held 106 behind the table integrity block. Most of the statements' source headings carry no period, and the two years' workbooks are laid out differently, so most figures cannot be followed from one year to the next by headings or by address. The refreshed copy was therefore not comparable with the department's published 2024-25 report (the 25 figures changed had no counterpart under a key that keeps the years), and no accuracy is claimed for the refreshed report. So the statement stays: a scored refresh of a real annual statement was not achieved.

What would make it work, not built: matching a last-year workbook to a this-year workbook structurally (sheet by sheet, row by row) before refreshing, so that a changed layout is mapped once and reused.
