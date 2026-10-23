"""
Notes, where they sit, their attributes and their history, and who may do what.

    Everyone      has a notebook of their own: days, and pages under them.
                  May add protocols to the library and use their lab's, the ones
                  other labs share with it, and those supplied with the notebook.
    A lab lead    may open the notebooks of their lab's members, and share them
                  with other labs or people, to read and export.
    An admin      may open every notebook and protocol.
    A protocol    belongs to its author's lab. It may be changed by whoever wrote
                  it, their lab's lead, or an admin, and shared by them with
                  other labs.
    A page        (or a day) may be shared by its owner with people and labs
                  of their chair group, to work on together: those it is shared
                  with read it and the pages under it, change them, add pages
                  under them, and may show it under a page of their own too (one
                  note in two notebooks, a change showing in both). What they
                  add stays in the owner's notebook. A share reaches only the
                  owner's own notes under the page, never someone else's note
                  shown there.

A share lasts until it is retracted. A notebook is changed only by its owner,
and those its pages are shared with; leads, admins and those a whole notebook
is shared with read it. Every
change to a note is kept as a revision (one person's edits within a few
minutes of each other make one revision, as in Trilium), and any revision can
be restored, which is a revision too.
"""

import calendar
import json
from datetime import date
from typing import Any, Dict, List, Optional, Set

from flask import g, has_app_context

from app import attachments
from app import bookings as bookings_mod
from app import content as content_mod
from app import people as people_mod
from app.db import connect
from app.people import Person

LIBRARY_TITLE = 'Protocol library'
# The notes of a notebook that can be shared to work on together.
SHARED_PAGE_TYPES = ('page', 'day')
# One person's edits closer together than this make one revision.
REVISION_WINDOW_MINUTES = 10
NOTE_TYPES = ('page', 'protocol', 'folder')


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


class Stale(Exception):
    def __init__(self, note: dict):
        super().__init__('This note was changed since you opened it')
        self.note = note


# --- reading -----------------------------------------------------------------

def _row(conn, note_id: str):
    row = conn.execute('SELECT * FROM notes WHERE id = ? AND deleted_at IS NULL', (note_id,)).fetchone()
    if row is None:
        raise NotFound('Note not found')
    return row


def note_lab(note) -> Optional[str]:
    """The lab a library note belongs to: as recorded, else its author's now; None for every lab's."""
    if note['lab']:
        return note['lab']
    if note['created_by']:
        return (people_mod.membership(note['created_by']) or {}).get('lab_id')
    return None


def _shared_with(person: Person) -> Dict[str, Set[str]]:
    """What is shared with this person or their lab: {'notes': note ids, 'owners': notebook owners}."""
    key = f'shared_{person.username}'
    if has_app_context() and key in g:
        return g.get(key)
    labs = sorted(person.lab_ids) or ['']
    with connect() as conn:
        rows = conn.execute(
            'SELECT s.note_id, n.type, n.owner FROM shares s JOIN notes n ON n.id = s.note_id '
            "WHERE n.deleted_at IS NULL AND ((s.target_type = 'person' AND s.target = ?) "
            f"OR (s.target_type = 'lab' AND s.target IN ({','.join('?' * len(labs))})))",
            (person.username, *labs)).fetchall()
    found = {'notes': {r['note_id'] for r in rows},
             'owners': {r['owner'] for r in rows if r['type'] == 'notebook' and r['owner']},
             # Pages shared to work on together, with their owners.
             'pages': {(r['note_id'], r['owner']) for r in rows if r['type'] in SHARED_PAGE_TYPES and r['owner']}}
    if has_app_context():
        setattr(g, key, found)
    return found


def _owned_subtree(conn, note_id: str, owner: Optional[str]) -> Set[str]:
    """A note and what is under it, as far as the notes are this owner's (not deleted)."""
    found, todo = set(), [note_id]
    while todo:
        current = todo.pop()
        if current in found:
            continue
        found.add(current)
        todo.extend(r['id'] for r in conn.execute(
            'SELECT n.id FROM branches b JOIN notes n ON n.id = b.note_id '
            'WHERE b.parent_id = ? AND n.deleted_at IS NULL AND n.owner IS ?', (current, owner)))
    return found


def _shared_pages(person: Person) -> Set[str]:
    """Every note this person may work on because a page was shared with them: those pages, and their owners' notes under them."""
    key = f'shared_pages_{person.username}'
    if has_app_context() and key in g:
        return g.get(key)
    roots = _shared_with(person)['pages']
    found: Set[str] = set()
    if roots:
        with connect() as conn:
            for root, owner in roots:
                found |= _owned_subtree(conn, root, owner)
    if has_app_context():
        setattr(g, key, found)
    return found


def _share_roots(conn, note) -> List[dict]:
    """The shared pages this note is in (itself, or one above it in its owner's notebook)."""
    if note['space'] != 'notebook' or note['type'] == 'notebook':
        return []
    roots = conn.execute(
        'SELECT DISTINCT n.id, n.title FROM shares s JOIN notes n ON n.id = s.note_id '
        f"WHERE n.owner = ? AND n.deleted_at IS NULL AND n.type IN ({','.join('?' * len(SHARED_PAGE_TYPES))})",
        (note['owner'], *SHARED_PAGE_TYPES)).fetchall()
    return [{'id': r['id'], 'title': r['title']} for r in roots
            if note['id'] in _owned_subtree(conn, r['id'], note['owner'])]


def _forget_shares() -> None:
    if has_app_context():
        for key in [k for k in vars(g) if k.startswith('shared_')]:
            delattr(g, key)


def can_view(person: Person, note) -> bool:
    if note['space'] == 'library':
        if note['type'] == 'library' or person.is_admin:
            return True
        lab = note_lab(note)
        if lab is None or lab in person.lab_ids:
            return True
        shared = _shared_with(person)['notes']
        if note['type'] == 'folder':
            # Another lab's folder shows when it holds something shared with this lab.
            with connect() as conn:
                return bool(shared.intersection(_subtree(conn, note['id'])))
        return note['id'] in shared
    return (person.oversees(note['owner']) or note['owner'] in _shared_with(person)['owners']
            or note['id'] in _shared_pages(person))


def can_edit(person: Person, note) -> bool:
    """Change this note's title, content and attributes."""
    if note['space'] == 'library':
        if note['type'] == 'library':
            return False
        author = note['created_by']
        if person.is_admin or (author and author == person.username):
            return True
        lab = note_lab(note)
        # The lead of the lab it belongs to.
        return bool(author and lab and lab in person.led_lab_ids)
    if note['type'] == 'notebook':
        return False
    return note['owner'] == person.username or note['id'] in _shared_pages(person)


