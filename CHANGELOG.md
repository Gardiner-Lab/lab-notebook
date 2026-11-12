# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [0.26.1] - 2026-11-12

### Fixed
- **A to-do list's block buttons no longer cover its first task.** The list leaves room above it for the
  block's ↑ ↓ ✕, which sat on top of the first task's **→ Next week**.

## [0.26.0] - 2026-11-12

### Added
- **A week's to-do list.** On a day page, **＋ Week's to-do** makes one list for that week (Monday to Sunday), a
  page of its own shown under every day page of the week, and under any started later. A task is a line of text
  in which `@` tags a plasmid, stock, seed lot, track or page, as in any text; ticked by whom and when. **→ Next
  week** moves a task still to do on to next week's list: it stays on this week's, marked as moved, and is on next
  week's as soon as that list is made, saying where it came from. **Bring back** undoes it while it is not ticked
  there. Deleting a day takes the list only when no other day of the week shows it. Lists print in PDF and Word
  exports.

### Changed
- **Start today** is now **Today**.

## [0.25.0] - 2026-11-11

### Added
- **Links to genome tracks.** Type `@` and choose *A genome track* to link a page to a track in the Genome Browser,
  found by its name, experiment or genome. The link opens the track's genome with it on, and goes into PDF and Word
  exports as a link there.
- **Which pages link to a record.** `GET /api/mentions?type=track&id=…` lists the pages linking to a track (or a
  plasmid, seed or stock) that the asker may open: the Genome Browser shows them under a track's Details.

## [0.24.0] - 2026-11-08

### Demo
- **The teaching demo sees only the demo's.** Someone in the suite's demo sees the demo's notebooks and protocols and the protocols supplied with the notebook; not a protocol a real lab or an administrator gave every lab, nor anything a real lab or person shares with them. Their share forms list only the demo's labs and people.

## [0.23.1] - 2026-11-07

### Fixed
- **Pasted bullet points became a table.** Word, web pages and emails copy a list as each bullet, a tab,
  then the item, and any pasted text with a tab in it was taken for spreadsheet cells. A paste whose
  tabs only follow list markers (`•`, `o`, `▪`, `-`, `*`, `1.`, `a)`, `ii.`…) is now a list: a bulleted or
  numbered one, nested where Word's markers or the indentation say so, with the lines around it kept as
  text and web addresses in it made links. Spreadsheet cells, and a copy whose HTML is a table, are
  still pasted as a table.

## [0.23.0] - 2026-11-07

### Added
- **Web links.**
  - **🔗** in the formatting bar, or **Ctrl+K** while writing, adds a link to the selected text,
    or changes or removes the one already there. It takes `https://…`, `www.…`, a bare domain or
    an email address.
  - **Pasting keeps links.** Copied from a web page, an email or another page, links stay links
    (styles and scripts are still dropped). An address pasted on its own becomes a link, or links
    the selected text, and addresses in pasted text are linked.
  - Links open in a new tab when clicked, as before.
- **"1. " starts a numbered list**, as "- " starts a bulleted one. The *1.* button does the same.

### Changed
- **Who sees whose notebook follows the lab roles**, unless something is shared:
  - a **lab admin** sees every notebook in their lab, lab leads' and other lab admins' too;
  - a **lab lead** sees every one but a lab admin's (so now other lab leads' as well);
  - a **member** sees only their own.

  Lab admins are told apart from lab leads by the suite's `lab_admin` flag, which the notebook now
  reads. Someone who has left is open to their lab's leads again, as before.
- Ctrl+K in a page's text makes a link. Elsewhere it still jumps to search.

### Fixed
- **Lines typed with Enter could run together when saved.** In text not already in a paragraph,
  the browser starts a new line as a `<div>`, which the server does not keep, so the lines were
  joined. New lines are now paragraphs, and a `<div>` line is saved as one.

## [0.22.0] - 2026-11-05

### Fixed
- **The formatting bar was out of reach in a long section.** It was placed once, just above the top of
  the text, so in a section taller than the window it sat above the screen as soon as you scrolled down
  to write - and headings and bullets could not be used there at all. It now stays in sight while you
  write, below the page's own bar, and follows the section as it scrolls.

