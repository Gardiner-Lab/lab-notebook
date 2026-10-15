# Lab Notebook

The Gardiner Lab suite's digital lab notebook.

- **A notebook for everyone.** "Start today" files a page for the day under its year and month.
  Pages can hold pages (the ＋ beside each note adds one), and a page can sit in two places at once.
- **Search.** Titles and everything written in pages and protocols, from the box at the top
  (Ctrl+K). `#label=value` finds labelled pages.
- **A shared protocol library**, in a Protocols tab of its own, with folders, search and
  favourites. Your starred protocols are listed in the sidebar. Anyone can add a protocol and use any of them. Whoever wrote a
  protocol, their lab's lead and administrators can change it. Every version is kept, and a protocol
  used on a day keeps the version that was used.
- **Active tables.** Volumes scale with the number of reactions, cells can hold formulas (`=B*N`,
  `=SUM(F1:F6)`), some cells are filled in on the day, and steps and rows can be ticked off. The
  server records who ticked each one and when.
- **From MoClo.** The MoClo Golden Gate protocol is in the library from the start. Assemblies saved
  in the MoClo Library Tool can be put into a page as reaction tables, with each DNA's volume worked
  out from its concentration.
- **Plasmid links.** Type `@` in a page to link a plasmid from the editor's library. Clicking the link
  opens the plasmid in the Plasmid Editor.
- **Who sees what.** Your notebook is yours. Lab leads can read their lab's notebooks, and
  administrators can read all of them. Only the owner changes a notebook.
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