def can_add_under(person: Person, parent) -> bool:
    """Put a new note (or a note moved here) under this one."""
    if parent['space'] == 'library':
        if parent['type'] == 'library':
            return True
        if parent['type'] == 'folder':
            # Into the lab's own folders (or every lab's), not into one another lab shares from.
            return person.is_admin or note_lab(parent) is None or note_lab(parent) in person.lab_ids
        return can_edit(person, parent)
    return parent['owner'] == person.username or parent['id'] in _shared_pages(person)


def _visible(person: Person, note_id: str):
    with connect() as conn:
        row = _row(conn, note_id)
    if not can_view(person, row):
        raise Forbidden('This notebook is not yours to open')
    return row


def _attributes(conn, note_id: str) -> List[dict]:
    # A relation points at a note by id; its title comes along to show it by.
    return [dict(r) for r in conn.execute(
        'SELECT a.id, a.type, a.name, a.value, t.title AS target_title FROM attributes a '
        "LEFT JOIN notes t ON a.type = 'relation' AND t.id = a.value AND t.deleted_at IS NULL "
        'WHERE a.note_id = ? ORDER BY a.position, a.rowid', (note_id,))]


def _path(conn, note_id: str) -> List[dict]:
    """From the root down to this note, following each note's first placement."""
    trail, seen = [], set()
    current = note_id
    while current and current not in seen:
        seen.add(current)
        row = conn.execute('SELECT id, title, type FROM notes WHERE id = ?', (current,)).fetchone()
        if row is None:
            break
        trail.append({'id': row['id'], 'title': row['title'], 'type': row['type']})
        parent = conn.execute('SELECT parent_id FROM branches WHERE note_id = ? ORDER BY rowid LIMIT 1',
                              (current,)).fetchone()
        current = parent['parent_id'] if parent else None
    return list(reversed(trail))


def summary(row) -> dict:
    return {'id': row['id'], 'title': row['title'], 'type': row['type'], 'space': row['space'],
            'owner': row['owner']}


def get(person: Person, note_id: str) -> dict:
    row = _visible(person, note_id)
    with connect() as conn:
        # Where it is, as far as this person may see: a page shared and shown
        # under someone else's page does not show their page to its owner.
        found = conn.execute(
            'SELECT b.id AS branch_id, b.parent_id, p.title AS parent_title, p.* FROM branches b '
            'JOIN notes p ON p.id = b.parent_id WHERE b.note_id = ? AND p.deleted_at IS NULL ORDER BY b.rowid',
            (note_id,)).fetchall()
        placements = [{'branch_id': r['branch_id'], 'parent_id': r['parent_id'], 'parent_title': r['parent_title'],
                       'parent_owner': r['owner']} for r in found if can_view(person, r)]
        share_roots = _share_roots(conn, row)
        shared_root = any(r['id'] == note_id for r in share_roots)
        backlinks = [r for r in conn.execute(
            "SELECT n.* FROM links l JOIN notes n ON n.id = l.note_id "
            "WHERE l.target_type = 'note' AND l.target_id = ? AND n.deleted_at IS NULL "
            "ORDER BY n.updated_at DESC LIMIT 100", (note_id,))]
        note = {
            **summary(row),
            'content': json.loads(row['content'] or '[]'),
            'version': row['version'], 'revision': row['revision'],
            'created_by': row['created_by'], 'created_at': row['created_at'],
            'updated_by': row['updated_by'], 'updated_at': row['updated_at'],
            'attributes': _attributes(conn, note_id),
            'path': _path(conn, note_id),
            'placements': placements,
            'other_places': len(found) - len(placements),
            # The shared pages it is in, to work on together, and who with.
            'shared_in': [{**r, 'with': _share_labels(conn, r['id'])} for r in share_roots],
            'can_edit': can_edit(person, row),
            'can_delete': can_edit(person, row) and row['type'] not in ('notebook', 'library')
                          and not (shared_root and row['owner'] != person.username and not person.is_admin),
            'can_add': can_add_under(person, row),
            'can_share': can_share(person, row),
            'has_children': bool(conn.execute(
                'SELECT 1 FROM branches b JOIN notes c ON c.id = b.note_id '
                'WHERE b.parent_id = ? AND c.deleted_at IS NULL LIMIT 1', (note_id,)).fetchone()),
            'favorite': bool(conn.execute('SELECT 1 FROM favorites WHERE username = ? AND note_id = ?',
                                          (person.username, note_id)).fetchone()),
            'attachments': attachments.listed(conn, note_id),
        }
        # A day: its bookings in the Booking tool, of whoever the notebook belongs to.
        iso = day_of(note)
        if iso and row['owner']:
            note['bookings'] = bookings_mod.on_day(conn, note_id, row['owner'], date.fromisoformat(iso))
    note['backlinks'] = [summary(b) for b in backlinks if can_view(person, b)]
    return note


def day_of(note) -> Optional[str]:
    """A day's date (YYYY-MM-DD), from its dateNote label; None for any other note."""
    if note['type'] != 'day':
        return None
    return next((a['value'] for a in note['attributes'] if a['name'] == 'dateNote' and a['value']), None)


def pages_for_bookings(person: Person) -> List[str]:
    """
    A page for every day they have a booking on (app/bookings.py), so a booking
    made or tagged in shows up in their notebook as that day's entry. Pages are
    only ever added here: a day stays if its booking is cancelled, as anything
    written on it is theirs.
    """
    return [day(person, d) for d in bookings_mod.booked_days(person.username)]


def write_booking_note(person: Person, note_id: str, booking_id: str, text: str) -> None:
    """What someone writes about one of a day's bookings: what they did with the time."""
    note = get(person, note_id)
    if not note['can_edit']:
        raise Forbidden('Only whoever can change this day writes on it')
    if booking_id not in {b['id'] for b in (note.get('bookings') or {}).get('items', [])}:
        raise NotFound('That booking is not on this day')
    with connect() as conn:
        bookings_mod.write_note(conn, note_id, booking_id, text, person.username)


def children(person: Person, parent_id: str) -> List[dict]:
    _visible(person, parent_id)
    with connect() as conn:
        rows = conn.execute(
            'SELECT n.*, b.id AS branch_id, b.position, '
            '  (SELECT COUNT(*) FROM branches c JOIN notes cn ON cn.id = c.note_id '
            '   WHERE c.parent_id = n.id AND cn.deleted_at IS NULL) AS child_count, '
            '  (SELECT COUNT(*) FROM branches o WHERE o.note_id = n.id) AS placements '
            'FROM branches b JOIN notes n ON n.id = b.note_id '
            'WHERE b.parent_id = ? AND n.deleted_at IS NULL '
            # Days, months and years newest first, as in a journal; the rest in their order.
            "ORDER BY CASE WHEN n.type IN ('year', 'month', 'day') THEN 0 ELSE 1 END, "
            "CASE WHEN n.type IN ('year', 'month', 'day') THEN n.title END DESC, b.position, n.title",
            (parent_id,)).fetchall()
        shared = {r['note_id'] for r in conn.execute(
            'SELECT DISTINCT s.note_id FROM shares s JOIN branches b ON b.note_id = s.note_id WHERE b.parent_id = ?',
            (parent_id,))}
    # Someone else's page shown here is listed only to those who may open it.
    return [{**summary(r), 'branch_id': r['branch_id'], 'has_children': r['child_count'] > 0,
             'cloned': r['placements'] > 1,
             'shared': r['space'] == 'notebook' and r['type'] in SHARED_PAGE_TYPES and r['id'] in shared}
            for r in rows if can_view(person, r)]


