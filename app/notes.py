"""
Notes, where they sit, their attributes and their history, and who may do what.

    Everyone      has a notebook of their own: days, and pages under them.
                  May add protocols to the shared library and use any of them.
    A lab lead    may open the notebooks of their lab's members.
    An admin      may open every notebook.
    A protocol    may be changed by whoever wrote it, their lab's lead, or an admin.

A notebook is changed only by its owner; leads and admins read it. Every
change to a note is kept as a revision (one person's edits within a few
minutes of each other make one revision, as in Trilium), and any revision can
be restored, which is a revision too.
"""

import calendar
import json
from datetime import date
from typing import Any, Dict, List, Optional

from app import content as content_mod
from app.db import connect
from app.people import Person

LIBRARY_TITLE = 'Protocol library'
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


def can_view(person: Person, note) -> bool:
    if note['space'] == 'library':
        return True
    return person.oversees(note['owner'])


def can_edit(person: Person, note) -> bool:
    """Change this note's title, content and attributes."""
    if note['space'] == 'library':
        if note['type'] == 'library':
            return False
        author = note['created_by']
        return person.is_admin or author == person.username or (person.is_lab_lead and person.oversees(author))
    return note['owner'] == person.username and note['type'] != 'notebook'


def can_add_under(person: Person, parent) -> bool:
    """Put a new note (or a note moved here) under this one."""
    if parent['space'] == 'library':
        return parent['type'] in ('library', 'folder') or can_edit(person, parent)
    return parent['owner'] == person.username


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
        placements = [dict(r) for r in conn.execute(
            'SELECT b.id AS branch_id, b.parent_id, p.title AS parent_title FROM branches b '
            'JOIN notes p ON p.id = b.parent_id WHERE b.note_id = ? AND p.deleted_at IS NULL',
            (note_id,))]
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
            'can_edit': can_edit(person, row),
            'can_add': can_add_under(person, row),
        }
    note['backlinks'] = [summary(b) for b in backlinks if can_view(person, b)]
    return note


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
    return [{**summary(r), 'branch_id': r['branch_id'], 'has_children': r['child_count'] > 0,
             'cloned': r['placements'] > 1} for r in rows]


# --- roots ---------------------------------------------------------------------

def _create(conn, *, title: str, type: str, space: str, owner: Optional[str], by: Optional[str],
            parent_id: Optional[str] = None, content: Optional[list] = None,
            kind: str = 'created') -> str:
    note_id = content_mod.new_id() + content_mod.new_id()
    body = json.dumps(content or [])
    conn.execute('INSERT INTO notes (id, title, type, space, owner, content, revision, version, '
                 'created_by, updated_by) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)',
                 (note_id, title, type, space, owner, body, by, by))
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
    """The notebooks this person may open besides their own: their lab's, or all for an admin."""
    if not (person.is_admin or person.is_lab_lead):
        return []
    with connect() as conn:
        rows = conn.execute("SELECT * FROM notes WHERE type = 'notebook' AND deleted_at IS NULL "
                            'AND owner != ? ORDER BY owner', (person.username,)).fetchall()
    return [summary(r) for r in rows if person.oversees(r['owner'])]


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
        return _create(conn, title=(title or 'Untitled').strip()[:200] or 'Untitled', type=type,
                       space=parent['space'], owner=parent['owner'], by=person.username,
                       parent_id=parent_id, content=blocks)


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
        conn.execute('UPDATE notes SET title = ?, content = ?, revision = ?, version = version + 1, '
                     'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (new_title, body, number, person.username, note_id))
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


def delete(person: Person, note_id: str) -> None:
    """Move a note, and everything under it, to the deleted notes (kept, not erased)."""
    with connect() as conn:
        row = _row(conn, note_id)
        if row['type'] in ('notebook', 'library') or not can_edit(person, row):
            raise Forbidden('You cannot delete this note')
        for nid in _subtree(conn, note_id):
            conn.execute('UPDATE notes SET deleted_at = CURRENT_TIMESTAMP, updated_by = ? '
                         'WHERE id = ? AND deleted_at IS NULL', (person.username, nid))


def _check_target(conn, person: Person, note, parent_id: str) -> None:
    parent = _row(conn, parent_id)
    if not can_add_under(person, parent):
        raise Forbidden('You cannot put notes there')
    if parent['space'] != note['space'] or parent['owner'] != note['owner']:
        raise ValueError('A note stays in its own notebook (or in the library)')
    if parent_id in _subtree(conn, note['id']):
        raise ValueError('A note cannot go inside itself')


def move(person: Person, branch_id: str, parent_id: str, position: Optional[int] = None) -> None:
    with connect() as conn:
        branch = conn.execute('SELECT * FROM branches WHERE id = ?', (branch_id,)).fetchone()
        if branch is None:
            raise NotFound('Not found')
        note = _row(conn, branch['note_id'])
        if note['type'] in ('year', 'month', 'day') or not can_edit(person, note):
            raise Forbidden('You cannot move this note')
        _check_target(conn, person, note, parent_id)
        if position is None:
            position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                    (parent_id,)).fetchone()[0]
        conn.execute('UPDATE OR IGNORE branches SET parent_id = ?, position = ? WHERE id = ?',
                     (parent_id, int(position), branch_id))


def place_also(person: Person, note_id: str, parent_id: str) -> None:
    """Show a note in a second place too: one note, two branches (a Trilium clone)."""
    with connect() as conn:
        note = _row(conn, note_id)
        if not can_view(person, note) or note['type'] in ('notebook', 'library'):
            raise Forbidden('You cannot place this note elsewhere')
        _check_target(conn, person, note, parent_id)
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                                (parent_id,)).fetchone()[0]
        conn.execute('INSERT OR IGNORE INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                     (content_mod.new_id(), note_id, parent_id, position))


def remove_placement(person: Person, branch_id: str) -> None:
    """Take a note out of one of its places; it must keep at least one."""
    with connect() as conn:
        branch = conn.execute('SELECT * FROM branches WHERE id = ?', (branch_id,)).fetchone()
        if branch is None:
            raise NotFound('Not found')
        note = _row(conn, branch['note_id'])
        if not can_add_under(person, _row(conn, branch['parent_id'])):
            raise Forbidden('You cannot change this')
        if conn.execute('SELECT COUNT(*) FROM branches WHERE note_id = ?', (note['id'],)).fetchone()[0] < 2:
            raise ValueError('This is its only place: delete the note instead')
        conn.execute('DELETE FROM branches WHERE id = ?', (branch_id,))


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
        if attr['name'] in ('dateNote', 'monthNote', 'yearNote', 'notebookRoot', 'protocolLibrary'):
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
        conn.execute('UPDATE notes SET title = ?, content = ?, revision = ?, version = version + 1, '
                     'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (r['title'], r['content'], new, person.username, note_id))
        _index_links(conn, note_id, json.loads(r['content']))
    return get(person, note_id)


# --- finding notes -------------------------------------------------------------

def search(person: Person, query: str, types: Optional[List[str]] = None, limit: int = 30) -> List[dict]:
    query = (query or '').strip()
    sql = 'SELECT * FROM notes WHERE deleted_at IS NULL AND type NOT IN (\'notebook\', \'library\')'
    args: List[Any] = []
    if query:
        sql += ' AND title LIKE ?'
        args.append(f'%{query}%')
    if types:
        sql += f' AND type IN ({",".join("?" * len(types))})'
        args += types
    sql += ' ORDER BY updated_at DESC LIMIT 500'
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [summary(r) for r in rows if can_view(person, r)][:limit]


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
