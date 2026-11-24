"""
Projects: work packages, tasks and subtasks, what waits for what, and the schedule that follows.

    A project   has members, invited by whoever set it up (its owner): anyone with an account in
                Trellis Tools. Every member adds and changes its work packages and tasks; the owner
                also renames it, invites and removes members, and deletes it.
    A work package
                groups a project's tasks. Its dates are those of its tasks.
    A task      belongs to a work package and may have subtasks (a task with subtasks spans them).
                It has a start and a length in days, people working on it, and may wait for other
                tasks: it starts the day after the last of them finishes, plus a lag of days if one
                is set. Change when a task finishes - its length, its start, or by ticking it done
                earlier or later than planned - and the tasks waiting for it move with it, and those
                waiting for them. A task without anything to wait for keeps the start it is given.
                Days are calendar days.

Each task is also a page (a note of type 'task', space 'project'), for its description and notes:
text, tables, steps, photos, @ links to protocols, stocks, seeds and plasmids, with a history like any
page. A task or work package can be put on a meeting's page (as an agenda item) or on any page of a
notebook: a section that names it, in which whatever is written about it is kept; the task's page
lists every page it was talked about on, and what was written there.
"""

import json
from datetime import date, timedelta
from typing import Dict, List, Optional

from app import content as content_mod
from app import notes
from app import people as people_mod
from app.db import connect
from app.people import Person

TASK_TYPE = 'task'
SPACE = 'project'
MAX_DAYS = 3650
COLOURS = ('#2e7d5b', '#3867b5', '#b5562e', '#7a4bb0', '#a07a12', '#2b8a99', '#b03a6f', '#5c6b2e')


def _today() -> date:
    from app import bookings
    return bookings.today()


def _new_id() -> str:
    return content_mod.new_id() + content_mod.new_id()


def _text(value, limit: int = 200) -> str:
    return ' '.join(str(value or '').split())[:limit]


def _day(value, what: str) -> date:
    try:
        return date.fromisoformat(str(value or '').strip())
    except ValueError:
        raise ValueError(f'{what} must be a date (YYYY-MM-DD)')


# --- who may do what ---------------------------------------------------------------------

def _members(conn, project_id: str) -> List[str]:
    return [r['username'] for r in conn.execute(
        'SELECT username FROM project_members WHERE project_id = ? ORDER BY username COLLATE NOCASE', (project_id,))]


def _project(conn, project_id: str):
    row = conn.execute('SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL', (project_id,)).fetchone()
    if row is None:
        raise notes.NotFound('No such project')
    return row


def is_member(conn, person: Person, project_id: str) -> bool:
    return bool(conn.execute('SELECT 1 FROM project_members WHERE project_id = ? AND username = ?',
                             (project_id, person.username)).fetchone())


def _open(conn, person: Person, project_id: str):
    """A project they may open and change: they are a member (an administrator opens any)."""
    row = _project(conn, project_id)
    if not (is_member(conn, person, project_id) or person.is_admin):
        raise notes.Forbidden('You are not a member of this project')
    return row


def _owned(conn, person: Person, project_id: str):
    row = _open(conn, person, project_id)
    if row['owner'] != person.username and not person.is_admin:
        raise notes.Forbidden('Only whoever set up the project changes this')
    return row


def can_view_note(person: Person, note) -> bool:
    """A task's page: the project's members (and administrators)."""
    project_id = note['project']
    if not project_id:
        return False
    if person.is_admin:
        return True
    with connect() as conn:
        return is_member(conn, person, project_id) and bool(
            conn.execute('SELECT 1 FROM projects WHERE id = ? AND deleted_at IS NULL', (project_id,)).fetchone())


def invitable(person: Person, project_id: Optional[str] = None) -> List[str]:
    """Anyone with an account in Trellis Tools (in the teaching demo, its people)."""
    return people_mod.people_for(person)


# --- projects ------------------------------------------------------------------------------

def mine(person: Person) -> List[dict]:
    """The projects they are a member of (every project, for an administrator), with their span and progress."""
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM projects WHERE deleted_at IS NULL AND (? OR id IN '
            '(SELECT project_id FROM project_members WHERE username = ?)) ORDER BY title COLLATE NOCASE',
            (1 if person.is_admin else 0, person.username)).fetchall()
        found = []
        for r in rows:
            span = conn.execute('SELECT MIN(sched_start) AS s, MAX(sched_end) AS e, COUNT(*) AS n, '
                                'SUM(CASE WHEN done_on IS NOT NULL THEN 1 ELSE 0 END) AS done FROM tasks t '
                                'WHERE project_id = ? AND deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM tasks c '
                                'WHERE c.parent_id = t.id AND c.deleted_at IS NULL)', (r['id'],)).fetchone()
            found.append({'id': r['id'], 'title': r['title'], 'owner': r['owner'], 'members': _members(conn, r['id']),
                          'start': span['s'], 'end': span['e'], 'tasks': span['n'], 'done': span['done'] or 0,
                          'member': is_member(conn, person, r['id'])})
    return found