# --- roots ---------------------------------------------------------------------

def _create(conn, *, title: str, type: str, space: str, owner: Optional[str], by: Optional[str],
            parent_id: Optional[str] = None, content: Optional[list] = None,
            kind: str = 'created', lab: Optional[str] = None) -> str:
    note_id = content_mod.new_id() + content_mod.new_id()
    body = json.dumps(content or [])
    conn.execute('INSERT INTO notes (id, title, type, space, owner, content, search_text, revision, version, '
                 'created_by, updated_by, lab) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)',
                 (note_id, title, type, space, owner, body, content_mod.plain_text(content or []), by, by,
                  lab if space == 'library' else None))
    conn.execute('INSERT INTO revisions (note_id, number, title, content, kind, changed_by) '
                 'VALUES (?, 1, ?, ?, ?, ?)', (note_id, title, body, kind, by))
    if parent_id:
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                (parent_id,)).fetchone()[0]
        conn.execute('INSERT INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                     (content_mod.new_id(), note_id, parent_id, position))
    _index_links(conn, note_id, content or [])
    return note_id


def _label(conn, note_id: str, name: str, value: str = '') -> None:
    conn.execute('INSERT INTO attributes (id, note_id, type, name, value) VALUES (?, ?, ?, ?, ?)',
                 (content_mod.new_id(), note_id, 'label', name, value))


def notebook_root(username: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT id FROM notes WHERE type = 'notebook' AND owner = ? AND deleted_at IS NULL",
                           (username,)).fetchone()
        if row:
            return row['id']
        note_id = _create(conn, title=f"{username}'s notebook", type='notebook', space='notebook',
                          owner=username, by=username)
        _label(conn, note_id, 'notebookRoot')
        return note_id


def library_root() -> str:
    with connect() as conn:
        row = conn.execute("SELECT id FROM notes WHERE type = 'library' AND deleted_at IS NULL").fetchone()
        if row:
            return row['id']
        note_id = _create(conn, title=LIBRARY_TITLE, type='library', space='library', owner=None, by=None)
        _label(conn, note_id, 'protocolLibrary')
        return note_id


def notebooks(person: Person) -> List[dict]:
    """
    The notebooks this person may open besides their own: their lab's (or all,
    for an admin), and those shared with them or their lab, marked shared.
    """
    with connect() as conn:
        rows = conn.execute("SELECT * FROM notes WHERE type = 'notebook' AND deleted_at IS NULL "
                            'AND owner != ? ORDER BY owner', (person.username,)).fetchall()
    shared = _shared_with(person)['owners']
    gone = people_mod.archived()
    found = []
    for r in rows:
        mine = (person.is_admin or person.is_lab_lead) and person.oversees(r['owner'])
        if mine or r['owner'] in shared:
            # Someone who left (archived) keeps their notebook, for their lab's leads.
            found.append({**summary(r), 'shared': not mine, 'can_share': can_share(person, r),
                          'archived': r['owner'] in gone})
    return found


def assign_labs() -> None:
    """Give library notes written before labs were recorded their author's lab, once known."""
    with connect() as conn:
        rows = conn.execute("SELECT id, created_by FROM notes WHERE space = 'library' AND lab IS NULL "
                            'AND created_by IS NOT NULL').fetchall()
    if not rows:
        return
    labs = {u: m.get('lab_id') for u, m in people_mod.memberships().items()}
    with connect() as conn:
        conn.executemany('UPDATE notes SET lab = ? WHERE id = ?',
                         [(labs[r['created_by']], r['id']) for r in rows if labs.get(r['created_by'])])


# --- days ----------------------------------------------------------------------

def _child_with_label(conn, parent_id: str, name: str, value: str) -> Optional[str]:
    row = conn.execute(
        'SELECT n.id FROM branches b JOIN notes n ON n.id = b.note_id '
        'JOIN attributes a ON a.note_id = n.id '
        'WHERE b.parent_id = ? AND n.deleted_at IS NULL AND a.name = ? AND a.value = ? LIMIT 1',
        (parent_id, name, value)).fetchone()
    return row['id'] if row else None


def day(person: Person, when: Optional[date] = None) -> str:
    """The person's page for a day, under Year › Month, made if it is not there yet."""
    when = when or date.today()
    root = notebook_root(person.username)
    year, month, iso = str(when.year), when.strftime('%Y-%m'), when.isoformat()
    with connect() as conn:
        year_id = _child_with_label(conn, root, 'yearNote', year)
        if not year_id:
            year_id = _create(conn, title=year, type='year', space='notebook', owner=person.username,
                              by=person.username, parent_id=root)
            _label(conn, year_id, 'yearNote', year)
        month_id = _child_with_label(conn, year_id, 'monthNote', month)
        if not month_id:
            month_id = _create(conn, title=f'{month} {calendar.month_name[when.month]}', type='month',
                               space='notebook', owner=person.username, by=person.username, parent_id=year_id)
            _label(conn, month_id, 'monthNote', month)
        day_id = _child_with_label(conn, month_id, 'dateNote', iso)
        if not day_id:
            day_id = _create(conn, title=f'{iso} {calendar.day_name[when.weekday()]}', type='day',
                             space='notebook', owner=person.username, by=person.username, parent_id=month_id,
                             content=[{'id': content_mod.new_id(), 'type': 'text', 'html': ''}])
            _label(conn, day_id, 'dateNote', iso)
        return day_id


# Sections other tools put into a day, by kind: where each comes from.
IMPORTED_KINDS = {
    'virtual-digest': 'the Plasmid Editor',
    'plasmid-map': 'the Plasmid Editor',
    'cloning-product': 'the Plasmid Editor',
    'pcr': 'the Plasmid Editor',
    'primers': 'the Plasmid Editor',
    'sequencing-read': 'the Plasmid Editor',
    'moclo-plasmid': 'the MoClo Library Tool',
    'moclo-cassette': 'the MoClo Library Tool',
    'moclo-part': 'the MoClo Library Tool',
}
MAX_PICTURES = 8


def picture_key(n: int) -> str:
    """How a section names its n-th picture (from 0) before it is attached: 'picture', 'picture-2', ..."""
    return 'picture' if n == 0 else f'picture-{n + 1}'


def _name_pictures(blocks: list, ids: Dict[str, str]) -> None:
    """Point the section's pictures at their attachments: a gel's photo, and images in its text."""
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'gel' and block.get('attachment') in ids:
            block['attachment'] = ids[block['attachment']]
        elif block.get('type') == 'text' and isinstance(block.get('html'), str):
            for key, att in ids.items():
                block['html'] = block['html'].replace(f'data-attachment="{key}"', f'data-attachment="{att}"')
        elif block.get('type') == 'section':
            _name_pictures(block.get('blocks') or [], ids)


def import_to_day(person: Person, section: dict, pictures: Optional[List[tuple]] = None,
                  when: Optional[date] = None) -> str:
    """
    Put a section another tool made - a figure and what it shows: a virtual
    digest, a plasmid map, a MoClo cassette... (IMPORTED_KINDS) - at the end of
    this person's page for a day, starting the day if needed. Pictures, given
    as (filename, bytes), are attached to the day; the section names them
    'picture', 'picture-2', ... (picture_key), in a gel block's attachment or
    an image in its text (data-attachment). Kept in the day's history as an
    import.
    """
    if not isinstance(section, dict) or section.get('type') != 'section':
        raise ValueError('Send a section to put into the day')
    kind = (section.get('source') or {}).get('kind') if isinstance(section.get('source'), dict) else None
    if kind not in IMPORTED_KINDS:
        raise ValueError('That kind of section cannot be put into a day this way')
    pictures = list(pictures or [])
    if len(pictures) > MAX_PICTURES:
        raise ValueError(f'At most {MAX_PICTURES} pictures at a time')
    day_id = day(person, when)
    if pictures:
        added = attachments.add(person, day_id, pictures)
        _name_pictures(section.get('blocks') or [], {picture_key(i): a['id'] for i, a in enumerate(added)})
    with connect() as conn:
        row = _row(conn, day_id)
        previous = json.loads(row['content'] or '[]')
        # A day just started holds an empty paragraph: the import takes its place.
        untouched = all(b.get('type') == 'text' for b in previous) and not content_mod.plain_text(previous)
        kept = [] if untouched else previous
        blocks = content_mod.clean_blocks(kept + [section], previous, person.username)
        body = json.dumps(blocks)
        number = _keep_revision(conn, day_id, row['title'], body, person.username, 'imported',
                               f"{_text_of(section.get('title'))} from {IMPORTED_KINDS[kind]}")
        conn.execute('UPDATE notes SET content = ?, search_text = ?, revision = ?, version = version + 1, '
                     'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (body, content_mod.plain_text(blocks), number, person.username, day_id))
        _index_links(conn, day_id, blocks)
    return day_id


def _text_of(value) -> str:
    return str(value or '').strip()[:200] or 'A section'


# --- changing notes ------------------------------------------------------------

def create(person: Person, parent_id: str, title: str, type: str = 'page',
           content: Optional[list] = None) -> str:
    if type not in NOTE_TYPES:
        raise ValueError(f'type must be one of {", ".join(NOTE_TYPES)}')
    parent = _visible(person, parent_id)
    if not can_add_under(person, parent):
        raise Forbidden('You cannot add notes here')
    if parent['space'] == 'notebook' and type == 'protocol':
        type = 'page'
    blocks = content_mod.clean_blocks(content or [{'type': 'text', 'html': ''}], username=person.username)
    with connect() as conn:
        note_id = _create(conn, title=(title or 'Untitled').strip()[:200] or 'Untitled', type=type,
                          space=parent['space'], owner=parent['owner'], by=person.username,
                          parent_id=parent_id, content=blocks, lab=person.lab_id)
    _forget_shares()          # a page added under a shared one is shared too
    return note_id


def _index_links(conn, note_id: str, blocks: list) -> None:
    conn.execute('DELETE FROM links WHERE note_id = ?', (note_id,))
    conn.executemany('INSERT OR IGNORE INTO links (note_id, target_type, target_id) VALUES (?, ?, ?)',
                     [(note_id, t, i) for t, i in content_mod.links(blocks)])


def _keep_revision(conn, note_id: str, title: str, body: str, by: str, kind: str,
                   remark: Optional[str] = None) -> int:
    """Keep a note's new state in its history, folding quick successive edits by one person."""
    last = conn.execute('SELECT number, kind, changed_by, '
                        "(julianday('now') - julianday(updated_at)) * 1440 AS minutes "
                        'FROM revisions WHERE note_id = ? ORDER BY number DESC LIMIT 1', (note_id,)).fetchone()
    if (kind == 'edited' and last and last['kind'] == 'edited' and last['changed_by'] == by
            and last['minutes'] < REVISION_WINDOW_MINUTES):
        conn.execute('UPDATE revisions SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP '
                     'WHERE note_id = ? AND number = ?', (title, body, note_id, last['number']))
        return last['number']
    number = (last['number'] if last else 0) + 1
    conn.execute('INSERT INTO revisions (note_id, number, title, content, kind, note, changed_by) '
                 'VALUES (?, ?, ?, ?, ?, ?, ?)', (note_id, number, title, body, kind, remark, by))
    return number


def save(person: Person, note_id: str, title: Optional[str] = None, content: Optional[list] = None,
         base_version: Optional[int] = None) -> dict:
    with connect() as conn:
        row = _row(conn, note_id)
    if not can_view(person, row):
        raise Forbidden('This notebook is not yours to open')
    if not can_edit(person, row):
        raise Forbidden('You can read this note but not change it')
    if base_version is not None and int(base_version) != row['version']:
        raise Stale(get(person, note_id))
    new_title = (title.strip()[:200] or 'Untitled') if isinstance(title, str) else row['title']
    if row['type'] in ('year', 'month', 'day'):
        new_title = row['title']          # a day is named by its date
    previous = json.loads(row['content'] or '[]')
    blocks = previous if content is None else content_mod.clean_blocks(content, previous, person.username)
    body = json.dumps(blocks)
    if new_title == row['title'] and body == row['content']:
        return get(person, note_id)
    with connect() as conn:
        number = _keep_revision(conn, note_id, new_title, body, person.username, 'edited')
        conn.execute('UPDATE notes SET title = ?, content = ?, search_text = ?, revision = ?, '
                     'version = version + 1, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (new_title, body, content_mod.plain_text(blocks), number, person.username, note_id))
        _index_links(conn, note_id, blocks)
    return get(person, note_id)


def _subtree(conn, note_id: str) -> List[str]:
    found, todo = [], [note_id]
    while todo:
        current = todo.pop()
        if current in found:
            continue
        found.append(current)
        todo.extend(r['note_id'] for r in conn.execute('SELECT note_id FROM branches WHERE parent_id = ?',
                                                       (current,)))
    return found


def copy(person: Person, note_id: str) -> str:
    """
    A new note with the same title and content, to start from: a protocol's copy
    goes into the library (beside the original when possible) as the copier's
    own, anything else into the copier's notebook. Ticks are not copied.
    """
    row = _visible(person, note_id)
    if row['type'] in ('notebook', 'library', 'year', 'month'):
        raise ValueError('This cannot be copied')
    with connect() as conn:
        parents = [r['parent_id'] for r in conn.execute('SELECT parent_id FROM branches WHERE note_id = ?',
                                                        (note_id,))]
        parent = next((p for p in parents if can_add_under(person, _row(conn, p))), None)
    if parent is None:
        parent = library_root() if row['space'] == 'library' else notebook_root(person.username)
    blocks = json.loads(row['content'] or '[]')

    def untick(items):
        for b in items:
            if b.get('type') == 'section':
                untick(b.get('blocks') or [])
            elif b.get('type') == 'steps':
                for i in b.get('items') or []:
                    i.update(by=None, at=None, done=False)
            elif b.get('type') == 'table':
                for r in b.get('rows') or []:
                    r['cells'] = [None if isinstance(c, dict) else c for c in r.get('cells') or []]
            b.pop('id', None)
    untick(blocks)
    note_type = row['type'] if row['type'] in NOTE_TYPES else 'page'
    new_id = create(person, parent, f"{row['title']} (copy)", note_type, blocks)
    # Its own copies of the attachments, so the copy does not depend on the original.
    with connect() as conn:
        mapping = attachments.copy_all(conn, note_id, new_id, person.username)
        if mapping:
            body = conn.execute('SELECT content FROM notes WHERE id = ?', (new_id,)).fetchone()['content']
            for old, new in mapping.items():
                body = body.replace(old, new)       # ids are random, 24 characters: no false matches
            conn.execute('UPDATE notes SET content = ? WHERE id = ?', (body, new_id))
            conn.execute('UPDATE revisions SET content = ? WHERE note_id = ? AND number = 1', (body, new_id))
    return new_id


def delete(person: Person, note_id: str) -> None:
    """
    Move a note, and everything under it, to the deleted notes (kept, not
    erased). Only its owner's own notes under it go with it: someone else's
    page shown under it stays, in its own place. A page shared to work on
    together is deleted by its owner; those it is shared with may delete the
    pages under it.
    """
    with connect() as conn:
        row = _row(conn, note_id)
        if row['type'] in ('notebook', 'library') or not can_edit(person, row):
            raise Forbidden('You cannot delete this note')
        if row['owner'] != person.username and not person.is_admin and row['space'] == 'notebook' and any(
                r == note_id for r, _ in _shared_with(person)['pages']):
            raise Forbidden('Only its owner can delete a page shared with you; you can delete the pages under it')
        for nid in _owned_subtree(conn, note_id, row['owner']):
            # Notes already deleted on their own stay their own deletion.
            conn.execute('UPDATE notes SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ?, deleted_root = ? '
                         'WHERE id = ? AND deleted_at IS NULL', (person.username, note_id, nid))
    _forget_shares()


# --- deleted notes ---------------------------------------------------------------

def _can_restore(person: Person, row) -> bool:
    """Whoever could have deleted it, and administrators, for anything."""
    if person.is_admin:
        return True
    return can_edit(person, row)


def deleted(person: Person) -> List[dict]:
    """Deletions this person may undo, newest first: each with what went with it."""
    with connect() as conn:
        rows = conn.execute(
            'SELECT n.*, (SELECT COUNT(*) FROM notes g WHERE g.deleted_root = n.id) AS with_it '
            'FROM notes n WHERE n.deleted_at IS NOT NULL AND (n.deleted_root = n.id OR n.deleted_root IS NULL) '
            'ORDER BY n.deleted_at DESC LIMIT 500').fetchall()
        found = []
        for r in rows:
            if not _can_restore(person, r):
                continue
            parent = conn.execute('SELECT p.id, p.title, p.type, p.deleted_at FROM branches b JOIN notes p ON p.id = b.parent_id '
                                  'WHERE b.note_id = ? ORDER BY b.rowid LIMIT 1', (r['id'],)).fetchone()
            found.append({**summary(r), 'deleted_at': r['deleted_at'], 'deleted_by': r['deleted_by'] or r['updated_by'],
                          'pages': max(1, r['with_it']),
                          # Where it was, unless at the top of its notebook or the library.
                          'was_under': parent['title'] if parent and parent['type'] not in ('notebook', 'library') else None,
                          'parent_deleted': bool(parent and parent['deleted_at'])})
    return found


def _deleted_row(conn, note_id: str):
    row = conn.execute('SELECT * FROM notes WHERE id = ? AND deleted_at IS NOT NULL', (note_id,)).fetchone()
    if row is None:
        raise NotFound('No such deleted note')
    return row


def deleted_note(person: Person, note_id: str) -> dict:
    """A deleted note's content, to look at before bringing it back."""
    with connect() as conn:
        row = _deleted_row(conn, note_id)
    if not _can_restore(person, row):
        raise Forbidden('You cannot see this deleted note')
    return {**summary(row), 'content': json.loads(row['content'] or '[]'), 'deleted_at': row['deleted_at']}


def undelete(person: Person, note_id: str) -> str:
    """
    Bring a deleted note back, with what was deleted together with it, to its
    old place; if that place is gone too, to the top of its notebook or library.
    """
    with connect() as conn:
        row = _deleted_row(conn, note_id)
        if not _can_restore(person, row):
            raise Forbidden('You cannot restore this note')
        group = [r['id'] for r in conn.execute('SELECT id FROM notes WHERE deleted_root = ?', (note_id,))] or [note_id]
        if note_id not in group:
            group.append(note_id)
        conn.executemany('UPDATE notes SET deleted_at = NULL, deleted_by = NULL, deleted_root = NULL '
                         'WHERE id = ?', [(i,) for i in group])
        alive = [b for b in conn.execute('SELECT b.id, p.deleted_at FROM branches b JOIN notes p ON p.id = b.parent_id '
                                         'WHERE b.note_id = ?', (note_id,)) if not b['deleted_at']]
    if not alive:
        root = library_root() if row['space'] == 'library' else notebook_root(row['owner'])
        with connect() as conn:
            conn.execute('DELETE FROM branches WHERE note_id = ?', (note_id,))
            position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                    (root,)).fetchone()[0]
            conn.execute('INSERT INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                         (content_mod.new_id(), note_id, root, position))
    _forget_shares()
    return note_id


def _check_target(conn, person: Person, note, parent_id: str, notebook: Optional[str] = None) -> None:
    """
    Whether the note may go under this parent: in `notebook`'s (the owner
    whose notebook the placement is in: the note's own unless it is shown in
    someone else's), or in the library for a library note.
    """
    parent = _row(conn, parent_id)
    if not can_add_under(person, parent):
        raise Forbidden('You cannot put notes there')
    owner = note['owner'] if notebook is None else notebook
    if parent['space'] != note['space'] or parent['owner'] != owner:
        raise ValueError('A note stays in its own notebook (or in the library)')
    if parent_id in _subtree(conn, note['id']):
        raise ValueError('A note cannot go inside itself')


def move(person: Person, branch_id: str, parent_id: str, position: Optional[int] = None) -> None:
    """
    Move one placement of a note. In its own notebook, whoever may change the
    note moves it; shown in someone else's, they move it about their own.
    """
    with connect() as conn:
        branch = conn.execute('SELECT * FROM branches WHERE id = ?', (branch_id,)).fetchone()
        if branch is None:
            raise NotFound('Not found')
        note = _row(conn, branch['note_id'])
        here = _row(conn, branch['parent_id'])
        elsewhere = note['space'] == 'notebook' and here['owner'] != note['owner']
        allowed = can_add_under(person, here) if elsewhere else can_edit(person, note)
        if note['type'] in ('year', 'month', 'day') or not allowed:
            raise Forbidden('You cannot move this note')
        _check_target(conn, person, note, parent_id, here['owner'] if elsewhere else None)
        if position is None:
            position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                    (parent_id,)).fetchone()[0]
        conn.execute('UPDATE OR IGNORE branches SET parent_id = ?, position = ? WHERE id = ?',
                     (parent_id, int(position), branch_id))
    _forget_shares()


def place_also(person: Person, note_id: str, parent_id: str) -> None:
    """
    Show a note in a second place too: one note, two branches (a Trilium
    clone), so a change shows in both. A page someone may work on (their own,
    or one shared with them) may also go under a page of their own notebook.
    """
    with connect() as conn:
        note = _row(conn, note_id)
        if not can_view(person, note) or note['type'] in ('notebook', 'library', 'year', 'month'):
            raise Forbidden('You cannot place this note elsewhere')
        parent = _row(conn, parent_id)
        into_own = (note['space'] == 'notebook' and parent['space'] == 'notebook'
                    and parent['owner'] == person.username != note['owner'])
        if into_own and not can_edit(person, note):
            raise Forbidden('Only a page shared with you to work on can go into your notebook')
        _check_target(conn, person, note, parent_id, person.username if into_own else None)
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                (parent_id,)).fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                     (content_mod.new_id(), note_id, parent_id, position))
    _forget_shares()


