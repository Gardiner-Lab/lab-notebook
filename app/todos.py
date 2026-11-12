"""
A week's to-do list: one page per notebook and week, shown under every day page of that week.

The list is made with a button on a day page, and is one note (type ``todo``, labelled
``weekNote`` with the week's Monday) placed under each of that week's day pages: a task added,
ticked or changed on any of them is the same task on all. A day page made later in the week
gets it too. Its content is a ``tasks`` block (app/content.py), whose tasks may link (@) a
plasmid, stock, seed lot, track or page, as text can.

A task can be moved on to next week's list: it stays on this week's, marked as moved, and a copy
goes onto next week's, or waits (``todo_pending``) until next week's list is made. It can be
brought back while its copy is not ticked.
"""

import json
from datetime import date, timedelta
from typing import List, Optional

from app import content as content_mod
from app import dates
from app import notes
from app.db import connect
from app.people import Person

TODO_TYPE = 'todo'


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def title(week: date) -> str:
    """To do · week 46 (09-11-2026 – 15-11-2026)."""
    end = week + timedelta(days=6)
    return f'To do · week {week.isocalendar()[1]} ({week.strftime(dates.DATE)} – {end.strftime(dates.DATE)})'


def find(conn, owner: str, week: date) -> Optional[str]:
    """This notebook's to-do page for the week, if it has been made."""
    row = conn.execute(
        "SELECT n.id FROM notes n JOIN attributes a ON a.note_id = n.id "
        "WHERE n.type = ? AND n.space = 'notebook' AND n.owner = ? AND n.deleted_at IS NULL "
        "AND a.name = 'weekNote' AND a.value = ? ORDER BY n.created_at LIMIT 1",
        (TODO_TYPE, owner, week.isoformat())).fetchone()
    return row['id'] if row else None


def _days(conn, owner: str, week: date) -> List[str]:
    """The day pages of that week in this notebook."""
    return [r['id'] for r in conn.execute(
        "SELECT n.id FROM notes n JOIN attributes a ON a.note_id = n.id "
        "WHERE n.type = 'day' AND n.space = 'notebook' AND n.owner = ? AND n.deleted_at IS NULL "
        "AND a.name = 'dateNote' AND a.value BETWEEN ? AND ?",
        (owner, week.isoformat(), (week + timedelta(days=6)).isoformat()))]


