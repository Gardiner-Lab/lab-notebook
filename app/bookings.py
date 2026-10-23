"""
Bookings from the Booking tool, on the day they are for.

A day's page shows the bookings of whoever the notebook belongs to that day:
those they made and those they are tagged in (a meeting, a colleague's
session at the microscope). They are read from the Booking tool's database,
read-only, so a booking moved or cancelled there moves or goes here too.

Once the day is over its bookings are kept here as they stood (the first time
the day is looked at or exported after it), so the notebook stays a record:
later changes in the Booking tool do not rewrite a day gone by. What someone
writes about a booking - what they actually did with the time - is the
notebook's, kept with the day.
"""

import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UPCOMING_DAYS = 7
UPCOMING_LIMIT = 8


def path() -> str:
    return os.environ.get('BOOKING_DATABASE_PATH', '/booking/booking.db')


def link_base() -> str:
    return os.environ.get('BOOKING_URL', '/booking').rstrip('/')


def zone() -> ZoneInfo:
    try:
        return ZoneInfo((os.environ.get('TZ') or 'Europe/Amsterdam').lstrip(':'))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('Europe/Amsterdam')


def today() -> date:
    return datetime.now(zone()).date()


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _read(sql: str, args=()) -> List[sqlite3.Row]:
    if not os.path.exists(path()):
        return []
    try:
        conn = sqlite3.connect(f'file:{path()}?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _between(username: str, start: datetime, end: datetime, limit: int = 200) -> List[dict]:
    """Their bookings (made, or tagged in) running at some time between two times, earliest first."""
    rows = _read(
        "SELECT b.*, r.name AS r_name, r.kind AS r_kind, r.location AS r_location, r.colour AS r_colour "
        "FROM bookings b JOIN resources r ON r.id = b.resource_id "
        "WHERE b.status != 'cancelled' AND b.kind = 'booking' AND b.starts_at < ? AND b.ends_at > ? "
        "AND (b.booked_by = ? OR EXISTS (SELECT 1 FROM booking_people p WHERE p.booking_id = b.id AND p.username = ?)) "
        "ORDER BY b.starts_at LIMIT ?", (_utc(end), _utc(start), username, username, limit))
    if not rows:
        return []
    ids = [r['id'] for r in rows]
    people = {i: [] for i in ids}
    for p in _read(f"SELECT booking_id, username FROM booking_people WHERE booking_id IN ({', '.join('?' * len(ids))}) "
                   "ORDER BY username COLLATE NOCASE", ids):
        people[p['booking_id']].append(p['username'])
    return [{'id': r['id'], 'start': r['starts_at'], 'end': r['ends_at'], 'title': r['title'],
             'booked_by': r['booked_by'], 'people': people[r['id']],
             'role': 'booked' if r['booked_by'] == username else 'tagged',
             'resource': {'id': r['resource_id'], 'name': r['r_name'], 'kind': r['r_kind'],
                          'location': r['r_location'], 'colour': r['r_colour']}} for r in rows]


def day_bounds(day: date):
    tz = zone()
    return (datetime.combine(day, time(0), tzinfo=tz), datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz))


def for_day(username: str, day: date) -> List[dict]:
    return _between(username, *day_bounds(day))


def upcoming(username: str, after: date) -> List[dict]:
    """Their next bookings, in the days after this one, for today's page."""
    start = day_bounds(after + timedelta(days=1))[0]
    return _between(username, start, start + timedelta(days=UPCOMING_DAYS), UPCOMING_LIMIT)


# Days with bookings get a page: from a month back to three months ahead.
PAGES_BACK_DAYS = 31
PAGES_AHEAD_DAYS = 92
MAX_PAGES = 120


def booked_days(username: str) -> List[date]:
    """The days they have a booking on (made, or tagged in), from a month back to three months ahead."""
    now_day = today()
    start = day_bounds(now_day - timedelta(days=PAGES_BACK_DAYS))[0]
    end = day_bounds(now_day + timedelta(days=PAGES_AHEAD_DAYS))[1]
    tz = zone()
    days = set()
    for b in _between(username, start, end, limit=1000):
        first = datetime.strptime(b['start'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(tz)
        last = datetime.strptime(b['end'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(tz) - timedelta(seconds=1)
        d = max(first.date(), start.astimezone(tz).date())
        while d <= min(last.date(), end.astimezone(tz).date()) and len(days) < MAX_PAGES:
            days.add(d)
            d += timedelta(days=1)
    return sorted(days)


# --- kept with the day ------------------------------------------------------------

def on_day(conn, note_id: str, username: str, day: date) -> dict:
    """
    The day's bookings: live while the day is today or ahead, kept as they
    stood once it is over; with what was written about each, and for today the
    bookings coming up.
    """
    now_day = today()
    frozen = conn.execute('SELECT bookings FROM day_bookings WHERE note_id = ?', (note_id,)).fetchone()
    if frozen is not None:
        items, live = json.loads(frozen['bookings']), False
    else:
        items, live = for_day(username, day), day >= now_day
        if not live and os.path.exists(path()):
            conn.execute('INSERT OR IGNORE INTO day_bookings (note_id, day, bookings) VALUES (?, ?, ?)',
                         (note_id, day.isoformat(), json.dumps(items)))
    written = {r['booking_id']: r['text'] for r in conn.execute(
        'SELECT booking_id, text FROM booking_notes WHERE note_id = ?', (note_id,))}
    for item in items:
        item['notes'] = written.get(item['id'], '')
    return {'items': items, 'live': live, 'link': link_base(),
            'upcoming': upcoming(username, day) if day == now_day else []}


def write_note(conn, note_id: str, booking_id: str, text: str, by: str) -> None:
    text = (text or '').strip()[:4000]
    if text:
        conn.execute('INSERT INTO booking_notes (note_id, booking_id, text, updated_by) VALUES (?, ?, ?, ?) '
                     'ON CONFLICT(note_id, booking_id) DO UPDATE SET text = excluded.text, updated_by = excluded.updated_by, '
                     'updated_at = CURRENT_TIMESTAMP', (note_id, booking_id, text, by))
    else:
        conn.execute('DELETE FROM booking_notes WHERE note_id = ? AND booking_id = ?', (note_id, booking_id))


def local_span(item: dict) -> str:
    """'09:00–11:00', or with the days when it runs over more than one."""
    tz = zone()
    s = datetime.strptime(item['start'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(tz)
    e = datetime.strptime(item['end'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).astimezone(tz)
    if s.date() == e.date() or (e - s <= timedelta(days=1) and e.time() == time(0)):
        return f"{s:%H:%M}–{'24:00' if e.time() == time(0) and e.date() != s.date() else f'{e:%H:%M}'}"
    return f'{s:%d %b %H:%M} – {e:%d %b %H:%M}'