def remove_placement(person: Person, branch_id: str) -> None:
    """Take a note out of one of its places; it must keep at least one."""
    with connect() as conn:
        branch = conn.execute('SELECT * FROM branches WHERE id = ?', (branch_id,)).fetchone()
        if branch is None:
            raise NotFound('Not found')
        note = _row(conn, branch['note_id'])
        parent = _row(conn, branch['parent_id'])
        if not can_add_under(person, parent):
            raise Forbidden('You cannot change this')
        # Those a page is shared with take it out of their own pages, not its owner's.
        if (note['space'] == 'notebook' and parent['owner'] == note['owner']
                and person.username != note['owner'] and not person.is_admin):
            raise Forbidden("Only its owner takes a page out of their own notebook")
        if conn.execute('SELECT COUNT(*) FROM branches WHERE note_id = ?', (note['id'],)).fetchone()[0] < 2:
            raise ValueError('This is its only place: delete the note instead')
        conn.execute('DELETE FROM branches WHERE id = ?', (branch_id,))
    _forget_shares()


# --- attributes ----------------------------------------------------------------

def add_attribute(person: Person, note_id: str, type: str, name: str, value: str = '') -> dict:
    name = (name or '').strip().lstrip('#~')[:60]
    if type not in ('label', 'relation') or not name or not all(c.isalnum() or c in '_-:' for c in name):
        raise ValueError('An attribute needs a name of letters, digits, - _ or :')
    with connect() as conn:
        row = _row(conn, note_id)
        if not can_edit(person, row):
            raise Forbidden('You cannot change this note')
        if type == 'relation':
            target = _row(conn, value)
            if not can_view(person, target):
                raise Forbidden('You cannot link to that note')
        attr_id = content_mod.new_id()
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 1 FROM attributes WHERE note_id = ?',
                                (note_id,)).fetchone()[0]
        conn.execute('INSERT INTO attributes (id, note_id, type, name, value, position) VALUES (?, ?, ?, ?, ?, ?)',
                     (attr_id, note_id, type, name, str(value or '')[:300], position))
    return {'id': attr_id, 'type': type, 'name': name, 'value': str(value or '')[:300]}