### Changed
- **A lab admin's notebook is their own.** Leading a lab opens the notebooks of its members, which is
  what leading it is for, but it opened the notebooks of the lab's other lab admins too, each being a
  member of the lab. One lab admin no longer reads another's notebook, and such a notebook is no longer
  listed for them or shareable by them.
- An **administrator of the suite** still reads every notebook, as before.
- A lab admin **who has left** is read by the lab's remaining ones again, as anyone archived is, so that
  their work stays reachable rather than needing a restore from backup.

## [0.21.2] - 2026-11-05

### Changed
- The Plasmid Editor is now called the **Sequence Editor**. Every mention and link here follows the new
  name. Nothing else changes: the tool is at the same address, and records and links are untouched.

## [0.21.1] - 2026-11-05

### Added
- **A line begun with "- " becomes a bulleted list.** Type a dash and a space at the start of a line, and the
  next character typed turns the line into a list item, the dash taken away. A dash in the middle of a line,
  or in a list, table cell or code, is left as it is.

### Fixed
- **Another day is typed as dd-mm-yyyy.** The box beside **Start today** was the browser's own date box, which
  follows the browser's language and so often asked for yyyy-mm-dd or mm/dd/yyyy. It now takes the day as
  dd-mm-yyyy (2-11-2026 and 02/11/2026 too) and Enter opens or starts it; the calendar button beside it picks a
  day as before. A day that does not exist, or a year that is not four figures, is refused with a message.

## [0.21.0] - 2026-11-04

### Added
- **Steps can be moved.** Drag the ⋮⋮ at the left of a step to where it should go (a line shows where it
  lands), or press Alt+↑ / Alt+↓ in it. A step keeps its tick when it moves. Until now a step could only be
  added at the bottom.
