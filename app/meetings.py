"""
Meetings: scheduled once or recurring, each meeting a page under the day it falls on.

A meeting is set up by someone (its organiser) in their own notebook, with a title, a time, where,
an agenda, how often it repeats (once, every week, every two or four weeks, or monthly on the same
weekday, e.g. the second Tuesday) and the people invited. Its dates of this week and next get a page
each (type ``meeting``), made the first time anyone invited opens their notebook, like the week's
to-do list: the page sits under the day page of the organiser and of everyone invited, and is shared
with those invited, so it is one page that all of them read and take notes on together. It stays in the
organiser's notebook. Anyone with an account in Trellis Tools may be invited, whatever their lab; only
the organiser changes the meeting itself (its time, place, agenda, repeats and who is invited).

A meeting's page holds its agenda, an attendance list (one line per person, ticked as present, by
whom and when), notes, and action items (a task list, whose tasks may link with @ as the to-do
list's do).

Changing a meeting changes its pages to come (from today on): one nobody has written on yet is made
again as the meeting now is; one already written on keeps what was written, and gets the new title
and the people added or taken off. Pages of days gone by are kept as they were. Ending a meeting
stops it after today. One date is skipped by deleting its page: it is not made again (it comes back
from Deleted like any page).

A repeating meeting's action items not ticked off are carried over to its next meeting's page, as the
to-do list moves a task on: once a meeting's day is over, its open action items go onto the next page
made (each time that page is opened, so what is added later to the earlier page follows too), marked with
the meeting they came from; on the earlier page they stay, marked as carried. Still open there, they are
carried on again to the one after. Not on the meeting's own day: the earlier page is then being written on,
and changing it under the people at the meeting would make their saves clash.
"""

import json
from datetime import date, timedelta
from html import escape
from typing import Iterable, List, Optional

from app import bookings as bookings_mod
from app import content as content_mod
from app import notes
from app import people as people_mod
from app.db import connect
from app.people import Person

MEETING_TYPE = 'meeting'
REPEATS = {'none': 'Once', 'weekly': 'Every week', 'fortnightly': 'Every two weeks',
           'four-weekly': 'Every four weeks', 'monthly': 'Every month, on the same weekday'}
MAX_PEOPLE = 60
# Pages are made for this week and the next.
WEEKS_AHEAD = 2
_ORDINALS = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'last'}


def today() -> date:
    return bookings_mod.today()


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# --- when it meets -------------------------------------------------------------------

def _nth(day: date) -> int:
    """Which of its weekday in the month a day is: 1 for the first, ... 5 for the last."""
    n = (day.day - 1) // 7 + 1
    return 5 if n >= 5 or (day + timedelta(days=7)).month != day.month else n


def _monthly(first: date, month_start: date) -> Optional[date]:
    """The day in this month on the same weekday, as the first date is (the second Tuesday, the last Friday)."""
    n = _nth(first)
    d = month_start + timedelta(days=(first.weekday() - month_start.weekday()) % 7)
    if n == 5:
        while (d + timedelta(days=7)).month == month_start.month:
            d += timedelta(days=7)
        return d
    d += timedelta(days=7 * (n - 1))
    return d if d.month == month_start.month else None