def create(person: Person, data: dict) -> dict:
    title = _text(data.get('title'), 120)
    if not title:
        raise ValueError('Give the project a title')
    project_id = _new_id()
    with connect() as conn:
        conn.execute('INSERT INTO projects (id, title, description, owner, created_by) VALUES (?, ?, ?, ?, ?)',
                     (project_id, title, str(data.get('description') or '')[:4000], person.username, person.username))
        conn.execute('INSERT INTO project_members (project_id, username, added_by) VALUES (?, ?, ?)',
                     (project_id, person.username, person.username))
    for u in data.get('members') or []:
        if u != person.username:
            add_member(person, project_id, u)
    return get(person, project_id)


def update(person: Person, project_id: str, data: dict) -> dict:
    with connect() as conn:
        row = _owned(conn, person, project_id)
        title = _text(data.get('title'), 120) if 'title' in data else row['title']
        if not title:
            raise ValueError('Give the project a title')
        description = str(data.get('description') or '')[:4000] if 'description' in data else row['description']
        conn.execute('UPDATE projects SET title = ?, description = ? WHERE id = ?', (title, description, project_id))
    return get(person, project_id)


def delete(person: Person, project_id: str) -> None:
    """Gone with its work packages and tasks (kept in the database, marked deleted)."""
    with connect() as conn:
        _owned(conn, person, project_id)
        conn.execute('UPDATE projects SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?', (project_id,))
        conn.execute("UPDATE notes SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ? WHERE project = ? "
                     "AND deleted_at IS NULL", (person.username, project_id))


def add_member(person: Person, project_id: str, username: str) -> dict:
    username = str(username or '').strip()
    with connect() as conn:
        _owned(conn, person, project_id)
    if username not in invitable(person, project_id):
        raise ValueError(f'No one called {username} has an account in Trellis Tools')
    with connect() as conn:
        conn.execute('INSERT OR IGNORE INTO project_members (project_id, username, added_by) VALUES (?, ?, ?)',
                     (project_id, username, person.username))
    return get(person, project_id)


def remove_member(person: Person, project_id: str, username: str) -> Optional[dict]:
    """The owner takes someone off the project; anyone may leave it. The owner stays."""
    with connect() as conn:
        row = _open(conn, person, project_id)
        if username != person.username and row['owner'] != person.username and not person.is_admin:
            raise notes.Forbidden('Only whoever set up the project takes people off it')
        if username == row['owner']:
            raise ValueError('Whoever set up the project stays on it')
        conn.execute('DELETE FROM project_members WHERE project_id = ? AND username = ?', (project_id, username))
        conn.execute('DELETE FROM task_people WHERE username = ? AND task_id IN (SELECT id FROM tasks WHERE project_id = ?)',
                     (username, project_id))
    return None if username == person.username else get(person, project_id)


# --- reading a project whole ------------------------------------------------------------------

def _task_dict(r, people: Dict[str, List[str]], deps: Dict[str, List[dict]], kids: Dict[str, int]) -> dict:
    return {'id': r['id'], 'wp_id': r['wp_id'], 'parent_id': r['parent_id'], 'note_id': r['note_id'],
            'title': r['title'], 'start_on': r['start_on'], 'duration': r['duration'],
            'start': r['sched_start'], 'end': r['sched_end'], 'done_on': r['done_on'], 'done_by': r['done_by'],
            'position': r['position'], 'people': people.get(r['id'], []), 'after': deps.get(r['id'], []),
            'subtasks': kids.get(r['id'], 0)}