- **A protocol can be added to any page, as a page of its own.** One **＋ Add to page…** button on a protocol
  (and in the library list) replaces **Use today**. It offers **Add to today** first, then the pages and days
  you may add to, newest first. The protocol becomes a new page named for it under the one chosen, holding the
  protocol as it is now with fresh ticks, its version recorded and listed under the protocol's *Used on*,
  instead of being added to the end of the day's own content. `POST /api/protocols/<id>/use` does it
  (`parent_id`, or today's page when left out).

### Fixed
- The buttons at the top of a protocol (or any page) ran out of room in a narrower window and were squeezed,
  their names breaking over two lines, so they no longer lined up with the page. They now keep their shape
  and move to a second row when there is no room.
- **A year, month or day can be deleted**, for one started by a typo (a year typed as 6, or 6202). It goes to
  Deleted with the days under it, and can be brought back. A day, month or year with a booking on it is kept
  until the booking is cancelled in Booking, because the notebook would only make its page again.
- `GET /api/search` takes `editable=1`, to list only the pages the person may change.

### Changed
- A deleted day, month or year comes back only if there is no page for the same date by now. A new one made
  since would stand beside it; delete the new one first, or copy over what is needed.

## [0.20.0] - 2026-10-31

### Added
- Every page's top bar now links to **all** the suite's tools, not a few: a row of them beside the tool's own
  name, the one you are on marked, names shown where there is room and icons alone when it is narrow. The list
  is the suite's own (`/tools.json`), so a tool added there appears here too; on its own, outside the suite,
  nothing is added.
- The bar is in two rows: the suite's on top — its tools, the dashboard, help, about and who is signed in —
  and this tool's own pages on the row under it, as the MoClo tool and Lab Stocks already read. A page with no
  pages of its own keeps a single row.
- The pages no longer assume whose lab is running the suite: "the Gardiner Lab" and "the lab's own server"
  are now "your lab" and "your own server", so they read correctly wherever it is deployed.

### Fixed
- The bar's "Trellis Tools" link pointed back at the tool itself instead of the suite's own page.

## [0.19.0] - 2026-10-30

### Added
- A **Help** page, *How to use the Lab Notebook*: how the notebook is arranged, writing a day, formatting,
  tables, steps, gel photos, attachments, links to plasmids, stocks and seeds, protocols, labels, sharing,
  history and export, and putting mistakes right. Linked from the top bar and from the welcome panel.
- **About** says much more: what the notebook holds, how it is arranged, how it fits with the other tools,
  who sees what, and what is kept.
- A page with notes under it shows them below its own content, as Trilium does: a card for each, with the
  start of its text, its first picture, how many notes are under it, and who saved it when; a click opens it. A
  note with no text of its own (a day whose work is in pages under it, a month, a year) shows what is under it
  instead: their titles, newest first, and the first picture among them.
- Attached documents open in the notebook itself: a photo, PDF, Word, PowerPoint or Excel file or text file,
  clicked in Attachments or in the text, is shown over the page (an office file as its PDF), with ‹ › (or the
  arrow keys) to go through the note's others, ⤓ to download the original and ↗ to open it in a tab of its own;
  Esc closes it. Ctrl- or ⌘-click still opens a new tab, and other files still download.

## [0.18.0] - 2026-10-30

### Added
- Tables paste in from Excel, Google Sheets, LibreOffice, Word or a web page. Pasted into text, they become a table
  where they were pasted (the text splits around it); a first row of names names the columns, and columns of
  numbers are number columns, so formulas work on them. Pasted into a table's cell, the cells fill the table from
  there, right and down, adding rows and columns as needed; in a tick-off column, TRUE, yes or x ticks. A table
  holds up to 500 rows and 40 columns, and a paste says when it left some out.
- A table's column names are changed where they are: click a name in the header and type. Their kind, unit and
  formula are still set under ⚙ Columns.
- More in the text's formatting bar: strike-through; colours for letters (red, orange, green, blue, purple, grey);
  a marker to highlight text (yellow, green, blue, pink), switched on and off like a pen: on, what is typed is
  highlighted; off, typing is plain, even next to or inside highlighted text; with text selected it highlights it,
  or takes the highlight off when it is all highlighted already. Its ⌀ No highlight takes the highlight off the
  selection, or off the whole highlighted stretch the cursor is in. Colours can be taken off again. A colour or
  highlight chosen for selected text applies to all of it, whatever its parts had (other colours, other
  highlights, none). And three
  headings instead of one, told apart by more than size: Heading 1 a serif title, Heading 2 bold and underlined,
  Heading 3 small grey capitals. All of it comes along in PDF and Word exports.

### Changed
- Dates are written day-first, as in Europe: 30-10-2026, and 30-10-2026 16:40 on the 24-hour clock, on pages, in
  their history, ticks and attachments, and in PDF and Word exports. Day pages are named 30-10-2026 Thursday and
  months October 2026; those already made under the old names (2026-10-30 Thursday, 2026-10 October) are renamed
  when the notebook starts, unless someone renamed them. The tree still lists them newest first, by their date.
  Stored dates stay as they were (2026-10-30).

### Fixed
- A long step, and a long title of the steps, wrap onto more lines, their box growing to show all of it; they
  used to run on out of sight in a one-line box. Each stays one paragraph: Enter does not break it, and pasted
  lines join up.

## [0.17.0] - 2026-10-26

### Added
- Word, PowerPoint and Excel files on a note open in the browser, without downloading: old and new
  formats (.doc, .docx, .ppt, .pptx, .xls, .xlsx), OpenDocument, RTF and CSV are turned into a PDF by the suite's
  converter (`CONVERTER_URL`) the first time they are opened, and the PDF is kept for the next time. Text files
  (notes, FASTA, GenBank) open as plain text. The original still downloads. Without a converter, office files
  download as before.

## [0.16.1] - 2026-10-26

### Added
- Tab in text works as in a word processor: it puts in a tab (Shift+Tab takes it back), and in a
  list it moves the item in a level (Shift+Tab moves it out). Tabs are kept in the PDF and Word
  exports.

## [0.16.0] - 2026-10-23

### Changed
- **Trellis Tools' look**: the header every module shares (Trellis Tools, then this module's icon and name,
  its tabs, the person and Log out), and the suite's palette - green for what you do, brown for structure,
  on warm paper-white - from static/trellis/trellis.css, copied in from the suite (design/sync.sh). Links to plasmids,
  stocks and seeds take the colour of the module they open; the Bookings box Booking's plum.