def dates_between(meeting, start: date, end: date) -> List[date]:
    """The dates a meeting falls on from start to end, both included."""
    first = date.fromisoformat(meeting['starts_on'])
    last = min(end, date.fromisoformat(meeting['until'])) if meeting['until'] else end
    start = max(start, first)
    if start > last:
        return []
    repeat = meeting['repeat']
    if repeat == 'none':
        return [first] if start <= first <= last else []
    if repeat == 'monthly':
        found, month = [], date(start.year, start.month, 1)
        while month <= last:
            d = _monthly(first, month)
            if d and start <= d <= last:
                found.append(d)
            month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        return found
    step = {'weekly': 7, 'fortnightly': 14, 'four-weekly': 28}[repeat]
    d = first + timedelta(days=-(-(start - first).days // step) * step)
    found = []
    while d <= last:
        found.append(d)
        d += timedelta(days=step)
    return found


def repeat_label(meeting) -> str:
    first = date.fromisoformat(meeting['starts_on'])
    weekday = first.strftime('%A')
    label = {'none': f"Once, {first.strftime('%d-%m-%Y')}",
             'weekly': f'Every {weekday}',
             'fortnightly': f'Every other {weekday}',
             'four-weekly': f'Every fourth {weekday}',
             'monthly': f'The {_ORDINALS[_nth(first)]} {weekday} of every month'}[meeting['repeat']]
    if meeting['repeat'] != 'none' and meeting['until']:
        label += f", until {date.fromisoformat(meeting['until']).strftime('%d-%m-%Y')}"
    return label


# --- reading ----------------------------------------------------------------------------

def _people(conn, meeting_id: str) -> List[str]:
    return [r['username'] for r in conn.execute(
        'SELECT username FROM meeting_people WHERE meeting_id = ? ORDER BY username COLLATE NOCASE', (meeting_id,))]


def _row(conn, meeting_id: str):
    row = conn.execute('SELECT * FROM meetings WHERE id = ?', (meeting_id,)).fetchone()
    if row is None:
        raise notes.NotFound('No such meeting')
    return row


def _involves(conn, person: Person, row) -> bool:
    return row['owner'] == person.username or person.username in _people(conn, row['id'])


def _summary(conn, person: Person, row, names=None) -> dict:
    invited = _people(conn, row['id'])
    upcoming = dates_between(row, today(), today() + timedelta(days=400))
    return {'id': row['id'], 'title': row['title'], 'owner': row['owner'],
            'starts_on': row['starts_on'], 'until': row['until'], 'repeat': row['repeat'],
            'start_time': row['start_time'], 'end_time': row['end_time'], 'location': row['location'],
            'agenda': row['agenda'], 'people': invited, 'when': repeat_label(row),
            'next': upcoming[0].isoformat() if upcoming else None, 'ended': bool(row['ended_at']),
            'can_edit': row['owner'] == person.username}


def mine(person: Person) -> List[dict]:
    """The meetings they organise or are invited to: those still to come first, by their next date."""
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM meetings WHERE owner = ? OR id IN (SELECT meeting_id FROM meeting_people WHERE username = ?) '
            'ORDER BY title COLLATE NOCASE', (person.username, person.username)).fetchall()
        found = [_summary(conn, person, r) for r in rows]
    return sorted(found, key=lambda m: (m['next'] is None, m['next'] or '', m['start_time']))


def get(person: Person, meeting_id: str) -> dict:
    with connect() as conn:
        row = _row(conn, meeting_id)
        if not _involves(conn, person, row) and not person.oversees(row['owner']):
            raise notes.Forbidden('You are not invited to this meeting')
        return _summary(conn, person, row)


def for_note(conn, person: Person, note_id: str) -> Optional[dict]:
    """The meeting a meeting page is of, and its date, to show at the top of the page."""
    found = conn.execute('SELECT m.*, d.day FROM meeting_dates d JOIN meetings m ON m.id = d.meeting_id '
                         'WHERE d.note_id = ?', (note_id,)).fetchone()
    if not found:
        return None
    return {**_summary(conn, person, found), 'date': found['day']}


# --- checking what is asked -------------------------------------------------------------

def _time(value) -> str:
    text = str(value or '').strip()
    try:
        hours, minutes = text.split(':')
        h, m = int(hours), int(minutes)
    except ValueError:
        raise ValueError('Give times as HH:MM, e.g. 14:00')
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError('Give times as HH:MM, e.g. 14:00')
    return f'{h:02d}:{m:02d}'


def _day(value, what: str) -> date:
    try:
        return date.fromisoformat(str(value or '').strip())
    except ValueError:
        raise ValueError(f'{what} must be a date (YYYY-MM-DD)')


def _clean(person: Person, data: dict, owner: str) -> dict:
    title = ' '.join(str(data.get('title') or '').split())[:120]
    if not title:
        raise ValueError('Give the meeting a title')
    starts_on = _day(data.get('starts_on'), 'The first date')
    repeat = str(data.get('repeat') or 'none')
    if repeat not in REPEATS:
        raise ValueError(f"Repeat must be one of {', '.join(REPEATS)}")
    until = _day(data.get('until'), 'The last date') if data.get('until') and repeat != 'none' else None
    if until and until < starts_on:
        raise ValueError('The last date is before the first')
    start_time, end_time = _time(data.get('start_time')), _time(data.get('end_time'))
    if end_time <= start_time:
        raise ValueError('The meeting ends before it starts')
    asked = data.get('people') or []
    if not isinstance(asked, list):
        raise ValueError('people must be a list of usernames')
    allowed = set(invitable(person, owner))
    invited = []
    for u in asked:
        u = str(u or '').strip()
        if not u or u == owner or u in invited:
            continue
        if u not in allowed:
            raise ValueError(f'No one called {u} has an account in Trellis Tools')
        invited.append(u)
    if len(invited) > MAX_PEOPLE:
        raise ValueError(f'At most {MAX_PEOPLE} people')
    return {'title': title, 'starts_on': starts_on.isoformat(), 'until': until.isoformat() if until else None,
            'repeat': repeat, 'start_time': start_time, 'end_time': end_time,
            'location': ' '.join(str(data.get('location') or '').split())[:200],
            'agenda': content_mod.clean_html(data.get('agenda') or '')[:20000], 'people': invited}


def invitable(person: Person, owner: Optional[str] = None) -> List[str]:
    """Whom a meeting may be shared with: anyone with an account in Trellis Tools, whatever their lab (in the
    teaching demo, the demo's people), but the organiser and those who have left."""
    owner = owner or person.username
    return [u for u in people_mod.people_for(person) if u != owner]


# --- its pages ----------------------------------------------------------------------------

def _title(meeting) -> str:
    return f"{meeting['title']} · {meeting['start_time']}"


def _blocks(meeting, everyone: Iterable[str], names) -> List[dict]:
    agenda = meeting['agenda'] or ''
    return [
        {'type': 'text', 'html': '<h3>Agenda</h3>' + (agenda or '<p></p>')},
        {'type': 'steps', 'title': 'Attendance',
         'items': [{'id': content_mod.new_id(), 'html': escape(people_mod.shown(u, names))} for u in everyone]},
        {'type': 'text', 'html': '<h3>Notes</h3><p></p>'},
        {'type': 'tasks', 'title': 'Action items', 'items': []},
    ]


def _place(conn, note_id: str, day_id: str) -> None:
    """Under a day page, after what is there."""
    if conn.execute('SELECT 1 FROM branches WHERE note_id = ? AND parent_id = ?', (note_id, day_id)).fetchone():
        return
    position = conn.execute('SELECT COALESCE(MAX(position), 0) + 10 FROM branches WHERE parent_id = ?',
                            (day_id,)).fetchone()[0]
    conn.execute('INSERT INTO branches (id, note_id, parent_id, position) VALUES (?, ?, ?, ?)',
                 (content_mod.new_id(), note_id, day_id, position))


def _share(conn, note_id: str, username: str, by: str) -> None:
    conn.execute("INSERT OR IGNORE INTO shares (id, note_id, target_type, target, created_by) VALUES (?, ?, 'person', ?, ?)",
                 (content_mod.new_id() + content_mod.new_id(), note_id, username, by))


def _unplace(conn, note_id: str, username: str) -> None:
    """Off the day pages of someone no longer invited, and no longer shared with them."""
    conn.execute("DELETE FROM shares WHERE note_id = ? AND target_type = 'person' AND target = ?", (note_id, username))
    conn.execute('DELETE FROM branches WHERE note_id = ? AND parent_id IN (SELECT id FROM notes WHERE owner = ?)',
                 (note_id, username))


def _make_pages(meeting_ids: Iterable[str], start: date, end: date) -> None:
    """The pages of these meetings' dates from start to end that have none yet."""
    gone = people_mod.archived()
    names = people_mod.display_names()
    for meeting_id in meeting_ids:
        with connect() as conn:
            meeting = _row(conn, meeting_id)
            invited = [u for u in _people(conn, meeting_id) if u not in gone]
            made = {r['day'] for r in conn.execute('SELECT day FROM meeting_dates WHERE meeting_id = ?', (meeting_id,))}
        if meeting['owner'] in gone:
            continue
        everyone = [meeting['owner'], *invited]
        for d in dates_between(meeting, start, end):
            if d.isoformat() in made:
                continue
            # The day pages first: each is made in a transaction of its own.
            days = {u: notes.day_for(u, d) for u in everyone}
            with connect() as conn:
                claimed = conn.execute('INSERT OR IGNORE INTO meeting_dates (meeting_id, day) VALUES (?, ?)',
                                       (meeting_id, d.isoformat())).rowcount
                if not claimed:
                    continue            # made meanwhile by someone else's visit
                blocks = content_mod.clean_blocks(_blocks(meeting, everyone, names), username=meeting['owner'])
                note_id = notes._create(conn, title=_title(meeting), type=MEETING_TYPE, space='notebook',
                                        owner=meeting['owner'], by=meeting['owner'], content=blocks)
                notes._label(conn, note_id, 'meetingDate', d.isoformat())
                conn.execute('UPDATE meeting_dates SET note_id = ? WHERE meeting_id = ? AND day = ?',
                             (note_id, meeting_id, d.isoformat()))
                for u in everyone:
                    _place(conn, note_id, days[u])
                    if u != meeting['owner']:
                        _share(conn, note_id, u, meeting['owner'])
    notes._forget_shares()


def _window() -> tuple:
    start = monday(today())
    return start, start + timedelta(days=7 * WEEKS_AHEAD - 1)


def pages_for(person: Person) -> None:
    """The pages of this week's and next week's meetings they organise or are invited to: before the notebook shows."""
    with connect() as conn:
        ids = [r['id'] for r in conn.execute(
            'SELECT id FROM meetings WHERE ended_at IS NULL AND (owner = ? OR id IN '
            '(SELECT meeting_id FROM meeting_people WHERE username = ?))', (person.username, person.username))]
    if ids:
        _make_pages(ids, *_window())


# --- setting up and changing -------------------------------------------------------------

def create(person: Person, data: dict) -> dict:
    meeting = _clean(person, data, person.username)
    meeting_id = content_mod.new_id() + content_mod.new_id()
    with connect() as conn:
        conn.execute('INSERT INTO meetings (id, owner, title, starts_on, until, repeat, start_time, end_time, location, '
                     'agenda, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (meeting_id, person.username, meeting['title'], meeting['starts_on'], meeting['until'],
                      meeting['repeat'], meeting['start_time'], meeting['end_time'], meeting['location'],
                      meeting['agenda'], person.username))
        conn.executemany('INSERT INTO meeting_people (meeting_id, username) VALUES (?, ?)',
                         [(meeting_id, u) for u in meeting['people']])
    _make_pages([meeting_id], *_window())
    return get(person, meeting_id)


