# Lab Notebook

The Gardiner Lab suite's digital lab notebook.

- **A notebook for everyone.** "Start today" files a page for the day under its year and month.
  Pages can hold pages (the ＋ beside each note adds one), and a page can sit in two places at once.
- **Search.** Titles and everything written in pages and protocols, from the box at the top
  (Ctrl+K). `#label=value` finds labelled pages.
- **A protocol library**, in a Protocols tab of its own, with folders, search and favourites. Your
  starred protocols are listed in the sidebar.
  - A protocol belongs to its author's lab: the lab sees and uses it, other labs do not.
  - Whoever wrote a protocol, their lab's lead and administrators can change it, and share it with other
    labs (👥 Share). A share lasts until it is retracted. The other lab can use, copy and export it, not
    change it.
  - The protocols supplied with the notebook are every lab's.
  - Every version is kept, and a protocol used on a day keeps the version that was used.
- **A guide to start from.** "How to write a protocol (start here)", first in the library, shows
  every kind of table by example. Make a copy of it to start your own.
- **Active tables.** Volumes scale with the number of reactions, cells can hold formulas (`=B*N`,
  `=SUM(F1:F6)`), some cells are filled in on the day, and steps and rows can be ticked off. The
  server records who ticked each one and when.
- **From MoClo.** The MoClo Golden Gate protocol is in the library from the start. Assemblies saved
  in the MoClo Library Tool can be put into a page as reaction tables, with each DNA's volume worked
  out from its concentration.
- **Plasmid links.** Type `@` in a page to link a plasmid from the editor's library. Clicking the link
  opens the plasmid in the Plasmid Editor.
- **Who sees what.** Your notebook is yours. Lab leads can read their lab's notebooks, and
  administrators can read all of them. Only the owner changes a notebook, and those its pages are
  shared with.
  - **Working together on a page.** Share a page (or a day) with people or labs of your chair group
    (👥 Share, on the page): they open it and the pages under it under "Shared with me", change them
    and add pages under them, and can show it under a page of their own too (⋯ › Show also under
    another page), as in Trilium: one page in both notebooks, so a change shows in both. What they add
    stays in your notebook, the history keeps who changed what, and an open page shows others' saves
    within half a minute. Only you share it on or delete the shared page itself. Without chair groups,
    a page is shared within your own lab(s).
  - A lab lead can share a notebook of their lab with another lab or a person (👥 beside it). They can
    then read, search and export it, under "Shared with me", until the share is retracted.
- **Export.** ⤓ Export, on any page, day, protocol or folder, on a whole notebook, or on the
  library, exports it and everything under it.
  - **PDF**, to keep or send: photos where they are; an attached PDF's pages put in where it is
    attached; other files embedded in the PDF (opened from its paperclip). CSV, text and sequence
    files are printed as well. Tables show their worked-out numbers, and ticks who made them.
  - **Word (.docx)**, to edit: photos and an attached PDF's pages as pictures; other files in a zip
    beside the document, linked from it.
- **Gel photos.** ▥ Gel photo… puts in a gel photo: click the wells you loaded, and each gets a
  number on the photo (row by row, top to bottom, each left to right) and a row beside it to name
  its sample.
- **Numbered photos.** In the markup window, ① Number numbers plants (or anything) in the order you
  click them, with a table beside the photo to say what each is.
- **Mark up photos.** Click a photo to draw on it: pen, highlighter, arrows, boxes, ellipses and
  text. The original is kept as it is; the marked-up picture takes its place in the page, and its
  marks can be changed later.
- **Photos and files.** Attach them to pages and protocols with 📎 Attach…, or paste or drop them into
  text. Photos show in the page, and the backup includes them.
- **History.** Every change is kept with who made it, and any version can be restored.

## Running it

The notebook runs inside the [Gardiner Lab suite](https://github.com/Gardiner-Lab/gardiner-lab-suite),
behind its proxy at `/notebook/`. Sign-in is the suite's: the proxy says who is signed in, and the
notebook reads who is an administrator from the suite's account directory and who leads which lab
from the suite's own database. It has no accounts of its own. Don't expose it outside the proxy.

| Setting | Default | |
| --- | --- | --- |
| `NOTEBOOK_DATABASE_PATH` | `/notebook/notebook.db` | the notebook's own data |
| `MOCLO_DATABASE_PATH` | `/moclo/moclo.db` | accounts, and MoClo's saved assemblies (read only) |
| `EDITOR_DATABASE_PATH` | `/editor/plasmid_editor.db` | plasmids to link to (read only) |
| `SUITE_DATABASE_PATH` | `/suite/suite.db` | labs and their leads (read only) |
| `URL_PREFIX` | `/notebook` | where the proxy mounts it |
| `EDITOR_URL` | `/editor` | where plasmid links open |

## Development

    pip install -r requirements.txt
    pytest -q
    node tests/js/sheet.test.js

## Trilium

The notebook's design follows [Trilium Notes](https://github.com/TriliumNext/Trilium) (TriliumNext):
- notes kept apart from their places in the tree;
- labels and relations;
- revisions;
- journal-style day notes;
- links between notes.

It is a separate program with its own code; see [NOTICE](NOTICE).

## Licence

GNU Affero General Public License v3.0, as Trilium's. See [LICENSE](LICENSE).