def _place(conn, todo_id: str, day_id: str) -> None:
    """Under a day page, first among what is under it."""
    if conn.execute('SELECT 1 FROM branches WHERE note_id = ? AND parent_id = ?', (todo_id, day_id)).fetchone():
        return
    position = conn.execute('SELECT COALESCE(MIN(position), 10) - 10 FROM branches WHERE parent_id = ?',
                            (day_id,)).fetchone()[0]
    conn.execute('INSERT INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                 (content_mod.new_id(), todo_id, day_id, position))


def place_on_day(conn, owner: str, day: date, day_id: str) -> None:
    """A day page just made: under it, its week's to-do page, if there is one."""
    todo_id = find(conn, owner, monday(day))
    if todo_id:
        _place(conn, todo_id, day_id)


def _day_of(conn, day_id: str) -> date:
    label = conn.execute("SELECT value FROM attributes WHERE note_id = ? AND name = 'dateNote'", (day_id,)).fetchone()
    if not label:
        raise ValueError('A to-do list is made from a day page')
    return date.fromisoformat(label['value'])


def _pending(conn, owner: str, week: date) -> List[dict]:
    """Tasks moved on to this week before its list was made, oldest first."""
    rows = conn.execute('SELECT * FROM todo_pending WHERE owner = ? AND week = ? ORDER BY created_at, rowid',
                        (owner, week.isoformat())).fetchall()
    conn.execute('DELETE FROM todo_pending WHERE owner = ? AND week = ?', (owner, week.isoformat()))
    return [_carried(r['html'], r['from_item'], r['from_week']) for r in rows]


def _carried(html: str, from_item: str, from_week: str) -> dict:
    return {'id': content_mod.new_id(), 'html': html, 'by': None, 'at': None,
            'moved': None, 'from_item': from_item, 'from_week': from_week}


def make(person: Person, day_id: str) -> str:
    """
    The to-do page of a day page's week: made if there is none, with the tasks moved on to it,
    and under every day page of that week. Its id.
    """
    with connect() as conn:
        day_row = notes._row(conn, day_id)
    if day_row['type'] != 'day' or not notes.can_view(person, day_row):
        raise notes.Forbidden('A to-do list is made from a day page you can open')
    if not notes.can_edit(person, day_row):
        raise notes.Forbidden('You can read this day but not change it')
    owner = day_row['owner']
    with connect() as conn:
        week = monday(_day_of(conn, day_id))
        todo_id = find(conn, owner, week)
        if not todo_id:
            blocks = [{'id': content_mod.new_id(), 'type': 'tasks', 'title': '', 'items': _pending(conn, owner, week)}]
            todo_id = notes._create(conn, title=title(week), type=TODO_TYPE, space='notebook', owner=owner,
                                    by=person.username, content=blocks)
            notes._label(conn, todo_id, 'weekNote', week.isoformat())
        for d in _days(conn, owner, week):
            _place(conn, todo_id, d)
    return todo_id


def _tasks_block(blocks: list) -> dict:
    block = next((b for b in blocks if isinstance(b, dict) and b.get('type') == 'tasks'), None)
    if block is None:
        block = {'id': content_mod.new_id(), 'type': 'tasks', 'title': '', 'items': []}
        blocks.append(block)
    return block


def _write(conn, person: Person, note_id: str, blocks: list, kind: str) -> None:
    """Content changed by the notebook itself (a task moved), kept as a revision like any edit."""
    row = notes._row(conn, note_id)
    body = json.dumps(blocks)
    number = notes._keep_revision(conn, note_id, row['title'], body, person.username, kind)
    conn.execute('UPDATE notes SET content = ?, search_text = ?, revision = ?, version = version + 1, '
                 'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 (body, content_mod.plain_text(blocks), number, person.username, note_id))
    notes._index_links(conn, note_id, blocks)


def _todo(conn, person: Person, todo_id: str):
    row = notes._row(conn, todo_id)
    if row['type'] != TODO_TYPE or not notes.can_view(person, row):
        raise notes.NotFound('To-do list not found')
    if not notes.can_edit(person, row):
        raise notes.Forbidden('You can read this list but not change it')
    label = conn.execute("SELECT value FROM attributes WHERE note_id = ? AND name = 'weekNote'", (todo_id,)).fetchone()
    return row, date.fromisoformat(label['value'])


def _item(blocks: list, item_id: str) -> dict:
    for block in blocks:
        if isinstance(block, dict) and block.get('type') == 'tasks':
            for item in block.get('items') or []:
                if item.get('id') == item_id:
                    return item
    raise notes.NotFound('That task is not on this list: save it first')


def move_on(person: Person, todo_id: str, item_id: str) -> Optional[str]:
    """Move a task on to next week's list. Gives next week's to-do page, if it is made yet."""
    with connect() as conn:
        row, week = _todo(conn, person, todo_id)
        blocks = json.loads(row['content'] or '[]')
        item = _item(blocks, item_id)
        if item.get('by'):
            raise ValueError('That task is done: only a task still to do moves on')
        if item.get('moved'):
            raise ValueError('That task has already moved on to next week')
        if not content_mod.plain_text([{'type': 'tasks', 'items': [item]}]).strip():
            raise ValueError('An empty task does not move on')
        following = week + timedelta(days=7)
        item['moved'] = following.isoformat()
        _write(conn, person, todo_id, blocks, 'edited')
        next_id = find(conn, row['owner'], following)
        if next_id:
            later = json.loads(notes._row(conn, next_id)['content'] or '[]')
            _tasks_block(later)['items'].append(_carried(item['html'], item_id, week.isoformat()))
            _write(conn, person, next_id, later, 'edited')
        else:
            conn.execute('INSERT OR REPLACE INTO todo_pending (owner, week, html, from_note, from_item, from_week) '
                         'VALUES (?, ?, ?, ?, ?, ?)',
                         (row['owner'], following.isoformat(), item['html'], todo_id, item_id, week.isoformat()))
    return next_id


def bring_back(person: Person, todo_id: str, item_id: str) -> None:
    """Undo a move: the task is to do this week again, and leaves next week's list, if not ticked there."""
    with connect() as conn:
        row, week = _todo(conn, person, todo_id)
        blocks = json.loads(row['content'] or '[]')
        item = _item(blocks, item_id)
        if not item.get('moved'):
            raise ValueError('That task has not moved on')
        following = date.fromisoformat(item['moved'])
        next_id = find(conn, row['owner'], following)
        if next_id:
            later = json.loads(notes._row(conn, next_id)['content'] or '[]')
            block = _tasks_block(later)
            copy = next((i for i in block['items'] if i.get('from_item') == item_id), None)
            if copy and copy.get('by'):
                raise ValueError('It is already done on next week\'s list')
            if copy and copy.get('moved'):
                raise ValueError('It has moved on again from next week\'s list: bring it back there first')
            if copy:
                block['items'].remove(copy)
                _write(conn, person, next_id, later, 'edited')
        else:
            conn.execute('DELETE FROM todo_pending WHERE from_note = ? AND from_item = ?', (todo_id, item_id))
        item['moved'] = None
        _write(conn, person, todo_id, blocks, 'edited')
