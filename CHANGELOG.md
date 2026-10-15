# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-15

The first release: a digital lab notebook for the Gardiner Lab suite, designed
after Trilium Notes.

### Added
- **Notebooks and days.** Each person's own notebook, with "Start today" (or any date) filing a
  day page under its year and month.
- **Notes in a tree.** Notes are kept apart from their places in the tree, so a note can sit in
  several places. Notes can be dragged to move them.
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