- Trellis Tools' small icons instead of emoji: page types, what other tools put into a day, links to plasmids,
  stocks and seeds, attachments, sharing and the tools of a page. Exports say "Attachment:" where they had 📎;
  what people wrote in their pages is left as it is.

## [0.15.1] - 2026-10-23

### Changed
- The suite it runs in is called Trellis Tools, as its About page and exports now say.

## [0.15.0] - 2026-10-23

### Changed
- Someone who has left (archived in the suite) keeps their notebook for their lab's leads, marked
  "(left)"; they are no longer offered to share with, and their bookings ahead are not shown.

## [0.14.0] - 2026-10-23

### Added
- **Bookings on the day.** A day's page shows the bookings in the Booking tool of whoever the notebook
  belongs to - those they made and those they are tagged in - with the time, the room or equipment,
  what for and who else. Live while the day is today or ahead (a booking moved or cancelled there moves
  or goes here); kept as they stood once the day is over. Under each, what was done with the time,
  written on the day. Today's page also lists the bookings coming up. Printed at the top of the day in
  PDF and Word exports. Needs the Booking tool's database (BOOKING_DATABASE_PATH, read-only).
- **A booking gives its day a page.** On opening the notebook, every day someone has a booking on (made
  or tagged in, from a month back to three months ahead) gets its page, if it had none. A page made this
  way stays if the booking is cancelled.

## [0.13.0] - 2026-10-23

### Added
- **Figures from the other tools go into a day.** Besides a virtual digest: from the Plasmid Editor,
  a plasmid map, a cloning product, a PCR, a designed primer pair and a sequencing read; from the
  MoClo Library Tool, a part, a plasmid and a cassette. Each comes with its pictures (several at a time) and
  what they show, and says on its heading, and in exports, where it came from.

## [0.12.0] - 2026-10-23

### Added
- **Virtual digests from the Plasmid Editor.** A digest's virtual gel and fragments, sent from the
  editor (📓 Add to notebook), go at the end of a day's page - started if needed - as a section: the
  gel as a gel photo with its wells numbered and named, and a table of the fragments with a column to
  tick off the bands seen on the real gel. Kept in the day's history as an import.

## [0.11.0] - 2026-10-23

### Added
- **Pages shared to work on together.** A lab member can share a page (or a day) - and everything
  under it - with people or labs of their chair group (👥 Share, on the page). Those it is shared with
  find it under "Shared with me", change it and the pages under it, and add pages under them; what
  they add stays in the owner's notebook, and the history keeps who changed what. They can also show
  it under a page of their own (⋯ › Show also under another page), as in Trilium: one page in both
  notebooks, so a change shows in both. Only the owner shares it on or deletes the shared page itself;
  a share reaches only the owner's own pages under it, never someone else's page shown there. The
  page says whom it is shared with, or who shared it. Without chair groups, a page is shared within
  the owner's lab(s).
- An open page is looked at again every 20 seconds and shown afresh when someone else saved it - not
  while it is being changed here.

### Changed
- A page or protocol shown in more than one place lists the places this person may see, and how many
  others there are; deleting a page no longer takes someone else's page shown under it along.

## [0.10.2] - 2026-10-20

### Added
- Links to Lab Stocks' plant material (GL-M-0001), found with the other stocks.

## [0.10.1] - 2026-10-19

### Added
- Links to Lab Stocks' chemicals (`GL-C-0003`), from `@` and the 🧫 Stock… button, as to its
  glycerol stocks and primers; they open the chemical's page, with its safety data sheet.
- Links to Lab Stocks' antibodies (`GL-A-0005`) in the same way.

## [0.10.0] - 2026-10-19

### Changed
- People can be in several labs: they see the protocols of all their labs and what is shared with
  any of them, and lead the labs they lead (reading their members' notebooks, changing their
  protocols). A new protocol belongs to its author's first lab.
- Plasmids to link follow the Plasmid Editor: always the owner's labs', every lab's once public.

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