def remove_attribute(person: Person, attr_id: str) -> None:
    with connect() as conn:
        attr = conn.execute('SELECT * FROM attributes WHERE id = ?', (attr_id,)).fetchone()
        if attr is None:
            raise NotFound('Not found')
        if not can_edit(person, _row(conn, attr['note_id'])):
            raise Forbidden('You cannot change this note')
        # 'seed' marks a protocol supplied with the notebook: without it, the next
        # start would supply it again.
        if attr['name'] in ('dateNote', 'monthNote', 'yearNote', 'notebookRoot', 'protocolLibrary', 'seed'):
            raise ValueError('This label keeps the notebook in order and cannot be removed')
        conn.execute('DELETE FROM attributes WHERE id = ?', (attr_id,))


# --- history -------------------------------------------------------------------

def revisions(person: Person, note_id: str) -> dict:
    row = _visible(person, note_id)
    with connect() as conn:
        rows = conn.execute('SELECT number, title, kind, note, changed_by, created_at, updated_at, '
                            'length(content) AS size FROM revisions WHERE note_id = ? ORDER BY number DESC',
                            (note_id,)).fetchall()
    return {'revisions': [dict(r) for r in rows], 'current': row['revision'],
            'can_restore': can_edit(person, row)}


def revision(person: Person, note_id: str, number: int) -> dict:
    _visible(person, note_id)
    with connect() as conn:
        r = conn.execute('SELECT * FROM revisions WHERE note_id = ? AND number = ?', (note_id, number)).fetchone()
    if r is None:
        raise NotFound('No such version')
    return {'number': r['number'], 'title': r['title'], 'content': json.loads(r['content']),
            'kind': r['kind'], 'changed_by': r['changed_by'], 'created_at': r['created_at']}


