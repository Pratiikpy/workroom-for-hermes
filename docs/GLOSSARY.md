# Glossary

The words Workroom uses on screen, in chat and in the documentation. Each one means the same thing everywhere.

| Word | Meaning |
|---|---|
| **Project** | A folder of Word, PowerPoint and Excel files that Workroom has been told about. Workroom reads and writes only inside it. |
| **Source** | A workbook (`.xlsx`) whose cells hold the numbers the documents quote. |
| **Link** | The connection between one number in a document and the source cell it came from. Workroom finds links; you confirm the ones it is unsure of. |
| **Linked number** | A number in a document that has a link. It follows its source cell. |
| **Find links** | Reading the documents and connecting each number to a cell. It writes nothing to your files. |
| **Need you** | A number Workroom found a likely cell for but is not sure about, so it asks. |
| **Coincidence** | A short number that equals some cell only by chance, with nothing in the text naming it. These are listed apart and not asked about; you can still link one. |
| **No source** | A number for which no cell in the workbook fits. It is left as written and reported as unverified. |
| **Changes** | What would change if the sources were applied now: which numbers, in which places, from what to what. |
| **Change map** | The Changes drawn as a graph: changed source cells on the left, the places they reach on the right. Every line is a link the project holds. |
| **Will update / held / blocked** | What happens to a place: it will be rewritten; it is left alone because you edited it by hand or it cannot be written faithfully; its source cell is gone. |
| **Finding** | Something to read before approving, such as a sentence an update makes false. A finding marked **Read first** must be acknowledged before the release can be approved. |
| **Release** | One prepared, approved set of changes. It is bound to the exact files and changes you reviewed; if either changes, it must be prepared again. |
| **Prepare release** | Building a release for review. Nothing is written yet. |
| **Approve and publish** | Writing the release. Only you can do this, in the Desktop screen or in a chat approval. A backup of every replaced file is kept. |
| **Restore** | Undoing a release from Past releases. It refuses if you have edited those files since. |
| **Roll forward** | Moving every linked number to the next period in one release. |
| **Held** (a link) | You changed a linked number by hand. Workroom leaves it alone and says so. |
| **Created file** | A file Workroom built from a description of its content, with every figure linked from the start. |