def get(person: Person, project_id: str) -> dict:
    with connect() as conn:
        row = _open(conn, person, project_id)
        wps = conn.execute('SELECT * FROM workpackages WHERE project_id = ? AND deleted_at IS NULL '
                           'ORDER BY position, created_at', (project_id,)).fetchall()
        rows = conn.execute('SELECT * FROM tasks WHERE project_id = ? AND deleted_at IS NULL ORDER BY position, created_at',
                            (project_id,)).fetchall()
        ids = [r['id'] for r in rows]
        people: Dict[str, List[str]] = {}
        deps: Dict[str, List[dict]] = {}
        if ids:
            marks = ','.join('?' * len(ids))
            for p in conn.execute(f'SELECT * FROM task_people WHERE task_id IN ({marks}) ORDER BY username', ids):
                people.setdefault(p['task_id'], []).append(p['username'])
            for d in conn.execute(f'SELECT * FROM task_deps WHERE task_id IN ({marks})', ids):
                deps.setdefault(d['task_id'], []).append({'id': d['after_id'], 'lag': d['lag']})
        kids: Dict[str, int] = {}
        for r in rows:
            if r['parent_id']:
                kids[r['parent_id']] = kids.get(r['parent_id'], 0) + 1
        tasks = [_task_dict(r, people, deps, kids) for r in rows]
        packages = []
        for i, w in enumerate(wps):
            mine_ = [t for t in tasks if t['wp_id'] == w['id']]
            starts = [t['start'] for t in mine_ if t['start']]
            ends = [t['end'] for t in mine_ if t['end']]
            leaves = [t for t in mine_ if not t['subtasks']]
            packages.append({'id': w['id'], 'title': w['title'], 'description': w['description'],
                             'position': w['position'], 'colour': COLOURS[i % len(COLOURS)],
                             'start': min(starts) if starts else None, 'end': max(ends) if ends else None,
                             'tasks': len(leaves), 'done': sum(1 for t in leaves if t['done_on'])})
        return {'id': row['id'], 'title': row['title'], 'description': row['description'], 'owner': row['owner'],
                'members': _members(conn, project_id), 'can_manage': row['owner'] == person.username or person.is_admin,
                'workpackages': packages, 'tasks': tasks, 'today': _today().isoformat()}


# --- work packages ---------------------------------------------------------------------------

def _wp(conn, person: Person, wp_id: str):
    row = conn.execute('SELECT * FROM workpackages WHERE id = ? AND deleted_at IS NULL', (wp_id,)).fetchone()
    if row is None:
        raise notes.NotFound('No such work package')
    _open(conn, person, row['project_id'])
    return row


def add_workpackage(person: Person, project_id: str, data: dict) -> dict:
    title = _text(data.get('title'), 160)
    if not title:
        raise ValueError('Give the work package a title')
    with connect() as conn:
        _open(conn, person, project_id)
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM workpackages WHERE project_id = ?',
                                (project_id,)).fetchone()[0]
        conn.execute('INSERT INTO workpackages (id, project_id, title, description, position, created_by) '
                     'VALUES (?, ?, ?, ?, ?, ?)', (_new_id(), project_id, title,
                                                   str(data.get('description') or '')[:4000], position, person.username))
    return get(person, project_id)


def update_workpackage(person: Person, wp_id: str, data: dict) -> dict:
    with connect() as conn:
        row = _wp(conn, person, wp_id)
        title = _text(data.get('title'), 160) if 'title' in data else row['title']
        if not title:
            raise ValueError('Give the work package a title')
        description = str(data.get('description') or '')[:4000] if 'description' in data else row['description']
        position = int(data['position']) if isinstance(data.get('position'), int) else row['position']
        conn.execute('UPDATE workpackages SET title = ?, description = ?, position = ? WHERE id = ?',
                     (title, description, position, wp_id))
    return get(person, row['project_id'])


def delete_workpackage(person: Person, wp_id: str) -> dict:
    with connect() as conn:
        row = _wp(conn, person, wp_id)
        ids = [r['id'] for r in conn.execute('SELECT id FROM tasks WHERE wp_id = ? AND deleted_at IS NULL', (wp_id,))]
        _drop_tasks(conn, person, ids)
        conn.execute('UPDATE workpackages SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?', (wp_id,))
        schedule(conn, row['project_id'])
    return get(person, row['project_id'])


# --- tasks -------------------------------------------------------------------------------------

def _task(conn, person: Person, task_id: str):
    row = conn.execute('SELECT * FROM tasks WHERE id = ? AND deleted_at IS NULL', (task_id,)).fetchone()
    if row is None:
        raise notes.NotFound('No such task')
    _open(conn, person, row['project_id'])
    return row


def _descendants(conn, task_id: str) -> List[str]:
    found, todo = [], [task_id]
    while todo:
        current = todo.pop()
        kids = [r['id'] for r in conn.execute('SELECT id FROM tasks WHERE parent_id = ? AND deleted_at IS NULL', (current,))]
        found.extend(kids)
        todo.extend(kids)
    return found


def _ancestors(conn, task_id: str) -> List[str]:
    found, current = [], task_id
    while current:
        row = conn.execute('SELECT parent_id FROM tasks WHERE id = ?', (current,)).fetchone()
        current = row['parent_id'] if row else None
        if current:
            if current in found:
                break
            found.append(current)
    return found