def restore(person: Person, note_id: str, number: int) -> dict:
    with connect() as conn:
        row = _row(conn, note_id)
        if not can_edit(person, row):
            raise Forbidden('You cannot change this note')
        r = conn.execute('SELECT * FROM revisions WHERE note_id = ? AND number = ?', (note_id, number)).fetchone()
        if r is None:
            raise NotFound('No such version')
        if number == row['revision']:
            raise ValueError('This is already the current version')
        new = _keep_revision(conn, note_id, r['title'], r['content'], person.username, 'restored',
                             f'Rolled back to version {number}')
        conn.execute('UPDATE notes SET title = ?, content = ?, search_text = ?, revision = ?, '
                     'version = version + 1, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (r['title'], r['content'], content_mod.plain_text(json.loads(r['content'])), new,
                      person.username, note_id))
        _index_links(conn, note_id, json.loads(r['content']))
    return get(person, note_id)


# --- finding notes -------------------------------------------------------------

def _snippet(text: str, words: List[str], width: int = 70) -> str:
    """A piece of the text around the first word found, to show why a note matched."""
    low = text.lower()
    hits = [low.find(w) for w in words if w and low.find(w) >= 0]
    if not hits:
        return text[:width * 2] + ('…' if len(text) > width * 2 else '')
    at = min(hits)
    start = max(0, at - width)
    return ('…' if start else '') + text[start:at + width] + ('…' if at + width < len(text) else '')