def _owned(conn, person: Person, meeting_id: str):
    row = _row(conn, meeting_id)
    if row['owner'] != person.username:
        raise notes.Forbidden('Only whoever set up the meeting changes it')
    return row


def _pages_to_come(conn, meeting_id: str):
    """This meeting's pages of today and later, not deleted, with whether anyone has written on them."""
    return conn.execute(
        'SELECT d.day, n.id, n.version, n.title, n.content FROM meeting_dates d JOIN notes n ON n.id = d.note_id '
        'WHERE d.meeting_id = ? AND d.day >= ? AND n.deleted_at IS NULL', (meeting_id, today().isoformat())).fetchall()


def _erase(conn, meeting_id: str, day: str, note_id: str) -> None:
    """A page nobody wrote on, gone without a trace, so it can be made again as the meeting now is."""
    for table, column in (('branches', 'note_id'), ('attributes', 'note_id'), ('revisions', 'note_id'),
                          ('shares', 'note_id'), ('links', 'note_id'), ('notes', 'id')):
        conn.execute(f'DELETE FROM {table} WHERE {column} = ?', (note_id,))
    conn.execute('DELETE FROM meeting_dates WHERE meeting_id = ? AND day = ?', (meeting_id, day))


def update(person: Person, meeting_id: str, data: dict) -> dict:
    with connect() as conn:
        before = _owned(conn, person, meeting_id)
        if before['ended_at']:
            raise ValueError('This meeting has ended')
        was = _people(conn, meeting_id)
    meeting = _clean(person, data, person.username)
    names = people_mod.display_names()
    with connect() as conn:
        conn.execute('UPDATE meetings SET title = ?, starts_on = ?, until = ?, repeat = ?, start_time = ?, end_time = ?, '
                     'location = ?, agenda = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                     (meeting['title'], meeting['starts_on'], meeting['until'], meeting['repeat'],
                      meeting['start_time'], meeting['end_time'], meeting['location'], meeting['agenda'], meeting_id))
        conn.execute('DELETE FROM meeting_people WHERE meeting_id = ?', (meeting_id,))
        conn.executemany('INSERT INTO meeting_people (meeting_id, username) VALUES (?, ?)',
                         [(meeting_id, u) for u in meeting['people']])
        now = _row(conn, meeting_id)
        added = [u for u in meeting['people'] if u not in was]
        dropped = [u for u in was if u not in meeting['people']]
        for page in _pages_to_come(conn, meeting_id):
            if page['version'] == 1:
                _erase(conn, meeting_id, page['day'], page['id'])
                continue
            _written_on(conn, person, page, now, added, dropped, names)
    _make_pages([meeting_id], *_window())
    return get(person, meeting_id)