def _set_task(conn, person: Person, project_id: str, task_id: Optional[str], data: dict, old=None) -> None:
    """Check and write a task's fields, people and what it waits for (task_id is new when old is None)."""
    title = _text(data.get('title'), 200) if 'title' in data or old is None else old['title']
    if not title:
        raise ValueError('Give the task a title')
    wp_id = str(data.get('wp_id') or (old['wp_id'] if old else '') or '')
    parent_id = str(data.get('parent_id') or '') if 'parent_id' in data else (old['parent_id'] if old else '')
    parent_id = parent_id or None
    if parent_id:
        parent = conn.execute('SELECT * FROM tasks WHERE id = ? AND project_id = ? AND deleted_at IS NULL',
                              (parent_id, project_id)).fetchone()
        if parent is None:
            raise ValueError('The task it is a subtask of is not in this project')
        if task_id and (parent_id == task_id or parent_id in _descendants(conn, task_id)):
            raise ValueError('A task cannot be a subtask of itself, or of one of its own subtasks')
        wp_id = parent['wp_id']           # a subtask is in its task's work package
    if not conn.execute('SELECT 1 FROM workpackages WHERE id = ? AND project_id = ? AND deleted_at IS NULL',
                        (wp_id, project_id)).fetchone():
        raise ValueError('Choose a work package of this project')
    start_on = _day(data.get('start_on'), 'The start') if data.get('start_on') else (
        date.fromisoformat(old['start_on']) if old else _today())
    try:
        duration = int(data.get('duration', old['duration'] if old else 5))
    except (TypeError, ValueError):
        raise ValueError('The length is a number of days')
    if not 1 <= duration <= MAX_DAYS:
        raise ValueError(f'A task lasts from 1 to {MAX_DAYS} days')
    done_on = old['done_on'] if old else None
    done_by = old['done_by'] if old else None
    if 'done' in data:
        if data.get('done'):
            done_on = (_day(data.get('done_on'), 'The day it was done') if data.get('done_on') else _today()).isoformat()
            done_by = done_by if old and old['done_on'] else person.username
        else:
            done_on = done_by = None
    if old is None:
        position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM tasks WHERE project_id = ?',
                                (project_id,)).fetchone()[0]
        conn.execute('INSERT INTO tasks (id, project_id, wp_id, parent_id, title, start_on, duration, sched_start, '
                     'sched_end, done_on, done_by, position, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (task_id, project_id, wp_id, parent_id, title, start_on.isoformat(), duration, start_on.isoformat(),
                      (start_on + timedelta(days=duration - 1)).isoformat(), done_on, done_by, position, person.username))
    else:
        conn.execute('UPDATE tasks SET wp_id = ?, parent_id = ?, title = ?, start_on = ?, duration = ?, done_on = ?, '
                     'done_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (wp_id, parent_id, title, start_on.isoformat(), duration, done_on, done_by, task_id))
        # Its subtasks follow it into another work package.
        for kid in _descendants(conn, task_id):
            conn.execute('UPDATE tasks SET wp_id = ? WHERE id = ?', (wp_id, kid))
    if 'people' in data:
        members = set(_members(conn, project_id))
        chosen = [u for u in (data.get('people') or []) if isinstance(u, str)]
        stray = [u for u in chosen if u not in members]
        if stray:
            raise ValueError(f'{people_mod.shown(stray[0])} is not a member of the project: invite them first')
        conn.execute('DELETE FROM task_people WHERE task_id = ?', (task_id,))
        conn.executemany('INSERT OR IGNORE INTO task_people (task_id, username) VALUES (?, ?)',
                         [(task_id, u) for u in chosen])
    if 'after' in data:
        _set_deps(conn, project_id, task_id, data.get('after') or [])


def _set_deps(conn, project_id: str, task_id: str, after: list) -> None:
    related = {task_id, *_descendants(conn, task_id), *_ancestors(conn, task_id)}
    rows = []
    for item in after[:100]:
        other = str((item or {}).get('id') if isinstance(item, dict) else item or '')
        try:
            lag = int((item or {}).get('lag') or 0) if isinstance(item, dict) else 0
        except (TypeError, ValueError):
            raise ValueError('A lag is a number of days')
        if not -365 <= lag <= MAX_DAYS:
            raise ValueError('A lag is from -365 to 3650 days')
        if other in related:
            raise ValueError('A task cannot wait for itself, for a task it is part of, or for one of its own subtasks')
        if not conn.execute('SELECT 1 FROM tasks WHERE id = ? AND project_id = ? AND deleted_at IS NULL',
                            (other, project_id)).fetchone():
            raise ValueError('A task waits only for tasks of the same project')
        rows.append((task_id, other, lag))
    conn.execute('DELETE FROM task_deps WHERE task_id = ?', (task_id,))
    conn.executemany('INSERT OR REPLACE INTO task_deps (task_id, after_id, lag) VALUES (?, ?, ?)', rows)


def _task_note(conn, person: Person, project_id: str, task_id: str, title: str) -> str:
    note_id = notes._create(conn, title=title, type=TASK_TYPE, space=SPACE, owner=None, by=person.username,
                            content=[{'id': content_mod.new_id(), 'type': 'text', 'html': ''}])
    conn.execute('UPDATE notes SET project = ? WHERE id = ?', (project_id, note_id))
    conn.execute('UPDATE tasks SET note_id = ? WHERE id = ?', (note_id, task_id))
    return note_id


def add_task(person: Person, project_id: str, data: dict) -> dict:
    task_id = _new_id()
    with connect() as conn:
        _open(conn, person, project_id)
        _set_task(conn, person, project_id, task_id, data)
        title = conn.execute('SELECT title FROM tasks WHERE id = ?', (task_id,)).fetchone()['title']
        _task_note(conn, person, project_id, task_id, title)
        moved = schedule(conn, project_id, changed=task_id)
    return {'project': get(person, project_id), 'task_id': task_id, 'moved': moved}


def update_task(person: Person, task_id: str, data: dict) -> dict:
    with connect() as conn:
        old = _task(conn, person, task_id)
        _set_task(conn, person, old['project_id'], task_id, data, old)
        title = conn.execute('SELECT title FROM tasks WHERE id = ?', (task_id,)).fetchone()['title']
        if old['note_id'] and title != old['title']:
            conn.execute('UPDATE notes SET title = ? WHERE id = ?', (title, old['note_id']))
        moved = schedule(conn, old['project_id'], changed=task_id)
    return {'project': get(person, old['project_id']), 'task_id': task_id, 'moved': moved}


def _drop_tasks(conn, person: Person, ids: List[str]) -> None:
    every = set(ids)
    for t in ids:
        every.update(_descendants(conn, t))
    for t in every:
        row = conn.execute('SELECT note_id FROM tasks WHERE id = ?', (t,)).fetchone()
        conn.execute('UPDATE tasks SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?', (t,))
        conn.execute('DELETE FROM task_deps WHERE task_id = ? OR after_id = ?', (t, t))
        if row and row['note_id']:
            conn.execute('UPDATE notes SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ? WHERE id = ? '
                         'AND deleted_at IS NULL', (person.username, row['note_id']))


def delete_task(person: Person, task_id: str) -> dict:
    """The task and its subtasks; whatever waited for them no longer does."""
    with connect() as conn:
        row = _task(conn, person, task_id)
        _drop_tasks(conn, person, [task_id])
        moved = schedule(conn, row['project_id'])
    return {'project': get(person, row['project_id']), 'moved': moved}


# --- the schedule ------------------------------------------------------------------------------

def schedule(conn, project_id: str, changed: Optional[str] = None) -> List[dict]:
    """
    Work out every task's dates: a task that waits starts the day after the last of what it waits for
    (its own and its parent tasks') finishes, plus the lag; one that does not keeps its own start. A task
    is done when ticked: it finished then. A task with subtasks spans them. Gives the tasks that moved,
    but the one changed. A loop of tasks waiting for each other is refused.
    """
    rows = {r['id']: dict(r) for r in conn.execute(
        'SELECT * FROM tasks WHERE project_id = ? AND deleted_at IS NULL', (project_id,))}
    deps: Dict[str, List[tuple]] = {}
    for d in conn.execute('SELECT d.* FROM task_deps d JOIN tasks t ON t.id = d.task_id '
                          'WHERE t.project_id = ? AND t.deleted_at IS NULL', (project_id,)):
        if d['after_id'] in rows:
            deps.setdefault(d['task_id'], []).append((d['after_id'], d['lag']))
    kids: Dict[str, List[str]] = {}
    for t in rows.values():
        if t['parent_id'] in rows:
            kids.setdefault(t['parent_id'], []).append(t['id'])

    def chain(tid):
        found, current = [], tid
        while current in rows and current not in found:
            found.append(current)
            current = rows[current]['parent_id']
        return found

    start = {t: date.fromisoformat(rows[t]['sched_start'] or rows[t]['start_on']) for t in rows}
    end = {t: date.fromisoformat(rows[t]['sched_end'] or rows[t]['start_on']) for t in rows}
    before = {t: (start[t], end[t]) for t in rows}

    def depth(t):
        return len(chain(t))
    summaries = sorted(kids, key=depth, reverse=True)          # the deepest first
    leaves = [t for t in rows if t not in kids]
    for _ in range(len(rows) + 3):
        moved = False
        for t in leaves:
            row = rows[t]
            waits = [(a, lag) for c in chain(t) for a, lag in deps.get(c, [])]
            s = max((end[a] + timedelta(days=1 + lag) for a, lag in waits), default=date.fromisoformat(row['start_on']))
            e = s + timedelta(days=row['duration'] - 1)
            if row['done_on']:
                e = date.fromisoformat(row['done_on'])
                s = min(s, e)
            if (s, e) != (start[t], end[t]):
                start[t], end[t], moved = s, e, True
        for t in summaries:
            s, e = min(start[k] for k in kids[t]), max(end[k] for k in kids[t])
            if (s, e) != (start[t], end[t]):
                start[t], end[t], moved = s, e, True
        if not moved:
            break
    else:
        raise ValueError('These tasks wait for each other in a loop: one of them must not wait')
    shifted = []
    for t, row in rows.items():
        if (start[t], end[t]) != before[t]:
            fixed = start[t].isoformat() if (deps.get(t) or any(deps.get(c) for c in chain(t))) else row['start_on']
            conn.execute('UPDATE tasks SET sched_start = ?, sched_end = ?, start_on = ? WHERE id = ?',
                         (start[t].isoformat(), end[t].isoformat(), fixed if t not in kids else row['start_on'], t))
            if t != changed:
                shifted.append({'id': t, 'title': row['title'], 'from': before[t][0].isoformat(),
                                'to': start[t].isoformat(), 'from_end': before[t][1].isoformat(),
                                'end': end[t].isoformat()})
    return sorted(shifted, key=lambda m: m['to'])


# --- a task's page, and where it was talked about ------------------------------------------------

def for_note(conn, person: Person, note_id: str) -> Optional[dict]:
    """The task a task's page is of, with its project, work package and dates, to show at the top of the page."""
    row = conn.execute('SELECT * FROM tasks WHERE note_id = ? AND deleted_at IS NULL', (note_id,)).fetchone()
    if row is None:
        return None
    project = conn.execute('SELECT id, title FROM projects WHERE id = ?', (row['project_id'],)).fetchone()
    wp = conn.execute('SELECT id, title FROM workpackages WHERE id = ?', (row['wp_id'],)).fetchone()
    parent = conn.execute('SELECT id, title, note_id FROM tasks WHERE id = ?', (row['parent_id'],)).fetchone() \
        if row['parent_id'] else None
    after = [{'id': d['after_id'], 'lag': d['lag'], 'title': d['title'], 'note_id': d['note_id'], 'end': d['sched_end'],
              'done_on': d['done_on']} for d in conn.execute(
        'SELECT d.*, t.title, t.note_id, t.sched_end, t.done_on FROM task_deps d JOIN tasks t ON t.id = d.after_id '
        'WHERE d.task_id = ? AND t.deleted_at IS NULL', (row['id'],))]
    waiting = [{'id': t['id'], 'title': t['title'], 'note_id': t['note_id'], 'start': t['sched_start']}
               for t in conn.execute('SELECT t.* FROM task_deps d JOIN tasks t ON t.id = d.task_id '
                                     'WHERE d.after_id = ? AND t.deleted_at IS NULL', (row['id'],))]
    subtasks = [{'id': t['id'], 'title': t['title'], 'note_id': t['note_id'], 'start': t['sched_start'],
                 'end': t['sched_end'], 'done_on': t['done_on']} for t in conn.execute(
        'SELECT * FROM tasks WHERE parent_id = ? AND deleted_at IS NULL ORDER BY position', (row['id'],))]
    return {'id': row['id'], 'title': row['title'], 'project': dict(project), 'workpackage': dict(wp) if wp else None,
            'parent': dict(parent) if parent else None, 'start': row['sched_start'], 'end': row['sched_end'],
            'start_on': row['start_on'], 'duration': row['duration'], 'done_on': row['done_on'],
            'done_by': row['done_by'],
            'people': [r['username'] for r in conn.execute('SELECT username FROM task_people WHERE task_id = ? '
                                                           'ORDER BY username', (row['id'],))],
            'after': after, 'waiting': waiting, 'subtasks': subtasks, 'wp_id': row['wp_id'],
            'parent_id': row['parent_id'], 'discussed': discussed(conn, person, 'task', row['id'])}


def _tagged_in(blocks: list, target_id: str) -> List[str]:
    """The lines a task is tagged in with @ (a paragraph, a list item, a task, a step, a table cell), as text."""
    import html as html_mod
    import re
    mark = f'data-task="{target_id}"'
    token = f'(task:{target_id})'
    found: List[str] = []

    def plain(fragment: str) -> str:
        return ' '.join(html_mod.unescape(re.sub(r'<[^>]+>', ' ', fragment)).split())

    def walk(items):
        for b in items or []:
            if not isinstance(b, dict):
                continue
            kind = b.get('type')
            if kind == 'text' and mark in (b.get('html') or ''):
                # Line by line: split where a paragraph, heading, list item or line break begins or ends (the first
                # line of a page may stand in no paragraph at all).
                lines = re.split(r'</?(?:p|li|ul|ol|h[1-6]|blockquote|pre|div)\b[^>]*>|<br\s*/?>', b['html'], flags=re.I)
                found.extend(plain(line) for line in lines if mark in line)
            elif kind in ('tasks', 'steps'):
                found.extend(plain(i.get('html') or i.get('text') or '') for i in b.get('items') or []
                             if mark in (i.get('html') or ''))
            elif kind == 'table':
                for row in b.get('rows') or []:
                    found.extend(content_mod.cell_text(c) for c in row.get('cells') or [] if isinstance(c, str) and token in c)
            elif kind == 'section':
                walk(b.get('blocks'))
    walk(blocks)
    return [f for f in found if f]


def discussed(conn, person: Person, kind: str, target_id: str) -> List[dict]:
    """
    The pages a task or work package was put on (a meeting's agenda, a day of a notebook), or a task was tagged in
    with @, newest first, with what was written there about it: those this person may open.
    """
    rows = conn.execute('SELECT n.* FROM links l JOIN notes n ON n.id = l.note_id WHERE l.target_type = ? '
                        'AND l.target_id = ? AND n.deleted_at IS NULL', (kind, target_id)).fetchall()
    found = []
    for r in rows:
        if not notes.can_view(person, r):
            continue
        blocks = json.loads(r['content'] or '[]')
        said = [content_mod.plain_text(b.get('blocks') or []) for b in blocks
                if b.get('type') == 'section' and (b.get('source') or {}).get('kind') == kind
                and (b.get('source') or {}).get('id') == target_id]
        if kind == 'task':
            said += _tagged_in(blocks, target_id)
        when = conn.execute("SELECT value FROM attributes WHERE note_id = ? AND name IN ('meetingDate', 'dateNote') "
                            'LIMIT 1', (r['id'],)).fetchone()
        found.append({**notes.summary(r), 'date': when['value'] if when else (r['updated_at'] or '')[:10],
                      'text': ' · '.join(s for s in said if s)[:1200]})
    return sorted(found, key=lambda f: f['date'], reverse=True)


def workpackage_discussed(person: Person, wp_id: str) -> List[dict]:
    with connect() as conn:
        _wp(conn, person, wp_id)
        return discussed(conn, person, 'workpackage', wp_id)


# --- the Gantt chart as a PDF --------------------------------------------------------------------

MAX_SVG = 3_000_000


def gantt_pdf(person: Person, project_id: str, svg: str) -> bytes:
    """
    The Gantt chart (the SVG the page drew) on a landscape page, A4 or A3 as it is wide, then a table of the
    tasks. Made with WeasyPrint, fetching nothing: the chart carries its own styles.
    """
    import html as html_mod
    import re
    from weasyprint import HTML
    project = get(person, project_id)
    svg = str(svg or '')
    if len(svg) > MAX_SVG:
        raise ValueError('The chart is too large to export')
    start = svg.find('<svg')
    if start < 0 or not svg.rstrip().endswith('</svg>'):
        raise ValueError('Send the chart as an SVG')
    svg = svg[start:]
    # Nothing in it may run or reach out: no scripts, no handlers, no links to anywhere.
    svg = re.sub(r'<script\b.*?</script\s*>', '', svg, flags=re.I | re.S)
    svg = re.sub(r'\son\w+\s*=\s*("[^"]*"|\'[^\']*\')', '', svg, flags=re.I)
    svg = re.sub(r'<(foreignObject|image|use|iframe)\b.*?(/>|</\1\s*>)', '', svg, flags=re.I | re.S)
    width = re.search(r'\bwidth="([\d.]+)"', svg)
    size = 'A3' if width and float(width.group(1)) > 1500 else 'A4'
    esc = html_mod.escape
    names = people_mod.display_names()
    titles = {t['id']: t['title'] for t in project['tasks']}

    def dmy(iso):
        return '-'.join(reversed(iso.split('-'))) if iso else ''
    rows = []
    for wp in project['workpackages']:
        span = f" · {dmy(wp['start'])} – {dmy(wp['end'])}" if wp['start'] else ''
        rows.append(f"<tr class='wp'><td colspan='7'>{esc(wp['title'])}{span}</td></tr>")
        kids: Dict[Optional[str], List[dict]] = {}
        for t in project['tasks']:
            if t['wp_id'] == wp['id']:
                kids.setdefault(t['parent_id'], []).append(t)

        def walk(parent, depth):
            for t in kids.get(parent, []):
                waits = ', '.join(esc(titles.get(a['id'], '?')) + (f" +{a['lag']} d" if a['lag'] else '')
                                  for a in t['after'])
                people = ', '.join(esc(people_mod.shown(u, names)) for u in t['people'])
                days = (date.fromisoformat(t['end']) - date.fromisoformat(t['start'])).days + 1
                done = f"✓ {dmy(t['done_on'])}" if t['done_on'] else ''
                rows.append(f"<tr><td style='padding-left:{0.3 + depth * 1.1}em'>{'<b>' if t['subtasks'] else ''}"
                            f"{esc(t['title'])}{'</b>' if t['subtasks'] else ''}</td><td>{dmy(t['start'])}</td>"
                            f"<td>{dmy(t['end'])}</td><td class='n'>{days}</td><td>{waits}</td><td>{people}</td>"
                            f"<td>{done}</td></tr>")
                walk(t['id'], depth + 1)
        walk(None, 0)
    members = ', '.join(esc(people_mod.shown(u, names)) for u in project['members'])
    today_text = dmy(_today().isoformat())
    source = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {size} landscape; margin: 12mm; @bottom-right {{ content: "{esc(project['title'])} · page " counter(page) " of " counter(pages);
  font: 8pt sans-serif; color: #6f665c; }} }}
body {{ font-family: "DejaVu Sans", sans-serif; font-size: 9pt; color: #2b2620; }}
h1 {{ font-size: 15pt; margin: 0 0 2mm; }}
.meta {{ color: #6f665c; margin: 0 0 4mm; }}
.chart svg {{ width: 100%; height: auto; max-height: 160mm; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 6mm; page-break-before: auto; }}
th, td {{ text-align: left; padding: 1.2mm 2mm; border-bottom: 0.3pt solid #e6dfd4; vertical-align: top; }}
th {{ font-size: 8pt; color: #6f665c; }}
td.n {{ text-align: right; }}
tr.wp td {{ background: #f3efe8; font-weight: bold; }}
thead {{ display: table-header-group; }}
tr {{ page-break-inside: avoid; }}
</style></head><body>
<h1>{esc(project['title'])}</h1>
<p class="meta">Gantt chart · exported {today_text} · {members}</p>
<div class="chart">{svg}</div>
<table><thead><tr><th>Task</th><th>Start</th><th>End</th><th>Days</th><th>Waits for</th><th>People</th><th>Done</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""

    def refuse(url, *args, **kwargs):
        raise ValueError('The chart fetches nothing')
    return HTML(string=source, url_fetcher=refuse).write_pdf()


def task_ref(person: Person, task_id: str) -> dict:
    """Where a task is: its page and project (to open it from a section that names it)."""
    with connect() as conn:
        row = _task(conn, person, task_id)
        return {'id': row['id'], 'note_id': row['note_id'], 'project_id': row['project_id'], 'title': row['title']}


def workpackage_ref(person: Person, wp_id: str) -> dict:
    with connect() as conn:
        row = _wp(conn, person, wp_id)
        return {'id': row['id'], 'project_id': row['project_id'], 'title': row['title']}


def taggable(person: Person, query: str = '') -> List[dict]:
    """The tasks of their projects whose title (or project, or work package) has all the words: for @."""
    words = [w.lower() for w in (query or '').split()][:6]
    found = []
    for p in pickable(person):
        for w in p['workpackages']:
            for t in w['tasks']:
                where = f"{p['title']} › {w['title']}"
                if all(word in f"{t['title']} {where}".lower() for word in words):
                    found.append({**t, 'where': where})
    return found[:60]


def pickable(person: Person) -> List[dict]:
    """What they may put on a page: the work packages and tasks of their projects, in order."""
    with connect() as conn:
        projects = conn.execute(
            'SELECT p.* FROM projects p JOIN project_members m ON m.project_id = p.id WHERE m.username = ? '
            'AND p.deleted_at IS NULL ORDER BY p.title COLLATE NOCASE', (person.username,)).fetchall()
        found = []
        for p in projects:
            wps = conn.execute('SELECT * FROM workpackages WHERE project_id = ? AND deleted_at IS NULL '
                               'ORDER BY position, created_at', (p['id'],)).fetchall()
            tasks = conn.execute('SELECT * FROM tasks WHERE project_id = ? AND deleted_at IS NULL '
                                 'ORDER BY position, created_at', (p['id'],)).fetchall()
            found.append({'id': p['id'], 'title': p['title'], 'workpackages': [
                {'id': w['id'], 'title': w['title'], 'tasks': [
                    {'id': t['id'], 'title': t['title'], 'parent_id': t['parent_id'], 'start': t['sched_start'],
                     'end': t['sched_end'], 'done_on': t['done_on']} for t in tasks if t['wp_id'] == w['id']]}
                for w in wps]})
    return found


def section(person: Person, kind: str, target_id: str) -> dict:
    """A task or work package as a section to put on a page: what is written in it is kept with it."""
    with connect() as conn:
        if kind == 'task':
            row = _task(conn, person, target_id)
            project = _project(conn, row['project_id'])
            name = f"{project['title']} › {conn.execute('SELECT title FROM workpackages WHERE id = ?', (row['wp_id'],)).fetchone()['title']}"
        elif kind == 'workpackage':
            row = _wp(conn, person, target_id)
            project = _project(conn, row['project_id'])
            name = project['title']
        else:
            raise ValueError('Put a task or a work package on the page')
    return {'id': content_mod.new_id(), 'type': 'section', 'title': row['title'],
            'source': {'kind': kind, 'id': target_id, 'version': None, 'name': name},
            'blocks': [{'id': content_mod.new_id(), 'type': 'text', 'html': ''}]}