def search(person: Person, query: str, types: Optional[List[str]] = None, limit: int = 30) -> List[dict]:
    """
    Notes this person may open, by the words in their title and content (all of
    them must appear): title matches first, then the most recently changed.
    "#name" or "#name=value" finds notes by label instead, as in Trilium.
    """
    query = (query or '').strip()
    sql = "SELECT * FROM notes WHERE deleted_at IS NULL AND type NOT IN ('notebook', 'library')"
    args: List[Any] = []
    words: List[str] = []
    if query.startswith('#'):
        name, _, value = query[1:].partition('=')
        sql += " AND id IN (SELECT note_id FROM attributes WHERE type = 'label' AND name = ?"
        sql += ' AND value LIKE ?)' if value else ')'
        args += [name.strip()] + ([f'%{value.strip()}%'] if value else [])
    elif query:
        words = [w.lower() for w in query.split()][:8]
        for w in words:
            sql += ' AND (title LIKE ? OR search_text LIKE ?)'
            args += [f'%{w}%', f'%{w}%']
    if types:
        sql += f' AND type IN ({",".join("?" * len(types))})'
        args += types
    sql += ' ORDER BY updated_at DESC LIMIT 1000'
    with connect() as conn:
        rows = [r for r in conn.execute(sql, args).fetchall() if can_view(person, r)]

        def in_title(r):
            return all(w in r['title'].lower() for w in words)
        rows.sort(key=lambda r: not in_title(r))
        found = []
        for r in rows[:limit]:
            path = _path(conn, r['id'])
            found.append({**summary(r), 'updated_at': r['updated_at'],
                          'where': ' › '.join(p['title'] for p in path[1:-1]),
                          'snippet': '' if not words or in_title(r) else _snippet(r['search_text'] or '', words)})
    return found


# --- protocols and favourites ---------------------------------------------------

def protocols(person: Person, query: str = '') -> List[dict]:
    """Every protocol in the library, with its folder, author, use and whether it is a favourite."""
    library = library_root()
    words = [w.lower() for w in (query or '').split()][:8]
    sql = "SELECT * FROM notes WHERE space = 'library' AND type = 'protocol' AND deleted_at IS NULL"
    args: List[Any] = []
    for w in words:
        sql += ' AND (title LIKE ? OR search_text LIKE ?)'
        args += [f'%{w}%', f'%{w}%']
    with connect() as conn:
        rows = conn.execute(sql + ' ORDER BY title COLLATE NOCASE', args).fetchall()
        favourites = {r['note_id'] for r in conn.execute('SELECT note_id FROM favorites WHERE username = ?',
                                                         (person.username,))}
        uses = dict(conn.execute(
            "SELECT l.target_id, COUNT(*) FROM links l JOIN notes n ON n.id = l.note_id "
            "WHERE l.target_type = 'note' AND n.deleted_at IS NULL AND n.space = 'notebook' "
            'GROUP BY l.target_id').fetchall())
        # The guide to writing protocols comes first, wherever the alphabet puts it.
        pinned = {r['note_id'] for r in conn.execute(
            "SELECT note_id FROM attributes WHERE name = 'seed' AND value = 'how-to-write-a-protocol'")}
        rows = sorted((r for r in rows if can_view(person, r)), key=lambda r: r['id'] not in pinned)
        share_counts = dict(conn.execute('SELECT note_id, COUNT(*) FROM shares GROUP BY note_id').fetchall())
        names = {lab['id']: lab['name'] for lab in people_mod.labs()}
        found = []
        for r in rows:
            path = [p for p in _path(conn, r['id'])[:-1] if p['id'] != library]
            lab = note_lab(r)
            found.append({**summary(r), 'folder': ' › '.join(p['title'] for p in path),
                          'created_by': r['created_by'], 'updated_by': r['updated_by'],
                          'updated_at': r['updated_at'], 'favorite': r['id'] in favourites,
                          'uses': uses.get(r['id'], 0), 'can_edit': can_edit(person, r),
                          'lab': names.get(lab) if lab else None,
                          # Seen here because another lab shares it.
                          'shared': bool(lab and lab not in person.lab_ids and not person.is_admin),
                          'shares': share_counts.get(r['id'], 0)})
    return found


def favorites(person: Person) -> List[dict]:
    with connect() as conn:
        rows = conn.execute('SELECT n.* FROM favorites f JOIN notes n ON n.id = f.note_id '
                            'WHERE f.username = ? AND n.deleted_at IS NULL ORDER BY n.title COLLATE NOCASE',
                            (person.username,)).fetchall()
    return [summary(r) for r in rows if can_view(person, r)]


def set_favorite(person: Person, note_id: str, favorite: bool) -> None:
    with connect() as conn:
        row = _row(conn, note_id)
        if row['type'] != 'protocol':
            raise ValueError('Only protocols can be favourites')
        if favorite:
            conn.execute('INSERT OR IGNORE INTO favorites (username, note_id) VALUES (?, ?)',
                         (person.username, note_id))
        else:
            conn.execute('DELETE FROM favorites WHERE username = ? AND note_id = ?', (person.username, note_id))


def protocol_snapshot(person: Person, protocol_id: str) -> Dict[str, Any]:
    """A protocol as a section to put into a page: its current version, with fresh ids."""
    row = _visible(person, protocol_id)
    if row['type'] != 'protocol':
        raise ValueError('That note is not a protocol')

    def fresh(block):
        copy = dict(block, id=content_mod.new_id())
        if copy.get('type') == 'steps':
            copy['items'] = [dict(i, id=content_mod.new_id(), by=None, at=None, done=False)
                             for i in copy.get('items') or []]
        if copy.get('type') == 'table':
            check = [c.get('kind') == 'check' for c in copy.get('columns') or []]
            copy['rows'] = [{'id': content_mod.new_id(),
                             'cells': [None if (k < len(check) and check[k]) else v
                                       for k, v in enumerate(r.get('cells') or [])]}
                            for r in copy.get('rows') or []]
        return copy

    blocks = [fresh(b) for b in json.loads(row['content'] or '[]') if b.get('type') != 'section']
    return {'type': 'section', 'title': row['title'],
            'source': {'kind': 'protocol', 'id': row['id'], 'version': row['revision'], 'name': row['title']},
            'blocks': blocks}