def _written_on(conn, person: Person, page, meeting, added: List[str], dropped: List[str], names) -> None:
    """A page to come that someone has written on: the new title, and the people added or taken off."""
    for u in dropped:
        _unplace(conn, page['id'], u)
    for u in added:
        _place(conn, page['id'], notes.day_in(conn, u, date.fromisoformat(page['day'])))
        _share(conn, page['id'], u, meeting['owner'])
    blocks = json.loads(page['content'] or '[]')
    attendance = next((b for b in blocks if b.get('type') == 'steps' and b.get('title') == 'Attendance'), None)
    if attendance is not None and added:
        attendance['items'].extend({'id': content_mod.new_id(), 'html': escape(people_mod.shown(u, names)),
                                    'by': None, 'at': None} for u in added)
    title = _title(meeting)
    if title == page['title'] and not (attendance is not None and added):
        return
    body = json.dumps(blocks)
    number = notes._keep_revision(conn, page['id'], title, body, person.username, 'edited')
    conn.execute('UPDATE notes SET title = ?, content = ?, search_text = ?, revision = ?, version = version + 1, '
                 'updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 (title, body, content_mod.plain_text(blocks), number, person.username, page['id']))
    notes._forget_shares()


def end(person: Person, meeting_id: str) -> dict:
    """No more after today: its pages to come that nobody wrote on go; those written on stay."""
    with connect() as conn:
        row = _owned(conn, person, meeting_id)
        if row['ended_at']:
            raise ValueError('This meeting has ended already')
        last = today()
        until = row['until'] if row['until'] and row['until'] < last.isoformat() else last.isoformat()
        conn.execute('UPDATE meetings SET until = ?, ended_at = CURRENT_TIMESTAMP WHERE id = ?', (until, meeting_id))
        for page in _pages_to_come(conn, meeting_id):
            if page['day'] > until and page['version'] == 1:
                _erase(conn, meeting_id, page['day'], page['id'])
    notes._forget_shares()
    return get(person, meeting_id)


# --- action items carried over ------------------------------------------------------------

def _action_items(blocks: list) -> Optional[dict]:
    return next((b for b in blocks if isinstance(b, dict) and b.get('type') == 'tasks'), None)


def carry_over(note_id: str) -> int:
    """
    The open action items of this meeting's last page before this one, once its day is over, put on this page
    (and marked carried there). How many were carried.
    """
    with connect() as conn:
        here = conn.execute('SELECT d.meeting_id, d.day, m.owner FROM meeting_dates d JOIN meetings m ON m.id = d.meeting_id '
                            'WHERE d.note_id = ?', (note_id,)).fetchone()
        if not here:
            return 0
        source = conn.execute(
            'SELECT d.day, n.id, n.content, n.title FROM meeting_dates d JOIN notes n ON n.id = d.note_id '
            'WHERE d.meeting_id = ? AND d.day < ? AND n.deleted_at IS NULL ORDER BY d.day DESC LIMIT 1',
            (here['meeting_id'], here['day'])).fetchone()
        # The meeting just before, and only once its day is over: items step on one meeting at a time.
        if not source or source['day'] >= today().isoformat():
            return 0
        earlier = json.loads(source['content'] or '[]')
        block = _action_items(earlier)
        open_items = [i for i in (block or {}).get('items') or []
                      if not i.get('by') and not i.get('moved')
                      and content_mod.plain_text([{'type': 'tasks', 'items': [i]}]).strip()]
        if not open_items:
            return 0
        row = notes._row(conn, note_id)
        blocks = json.loads(row['content'] or '[]')
        target = _action_items(blocks)
        if target is None:
            target = {'id': content_mod.new_id(), 'type': 'tasks', 'title': 'Action items', 'items': []}
            blocks.append(target)
        already = {i.get('from_item') for i in target['items']}
        for item in open_items:
            item['moved'] = here['day']
            if item['id'] not in already:
                target['items'].append({'id': content_mod.new_id(), 'html': item['html'], 'by': None, 'at': None,
                                        'priority': content_mod.task_priority(item.get('priority')), 'moved': None,
                                        'from_item': item['id'], 'from_week': source['day']})
        content_mod.sort_tasks(target['items'])
        remark = f"Action items carried over from {date.fromisoformat(source['day']).strftime('%d-%m-%Y')}"
        for nid, title, content in ((source['id'], source['title'], earlier), (note_id, row['title'], blocks)):
            body = json.dumps(content)
            number = notes._keep_revision(conn, nid, title, body, here['owner'], 'carried', remark)
            conn.execute('UPDATE notes SET content = ?, search_text = ?, revision = ?, version = version + 1, '
                         'updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (body, content_mod.plain_text(content), number, nid))
            notes._index_links(conn, nid, content)
        return len(open_items)


# --- the week, as a schedule ---------------------------------------------------------------

def week(person: Person, start: date) -> dict:
    """
    The meetings they organise or are invited to in the week from this Monday, for the Meetings tab: each date
    with its time, where, who, and its page if made (a date whose page was deleted is shown as skipped).
    """
    start = monday(start)
    end = start + timedelta(days=6)
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM meetings WHERE owner = ? OR id IN (SELECT meeting_id FROM meeting_people WHERE username = ?)',
            (person.username, person.username)).fetchall()
        items = []
        for row in rows:
            made = {r['day']: r for r in conn.execute(
                'SELECT d.day, d.note_id, n.deleted_at FROM meeting_dates d LEFT JOIN notes n ON n.id = d.note_id '
                'WHERE d.meeting_id = ? AND d.day BETWEEN ? AND ?', (row['id'], start.isoformat(), end.isoformat()))}
            for d in dates_between(row, start, end):
                page = made.get(d.isoformat())
                items.append({**_summary(conn, person, row), 'date': d.isoformat(),
                              'note_id': page['note_id'] if page and not page['deleted_at'] else None,
                              'skipped': bool(page and (page['deleted_at'] or not page['note_id']))})
    items.sort(key=lambda m: (m['date'], m['start_time'], m['title'].lower()))
    return {'start': start.isoformat(), 'end': end.isoformat(), 'today': today().isoformat(), 'items': items}


def page_for(person: Person, meeting_id: str, day: date) -> str:
    """A date's page, made now if it is not yet (a date further ahead than next week, opened from the schedule)."""
    with connect() as conn:
        row = _row(conn, meeting_id)
        if not _involves(conn, person, row):
            raise notes.Forbidden('You are not invited to this meeting')
        if day not in dates_between(row, day, day):
            raise ValueError('The meeting does not fall on that date')
        found = conn.execute('SELECT d.note_id, n.deleted_at FROM meeting_dates d LEFT JOIN notes n ON n.id = d.note_id '
                             'WHERE d.meeting_id = ? AND d.day = ?', (meeting_id, day.isoformat())).fetchone()
    if found:
        if found['deleted_at'] or not found['note_id']:
            raise ValueError('That date was skipped: its page is in Deleted, to bring back')
        return found['note_id']
    _make_pages([meeting_id], day, day)
    with connect() as conn:
        return conn.execute('SELECT note_id FROM meeting_dates WHERE meeting_id = ? AND day = ?',
                            (meeting_id, day.isoformat())).fetchone()['note_id']
