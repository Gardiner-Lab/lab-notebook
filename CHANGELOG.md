# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] - 2026-10-16

### Added
- **Number plants (or colonies, seedlings…) on a photo**, with the ① Number tool in the markup
  window. Click each one: it gets the next number, in the order clicked, and a row in a table beside
  the photo for a label and a note. Click a number to take it away; the rest renumber.
  - Saved, the photo becomes a numbered photo where it was in the page: the photo with its numbers,
    and the table beside it, like a gel's. Its labels can be changed in the page, and more spots
    numbered (✚ Number spots).
  - The numbers are not drawn into the photo, so numbering alone makes no marked-up copy; drawing
    does, as before. Exports draw the numbers on, with the table beside.
  - On a gel, ✏️ Mark up opens its lanes in the same window, numbered by rows as before.

## [0.8.0] - 2026-10-16

### Added
- **Mark up photos**: draw and write on a photo in the page.
  - Click a photo in the text (✏️ Mark up), or ✏️ beside it under Attachments, or ✏️ Mark up on a gel.
  - Tools: freehand pen, highlighter, arrows, lines, boxes, ellipses and text, in six colours and three
    sizes, a rubber that takes away a whole mark, Undo and Redo (Ctrl+Z, Ctrl+Y). Works with a mouse,
    a pen or a finger.
  - **The original photo is never changed.** The marked-up picture is a new attachment that takes its
    place in the page, and the original stays under Attachments. The marks are kept, so opening the
    picture again brings them back to change; saving again replaces the marked-up picture, not the
    original. Earlier versions of the page still show the picture as it was.

## [0.7.1] - 2026-10-16

### Fixed
- **Gels with more than one row of wells** (a comb at the top and more further down) were numbered
  left to right across all of them, mixing the rows. Lanes are now numbered row by row, top to
  bottom, and each row left to right. The table shows where each new row starts.

## [0.7.0] - 2026-10-16

### Added
- **Gel photos with their wells marked** (▥ Gel photo… in the Add bar). Choose a photo on the page or
  upload one, then click each well that was loaded.
  - Each click puts a number on the photo, and a row in a table beside it for the sample and a note.
  - Lanes are numbered row by row, top to bottom, each row left to right, whatever order they are
    clicked in.
  - Click a number to take it away; Mark wells adds more later.
  - Pointing at a lane's row lights up its number on the photo, and the other way round.
  - Exports show the photo with its numbers drawn on, and the lanes beside it. Sample names are
    found by search.

## [0.6.0] - 2026-10-16

### Added
- **Export** to PDF or Word, from any level of the tree: a page, a day, a month, a folder, a protocol,
  a whole notebook or the library, with everything under it (or the page alone).
  - PDF: a cover, contents with page numbers, and each page with who wrote it and when.
    - Photos are where they are in the text.
    - An attached PDF's pages are put in where it is attached.
    - Other files are embedded in the PDF; CSV, text and sequence files are printed too.
    - Tables show their worked-out numbers, ticks who made them and when.
  - Word (.docx), to edit: photos and an attached PDF's pages as pictures, and other files in a zip
    beside the document, linked from it.
  - Exports run in the background with their progress shown, and are kept for an hour.
- **Sharing notebooks.** A lab lead (or an administrator) can share a notebook of their lab with
  another lab or a person, who can then read, search and export it, under "Shared with me". It stays
  shared until the share is retracted.
- **Sharing protocols** with other labs, by whoever may change the protocol, until retracted.

### Changed
- **Protocols belong to their author's lab** and are seen by that lab only, unless shared. Protocols
  written before keep their author's lab. The protocols supplied with the notebook stay every lab's.
- The image includes Pango and fonts, for the PDFs.

## [0.5.0] - 2026-10-16

### Added
- **Links to Lab Stocks.** `@` in a page (or 🧫 Stock… in the Add bar) links a glycerol stock or
  primer. The link opens it in Lab Stocks, which lists the notebook pages that mention each stock.

## [0.4.1] - 2026-10-15

### Fixed
- Links to the Seed Bank open the right page for codes that start with a lab code (GL-S-0042), as
  well as older ones (S-0042).

## [0.4.0] - 2026-10-15

### Added
- **Links to the Seed Bank.** Type `@` in a page, or use 🌱 Seed… in the Add bar, to link a seed
  lot, plant or line from your lab's seed bank. The link opens it there, and the seed bank lists the
  notebook pages that mention each record.

## [0.3.0] - 2026-10-15

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