# --- sharing ---------------------------------------------------------------------

def _home_lab(note) -> Optional[str]:
    """The lab that sees a note without a share: a protocol's own, or its notebook owner's."""
    if note['space'] == 'library':
        return note_lab(note)
    return (people_mod.membership(note['owner']) or {}).get('lab_id')


def can_share(person: Person, note) -> bool:
    """
    A notebook: its lab's lead, or an admin. A protocol (or a page in the
    library): whoever may change it, unless it is every lab's already. A page
    or a day of a notebook: its owner, or an admin.
    """
    if note['type'] == 'notebook':
        return person.is_admin or (person.is_lab_lead and person.oversees(note['owner']))
    if note['space'] == 'library' and note['type'] not in ('library', 'folder'):
        return can_edit(person, note) and note_lab(note) is not None
    if note['space'] == 'notebook' and note['type'] in SHARED_PAGE_TYPES:
        return person.is_admin or note['owner'] == person.username
    return False


def _is_page(note) -> bool:
    return note['space'] == 'notebook' and note['type'] in SHARED_PAGE_TYPES


def _page_labs(note) -> Set[str]:
    """The labs a page may be shared with: those of its owner's chair group(s), their own included."""
    member = people_mod.membership(note['owner']) or {}
    return people_mod.chair_group_labs(m['lab_id'] for m in member.get('labs', []))


def _share_labels(conn, note_id: str) -> List[str]:
    """Who a note is shared with, by name."""
    names = {lab['id']: lab['name'] for lab in people_mod.labs()}
    return [names.get(s['target'], f"Lab {s['target']}") if s['target_type'] == 'lab' else s['target']
            for s in conn.execute('SELECT target_type, target FROM shares WHERE note_id = ? ORDER BY created_at, rowid',
                                  (note_id,))]


def shared_pages(person: Person) -> List[dict]:
    """The pages others share with this person (or their lab) to work on together, by title."""
    ids = [r for r, owner in _shared_with(person)['pages'] if owner != person.username]
    if not ids:
        return []
    with connect() as conn:
        rows = conn.execute(f"SELECT n.*, (SELECT COUNT(*) FROM branches c JOIN notes cn ON cn.id = c.note_id "
                            f"WHERE c.parent_id = n.id AND cn.deleted_at IS NULL) AS child_count FROM notes n "
                            f"WHERE n.id IN ({','.join('?' * len(ids))}) AND n.deleted_at IS NULL "
                            'ORDER BY n.title COLLATE NOCASE', ids).fetchall()
    return [{**summary(r), 'has_children': r['child_count'] > 0, 'shared': True} for r in rows]


def _shareable(conn, person: Person, note_id: str):
    row = _row(conn, note_id)
    if not can_view(person, row):
        raise Forbidden('This notebook is not yours to open')
    if not can_share(person, row):
        if row['type'] == 'notebook':
            raise Forbidden("Only the lab's lead or an administrator can share a notebook")
        if row['space'] == 'library' and row['type'] not in ('library', 'folder') and note_lab(row) is None:
            raise ValueError('Every lab can use this protocol already')
        if _is_page(row):
            raise Forbidden('Only its owner can share this page')
        raise Forbidden('Only whoever may change a protocol can share it; a page or a day is shared by its owner')
    return row


def shares(person: Person, note_id: str) -> dict:
    """Who a notebook or protocol is shared with, and whom it could be shared with."""
    with connect() as conn:
        row = _row(conn, note_id)
        if not can_view(person, row):
            raise Forbidden('This notebook is not yours to open')
        allowed = can_share(person, row)
        listed = conn.execute('SELECT * FROM shares WHERE note_id = ? ORDER BY created_at, rowid',
                              (note_id,)).fetchall() if allowed else []
    labs = people_mod.labs()
    names = {lab['id']: lab['name'] for lab in labs}
    out = {'can_share': allowed,
           'shares': [{'id': s['id'], 'target_type': s['target_type'], 'target': s['target'],
                       'label': names.get(s['target'], f"Lab {s['target']}") if s['target_type'] == 'lab' else s['target'],
                       'created_by': s['created_by'], 'created_at': s['created_at']} for s in listed]}
    if allowed and _is_page(row):
        # A page goes to people and labs of its owner's chair group, its own lab too.
        within = _page_labs(row)
        out['labs'] = [lab for lab in labs if lab['id'] in within]
        out['people'] = people_mod.colleagues(row['owner'])
    elif allowed:
        home = _home_lab(row)
        out['labs'] = [lab for lab in labs if lab['id'] != home]
        # Notebooks go to people as well as labs; protocols to labs.
        out['people'] = [u for u in people_mod.people() if u != row['owner']] if row['type'] == 'notebook' else []
    return out


def share(person: Person, note_id: str, target_type: str, target: str) -> dict:
    target = str(target or '').strip()
    with connect() as conn:
        row = _shareable(conn, person, note_id)
        if _is_page(row):
            if target_type == 'lab':
                if target not in _page_labs(row):
                    raise ValueError('A page is shared within its owner\'s chair group: choose one of its labs')
            elif target_type == 'person':
                if target == row['owner']:
                    raise ValueError('It is their own page')
                if target not in people_mod.colleagues(row['owner']):
                    raise ValueError('A page is shared within its owner\'s chair group: choose someone in one of its labs')
            else:
                raise ValueError('A page is shared with people or labs')
        elif target_type == 'lab':
            if target not in {lab['id'] for lab in people_mod.labs()}:
                raise ValueError('Choose a lab of the suite')
            if target == _home_lab(row):
                raise ValueError('Its own lab sees it already')
        elif target_type == 'person' and row['type'] == 'notebook':
            if target not in people_mod.people():
                raise ValueError('No one has that username')
            if target == row['owner']:
                raise ValueError('It is their own notebook')
        else:
            raise ValueError('A protocol is shared with labs; a notebook with labs or people')
        conn.execute('INSERT OR IGNORE INTO shares (id, note_id, target_type, target, created_by) '
                     'VALUES (?, ?, ?, ?, ?)',
                     (content_mod.new_id() + content_mod.new_id(), note_id, target_type, target, person.username))
    _forget_shares()
    return shares(person, note_id)


def unshare(person: Person, share_id: str) -> dict:
    """Retract a share: whoever may share the note may retract any of its shares."""
    with connect() as conn:
        found = conn.execute('SELECT * FROM shares WHERE id = ?', (share_id,)).fetchone()
        if found is None:
            raise NotFound('No such share')
        _shareable(conn, person, found['note_id'])
        conn.execute('DELETE FROM shares WHERE id = ?', (share_id,))
    _forget_shares()
    return shares(person, found['note_id'])
