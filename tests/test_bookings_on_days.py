"""A day's bookings from the Booking tool: live, kept once the day is over, notes on them, in exports."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

AMS = ZoneInfo('Europe/Amsterdam')

# The parts of the Booking tool's database the notebook reads.
BOOKING_SCHEMA = """
CREATE TABLE resources (id TEXT PRIMARY KEY, name TEXT, kind TEXT, location TEXT, colour TEXT);
CREATE TABLE bookings (id TEXT PRIMARY KEY, resource_id TEXT, starts_at TEXT, ends_at TEXT, title TEXT,
    notes TEXT DEFAULT '', kind TEXT DEFAULT 'booking', status TEXT DEFAULT 'confirmed', booked_by TEXT);
CREATE TABLE booking_people (booking_id TEXT, username TEXT);
INSERT INTO resources VALUES ('scope', 'Confocal', 'Microscope', 'Kruyt 2.14', '#7c3aed');
INSERT INTO resources VALUES ('room', 'Meeting room', 'Meeting room', '', '#2563eb');
"""


def utc(day, hhmm):
    h, m = map(int, hhmm.split(':'))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=AMS).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@pytest.fixture()
def booking_db(world, monkeypatch, tmp_path):
    path = tmp_path / 'booking.db'
    conn = sqlite3.connect(path)
    conn.executescript(BOOKING_SCHEMA)
    conn.commit()
    conn.close()
    monkeypatch.setenv('BOOKING_DATABASE_PATH', str(path))
    monkeypatch.setenv('TZ', 'Europe/Amsterdam')

    def add(id_, resource, day, start, end, by, people=(), title='', status='confirmed', kind='booking'):
        c = sqlite3.connect(path)
        c.execute('INSERT INTO bookings (id, resource_id, starts_at, ends_at, title, kind, status, booked_by) '
                  'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (id_, resource, utc(day, start), utc(day, end), title, kind, status, by))
        c.executemany('INSERT INTO booking_people VALUES (?, ?)', [(id_, p) for p in people])
        c.commit()
        c.close()

    def run(sql, *args):
        c = sqlite3.connect(path)
        c.execute(sql, args)
        c.commit()
        c.close()
    return {'add': add, 'run': run}


def day_note(client, day):
    note = client.post('/api/days', json={'date': day.isoformat()}).get_json()['note']
    return client.get(f"/api/notes/{note['id']}").get_json()['note']


def test_a_day_shows_their_bookings_and_those_they_are_in(as_user, booking_db):
    today = datetime.now(AMS).date()
    add = booking_db['add']
    add('b1', 'scope', today, '09:00', '11:00', 'ana', title='GFP imaging')
    add('b2', 'room', today, '13:00', '14:00', 'ben', people=['ana', 'zoe'], title='Project meeting')
    add('b3', 'room', today, '15:00', '16:00', 'ben')                                   # not hers
    add('b4', 'scope', today, '16:00', '17:00', 'ana', status='cancelled')
    add('b5', 'scope', today, '17:00', '18:00', 'lead', kind='closed')
    add('b6', 'scope', today + timedelta(days=2), '10:00', '12:00', 'ana')
    note = day_note(as_user('ana'), today)
    items = note['bookings']['items']
    assert [b['id'] for b in items] == ['b1', 'b2']
    assert items[0]['role'] == 'booked' and items[0]['resource']['name'] == 'Confocal'
    assert items[1]['role'] == 'tagged' and items[1]['people'] == ['ana', 'zoe']
    assert note['bookings']['live'] and note['bookings']['link'] == '/booking'
    assert [b['id'] for b in note['bookings']['upcoming']] == ['b6']
    # Another day: not today, nothing coming up shown.
    assert day_note(as_user('ana'), today + timedelta(days=2))['bookings']['upcoming'] == []
    # Others' pages are theirs: ben's day has his meeting and his own room booking.
    assert [b['id'] for b in day_note(as_user('ben'), today)['bookings']['items']] == ['b2', 'b3']


def test_ahead_it_follows_the_booking_tool(as_user, booking_db):
    ahead = datetime.now(AMS).date() + timedelta(days=3)
    booking_db['add']('b1', 'scope', ahead, '09:00', '10:00', 'ana')
    ana = as_user('ana')
    assert [b['id'] for b in day_note(ana, ahead)['bookings']['items']] == ['b1']
    booking_db['run']("UPDATE bookings SET starts_at = ?, ends_at = ? WHERE id = 'b1'",
                      utc(ahead + timedelta(days=1), '09:00'), utc(ahead + timedelta(days=1), '10:00'))
    assert day_note(ana, ahead)['bookings']['items'] == []
    assert [b['id'] for b in day_note(ana, ahead + timedelta(days=1))['bookings']['items']] == ['b1']


def test_once_the_day_is_over_it_is_kept_as_it_stood(as_user, booking_db):
    before = datetime.now(AMS).date() - timedelta(days=2)
    booking_db['add']('b1', 'scope', before, '09:00', '10:00', 'ana', title='Imaging')
    ana = as_user('ana')
    first = day_note(ana, before)['bookings']
    assert [b['id'] for b in first['items']] == ['b1'] and not first['live']
    # Changed or cancelled in the Booking tool afterwards: the day keeps what it was.
    booking_db['run']("UPDATE bookings SET status = 'cancelled', title = 'Changed' WHERE id = 'b1'")
    kept = day_note(ana, before)['bookings']['items']
    assert [(b['id'], b['title']) for b in kept] == [('b1', 'Imaging')]


def test_what_was_done_is_written_under_a_booking(as_user, booking_db):
    today = datetime.now(AMS).date()
    booking_db['add']('b1', 'scope', today, '09:00', '11:00', 'ana')
    ana = as_user('ana')
    note = day_note(ana, today)
    res = ana.put(f"/api/notes/{note['id']}/bookings/b1", json={'text': 'Imaged 12 seedlings, 488 nm at 4%'})
    assert res.status_code == 200
    assert day_note(ana, today)['bookings']['items'][0]['notes'] == 'Imaged 12 seedlings, 488 nm at 4%'
    # Only on this day's bookings, and only by whoever may change the day.
    assert ana.put(f"/api/notes/{note['id']}/bookings/nope", json={'text': 'x'}).status_code == 404
    assert as_user('lead').put(f"/api/notes/{note['id']}/bookings/b1", json={'text': 'x'}).status_code == 403
    ana.put(f"/api/notes/{note['id']}/bookings/b1", json={'text': ''})
    assert day_note(ana, today)['bookings']['items'][0]['notes'] == ''


def test_exports_print_a_days_bookings(as_user, booking_db):
    from app import exporting, people
    today = datetime.now(AMS).date()
    booking_db['add']('b1', 'scope', today, '09:00', '11:00', 'ana', title='GFP <imaging>', people=['zoe'])
    ana = as_user('ana')
    note = day_note(ana, today)
    ana.put(f"/api/notes/{note['id']}/bookings/b1", json={'text': 'All fine'})
    ctx = exporting.collect(people.Person(username='ana'), note['id'])
    first = ctx.entries[0].content[0]
    assert first['type'] == 'text' and first['html'].startswith('<h3>Bookings</h3>')
    assert '09:00–11:00' in first['html'] and 'Confocal' in first['html'] and 'GFP &lt;imaging&gt;' in first['html']
    assert 'with zoe' in first['html'] and 'All fine' in first['html']


def test_without_the_booking_tool_days_are_as_before(as_user, monkeypatch, tmp_path):
    monkeypatch.setenv('BOOKING_DATABASE_PATH', str(tmp_path / 'none.db'))
    note = day_note(as_user('ana'), date(2026, 1, 5))
    assert note['bookings'] == {'items': [], 'live': False, 'link': '/booking', 'upcoming': []}


def test_a_booking_gives_its_day_a_page(as_user, booking_db):
    today = datetime.now(AMS).date()
    add = booking_db['add']
    add('b1', 'scope', today + timedelta(days=4), '09:00', '11:00', 'ana')
    add('b2', 'room', today + timedelta(days=6), '13:00', '14:00', 'ben', people=['ana'])
    add('b3', 'room', today + timedelta(days=8), '13:00', '14:00', 'ana', status='cancelled')
    add('b4', 'room', today + timedelta(days=9), '13:00', '14:00', 'ben')                 # not hers
    ana = as_user('ana')

    assert ana.get('/api/me').status_code == 200
    from app import db
    with db.connect() as conn:
        rows = conn.execute("SELECT a.value FROM attributes a JOIN notes n ON n.id = a.note_id "
                            "WHERE a.name = 'dateNote' AND n.owner = 'ana' AND n.deleted_at IS NULL").fetchall()
    have = {r['value'] for r in rows}
    assert (today + timedelta(days=4)).isoformat() in have and (today + timedelta(days=6)).isoformat() in have
    assert (today + timedelta(days=8)).isoformat() not in have and (today + timedelta(days=9)).isoformat() not in have
    # Again: the same pages, no second ones.
    ana.get('/api/me')
    with db.connect() as conn:
        again = conn.execute("SELECT count(*) AS n FROM attributes a JOIN notes n ON n.id = a.note_id "
                             "WHERE a.name = 'dateNote' AND n.owner = 'ana' AND n.deleted_at IS NULL").fetchone()['n']
    assert again == len(rows)
    # The page shows the booking.
    note = day_note(ana, today + timedelta(days=4))
    assert [b['id'] for b in note['bookings']['items']] == ['b1']


def leaves(world, username, when='2000-01-01T00:00:00Z'):
    conn = sqlite3.connect(world['paths']['suite'])
    conn.execute('CREATE TABLE IF NOT EXISTS archived (username TEXT PRIMARY KEY, archived_at TEXT, archived_by TEXT)')
    conn.execute('INSERT INTO archived VALUES (?, ?, ?)', (username, when, 'lead'))
    conn.commit()
    conn.close()


def test_someone_who_left_keeps_their_notebook_for_the_lab(as_user, booking_db, world):
    ana = as_user('ana')
    ana.post('/api/days', json={'date': '2026-10-15'})
    leaves(world, 'ana')
    # Their lab lead still opens it, marked as theirs who left; they are not offered to share with.
    others = as_user('lead').get('/api/me').get_json()['others']
    mine = next(nb for nb in others if nb['owner'] == 'ana')
    assert mine['archived'] is True
    from app import people
    assert 'ana' not in people.people() and 'ana' not in people.colleagues('ben')
    # Their bookings ahead are freed: not on the days of those they tagged.
    ahead = datetime.now(AMS).date() + timedelta(days=3)
    booking_db['add']('b1', 'room', ahead, '10:00', '11:00', 'ana', people=['ben'])
    assert day_note(as_user('ben'), ahead)['bookings']['items'] == []
