# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added
- **Photos and attachments**, as in Trilium, on pages and protocols.
  - Any kind of file: Word, PowerPoint, Excel, PDF, CSV, GenBank and SnapGene, archives, anything.
  - Add them with **📎 Attach…**, by pasting a screenshot into text, or by dropping files onto it.
  - PDFs open in the browser's own viewer. Office files download with their real type, so they open
    in Word, PowerPoint or Excel. Each kind of file has its own icon.
  - Photos show in the text; other files become download links. Every note lists its attachments.
  - The files are kept in the notebook's database, so the suite's backup includes them.
  - Who sees and adds them follows the note.
  - Only PNG, JPEG, GIF, WebP and BMP photos show in pages, and only real PDFs open in the viewer
    (checked by their contents). SVG, HTML and other files a browser could run as a page download as
    plain files, so nothing attached can run in the notebook.
  - Files are limited to 25 MB each.
  - A copy of a note gets its own copies of the attachments.
  - Removing one leaves the note's earlier versions intact.

## [0.2.0] - 2026-10-15

### Added
- **🗑 Deleted**, at the bottom of the sidebar. It lists deleted pages and protocols with where they
  were, who deleted them and when; View shows one, and Restore brings it back.
  - A restore brings back what was deleted with it, to its old place, or to the top when that place
    is deleted too.
  - Owners restore their own pages; a protocol's author, their lab lead or an admin restores it;
    administrators can restore anything.

## [0.1.1] - 2026-10-15

### Fixed
- The suite's backup could not copy the notebook's database, and so failed altogether: the notebook
  kept it in SQLite's WAL mode, which cannot be read from the backup's read-only mount. It now uses
  the ordinary journal, as the other tools do, and switches an existing database over when it starts.

## [0.1.0] - 2026-10-15

The first release: a digital lab notebook for the Gardiner Lab suite, designed
after Trilium Notes.

### Added
- **Notebooks and days.** Each person's own notebook, with "Start today" (or any date) filing a
  day page under its year and month.
- **Notes in a tree.** Notes are kept apart from their places in the tree, so a note can sit in
  several places. A ＋ beside each note adds a page under it, as in Trilium. Notes can be dragged,
  or moved with "Move to…".
- **Search.** The box at the top of the sidebar (Ctrl+K or /) searches titles and everything written
  in pages and protocols: text, table cells and steps. Matches are highlighted in context.
  `#label` or `#label=value` finds notes by their labels.
- **Protocols tab.** The library has a tab of its own, with search, folders, who wrote each protocol
  and how often it has been used, and "Use today" to put a protocol into today's page.
- **How to write a protocol (start here).** A protocol in the library that teaches by example.
  Each example is a working template:
  - a master mix that scales with the number of reactions;
  - a scaled column (LB plates);
  - a dilution calculator with formulas and a total row;
  - a run record with fill-in and tick-off cells;
  - a step list;
  - a formula cheat sheet.
- **Make a copy** (⋯ menu) of any protocol or page, as your own to change. Ticks are not copied.
- **Favourite protocols.** Star a protocol to list it in your sidebar. Favourites come first when
  you add a protocol to a page.
- **Protocol library.** Shared by everyone. A protocol is changed by its author, their lab's lead
  or an administrator. It is put into a day as the version used, and the protocol shows the days
  that used it.
- **Active tables.**
  - Scaling by the number of reactions.
  - Column and cell formulas, with A1 references, ranges and SUM/MIN/MAX/AVERAGE/ROUND/ABS/IF.
  - Fill-in cells.
  - Tick-off cells and steps, stamped with who and when by the server.
- **From MoClo.** The MoClo Golden Gate protocol in the library. Saved MoClo assemblies go into a
  page as reaction tables that work out DNA volumes from concentrations, as MoClo does.
- **Plasmid links.** `@` or the Plasmid button links plasmids from the Plasmid Editor's library,
  and clicking one opens it in the editor.
- **Labels and relations, links and backlinks.**
- **History.** A revision for every change, edits close together kept as one, any version
  restorable. A save from an out-of-date window is held back.
- **Access.** Lab leads read their lab's notebooks and administrators read all of them. Text is
  cleaned on the server, so no page can carry scripts to its readers.
