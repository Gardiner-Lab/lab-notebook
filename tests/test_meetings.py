"""Meetings: once or repeating, a page under the day of everyone invited, shared with them (app/meetings.py)."""
from datetime import date, timedelta

import pytest

from app import meetings

TODAY = date(2026, 11, 25)              # a Wednesday; this week starts Monday 23-11-2026
MONDAY = date(2026, 11, 23)


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    monkeypatch.setattr(meetings, 'today', lambda: TODAY)


def _meeting(client, **changes):
    data = {'title': 'Lab meeting', 'starts_on': MONDAY.isoformat(), 'repeat': 'weekly',
            'start_time': '14:00', 'end_time': '15:00', 'location': 'Room 2.12',
            'agenda': '<p>Updates</p>', 'people': ['ben'], **changes}
    r = client.post('/api/meetings', json=data)
    assert r.status_code == 201, r.get_json()
    return r.get_json()['meeting']


def _day(client, when):
    return client.post('/api/days', json={'date': when.isoformat()}).get_json()['note']


def _children(client, note_id):
    return client.get(f'/api/notes/{note_id}/children').get_json()['children']


def _meeting_pages(client, when):
    return [c for c in _children(client, _day(client, when)['id']) if c['type'] == 'meeting']


def _get(client, note_id):
    r = client.get(f'/api/notes/{note_id}')
    assert r.status_code == 200, r.get_json()
    return r.get_json()['note']


def test_dates_of_each_kind_of_repeat():
    def on(repeat, first, start, end, until=None):
        row = {'starts_on': first.isoformat(), 'until': until and until.isoformat(), 'repeat': repeat}
        return meetings.dates_between(row, start, end)
    jan = date(2027, 1, 1)
    assert on('none', date(2027, 1, 5), jan, date(2027, 3, 1)) == [date(2027, 1, 5)]
    assert on('weekly', date(2027, 1, 5), date(2027, 1, 10), date(2027, 1, 26)) == [
        date(2027, 1, 12), date(2027, 1, 19), date(2027, 1, 26)]
    assert on('fortnightly', date(2027, 1, 5), jan, date(2027, 2, 10)) == [
        date(2027, 1, 5), date(2027, 1, 19), date(2027, 2, 2)]
    assert on('four-weekly', date(2027, 1, 5), jan, date(2027, 3, 31)) == [
        date(2027, 1, 5), date(2027, 2, 2), date(2027, 3, 2), date(2027, 3, 30)]
    # The second Tuesday of every month; the last Friday of every month.
    assert on('monthly', date(2027, 1, 12), jan, date(2027, 4, 30)) == [
        date(2027, 1, 12), date(2027, 2, 9), date(2027, 3, 9), date(2027, 4, 13)]
    assert on('monthly', date(2027, 1, 29), jan, date(2027, 4, 30)) == [
        date(2027, 1, 29), date(2027, 2, 26), date(2027, 3, 26), date(2027, 4, 30)]
    # Until a last date.
    assert on('weekly', date(2027, 1, 5), jan, date(2027, 3, 1), until=date(2027, 1, 19)) == [
        date(2027, 1, 5), date(2027, 1, 12), date(2027, 1, 19)]


def test_a_weekly_meeting_is_a_page_under_this_and_next_weeks_days_of_everyone(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    m = _meeting(ana)
    assert m['when'] == 'Every Monday' and m['next'] == (MONDAY + timedelta(days=7)).isoformat()
    for when in (MONDAY, MONDAY + timedelta(days=7)):
        mine, theirs = _meeting_pages(ana, when), _meeting_pages(ben, when)
        assert len(mine) == 1 and [p['id'] for p in theirs] == [mine[0]['id']]
        assert mine[0]['title'] == 'Lab meeting · 14:00'
    # Not the week after: that comes when the weeks move on.
    assert _meeting_pages(ana, MONDAY + timedelta(days=14)) == []
    page = _get(ben, _meeting_pages(ben, MONDAY)[0]['id'])
    assert page['owner'] == 'ana' and page['can_edit'] and not page['can_delete']
    assert page['meeting']['date'] == MONDAY.isoformat() and page['meeting']['people'] == ['ben']
    assert page['meeting']['location'] == 'Room 2.12' and not page['meeting']['can_edit']
    kinds = [(b['type'], b.get('title')) for b in page['content']]
    assert kinds == [('text', None), ('steps', 'Attendance'), ('text', None), ('tasks', 'Action items')]
    assert 'Updates' in page['content'][0]['html']
    assert [i['html'] for i in page['content'][1]['items']] == ['ana', 'ben']
    # Ben writes on it, ticks himself present, and adds an action item: ana sees it.
    page['content'][1]['items'][1]['done'] = True
    page['content'][3]['items'] = [{'id': 'a1', 'html': 'Order primers'}]
    r = ben.put(f"/api/notes/{page['id']}", json={'content': page['content'], 'title': 'Renamed',
                                                  'base_version': page['version']})
    assert r.status_code == 200, r.get_json()
    seen = _get(ana, page['id'])
    assert seen['title'] == 'Lab meeting · 14:00'        # named by its meeting
    assert seen['content'][1]['items'][1]['by'] == 'ben'
    assert seen['content'][3]['items'][0]['html'] == 'Order primers'


def test_pages_are_made_when_someone_invited_opens_their_notebook(as_user, monkeypatch):
    ana, ben = as_user('ana'), as_user('ben')
    _meeting(ana)
    # A week later: the week after next gets its page when ben (not ana) opens his notebook.
    monkeypatch.setattr(meetings, 'today', lambda: TODAY + timedelta(days=7))
    assert ben.get('/api/me').status_code == 200
    later = MONDAY + timedelta(days=14)
    assert len(_meeting_pages(ana, later)) == 1 and len(_meeting_pages(ben, later)) == 1
    # Opened again: no second page.
    ben.get('/api/me')
    assert len(_meeting_pages(ana, later)) == 1


def test_anyone_in_trellis_is_invited_and_those_not_invited_do_not_see_it(as_user):
    ana, ben, zoe = as_user('ana'), as_user('ben'), as_user('zoe')
    r = ana.post('/api/meetings', json={'title': 'X', 'starts_on': MONDAY.isoformat(), 'repeat': 'none',
                                        'start_time': '10:00', 'end_time': '11:00', 'people': ['nobody']})
    assert r.status_code == 400 and 'account' in r.get_json()['error']
    listed = ana.get('/api/meetings').get_json()
    # Another lab's people too; not ana herself.
    assert {'ben', 'zoe', 'olead'} <= set(listed['invitable']) and 'ana' not in listed['invitable']
    m = _meeting(ana)                                      # ben only
    page = _meeting_pages(ana, MONDAY)[0]
    assert zoe.get(f"/api/notes/{page['id']}").status_code == 403
    assert zoe.get(f"/api/meetings/{m['id']}").status_code == 403
    assert [x['id'] for x in ben.get('/api/meetings').get_json()['meetings']] == [m['id']]
    # Zoe, of another lab, invited: the page is hers to take notes on, under her day.
    m2 = _meeting(ana, title='Collaboration', people=['zoe'])
    shared = _meeting_pages(zoe, MONDAY + timedelta(days=7))
    assert [p['title'] for p in shared] == ['Collaboration · 14:00']
    note = _get(zoe, shared[0]['id'])
    assert note['can_edit'] and not note['can_share'] and not note['meeting']['can_edit']
    note['content'][2]['html'] = '<h3>Notes</h3><p>Seeds sent on Friday</p>'
    assert zoe.put(f"/api/notes/{note['id']}", json={'content': note['content']}).status_code == 200
    assert 'Seeds sent' in _get(ana, note['id'])['content'][2]['html']
    # Only the organiser changes or ends the meeting.
    change = {'title': 'Mine now', 'starts_on': MONDAY.isoformat(), 'repeat': 'weekly',
              'start_time': '10:00', 'end_time': '11:00', 'people': []}
    assert zoe.put(f"/api/meetings/{m2['id']}", json=change).status_code == 403
    assert zoe.post(f"/api/meetings/{m2['id']}/end").status_code == 403
    assert ben.put(f"/api/meetings/{m['id']}", json=change).status_code == 403


def test_bad_times_and_dates(as_user):
    ana = as_user('ana')
    base = {'title': 'X', 'starts_on': MONDAY.isoformat(), 'repeat': 'weekly', 'start_time': '10:00', 'end_time': '11:00'}
    for change in ({'title': ' '}, {'start_time': '25:00'}, {'end_time': '09:00'}, {'repeat': 'daily'},
                   {'starts_on': '23-11-2026'}, {'until': '2026-11-01'}):
        assert ana.post('/api/meetings', json={**base, **change}).status_code == 400, change


def test_changing_a_meeting_remakes_pages_nobody_wrote_on_and_keeps_written_ones(as_user):
    ana, ben, lead = as_user('ana'), as_user('ben'), as_user('lead')
    m = _meeting(ana)
    this_week = _meeting_pages(ana, MONDAY)[0]
    next_week = _meeting_pages(ana, MONDAY + timedelta(days=7))[0]
    # Monday this week is gone by (today is Wednesday); it is kept as it was.
    # Next week's is written on.
    page = _get(ana, next_week['id'])
    page['content'][2]['html'] = '<h3>Notes</h3><p>Talk about the grant</p>'
    assert ana.put(f"/api/notes/{page['id']}", json={'content': page['content']}).status_code == 200
    r = ana.put(f"/api/meetings/{m['id']}", json={'title': 'Group meeting', 'starts_on': MONDAY.isoformat(),
                                                   'repeat': 'weekly', 'start_time': '09:30', 'end_time': '10:30',
                                                   'people': ['lead']})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['meeting']['people'] == ['lead']
    # Gone by: untouched.
    assert _get(ana, this_week['id'])['title'] == 'Lab meeting · 14:00'
    # Written on: kept, renamed; ben off it, lead on it and on the attendance list.
    kept = _get(ana, next_week['id'])
    assert kept['title'] == 'Group meeting · 09:30' and 'grant' in kept['content'][2]['html']
    assert [i['html'] for i in kept['content'][1]['items']] == ['ana', 'ben', 'lead']
    assert ben.get(f"/api/notes/{kept['id']}").status_code == 403
    assert [p['id'] for p in _meeting_pages(lead, MONDAY + timedelta(days=7))] == [kept['id']]
    assert _meeting_pages(ben, MONDAY + timedelta(days=7)) == []


def test_an_untouched_page_to_come_is_made_again_as_the_meeting_now_is(as_user):
    ana = as_user('ana')
    m = _meeting(ana)
    before = _meeting_pages(ana, MONDAY + timedelta(days=7))[0]
    # Moved to Thursdays.
    ana.put(f"/api/meetings/{m['id']}", json={'title': 'Lab meeting', 'starts_on': (MONDAY + timedelta(days=3)).isoformat(),
                                               'repeat': 'weekly', 'start_time': '14:00', 'end_time': '15:00',
                                               'people': ['ben']})
    assert _meeting_pages(ana, MONDAY + timedelta(days=7)) == []
    assert ana.get(f"/api/notes/{before['id']}").status_code == 404
    thursday = _meeting_pages(ana, MONDAY + timedelta(days=10))
    assert len(thursday) == 1 and len(_meeting_pages(ana, MONDAY + timedelta(days=3))) == 1


def test_a_date_deleted_is_skipped_and_ending_stops_it(as_user, monkeypatch):
    ana, ben = as_user('ana'), as_user('ben')
    m = _meeting(ana)
    page = _meeting_pages(ana, MONDAY + timedelta(days=7))[0]
    # Ben cannot delete the shared page; ana can, and it is not made again.
    assert ben.delete(f"/api/notes/{page['id']}").status_code == 403
    assert ana.delete(f"/api/notes/{page['id']}").status_code == 200
    ana.get('/api/me')
    assert _meeting_pages(ana, MONDAY + timedelta(days=7)) == []
    assert _meeting_pages(ben, MONDAY + timedelta(days=7)) == []
    r = ana.post(f"/api/meetings/{m['id']}/end")
    assert r.status_code == 200 and r.get_json()['meeting']['ended'] and r.get_json()['meeting']['next'] is None
    monkeypatch.setattr(meetings, 'today', lambda: TODAY + timedelta(days=14))
    ana.get('/api/me')
    assert _meeting_pages(ana, MONDAY + timedelta(days=14)) == []


def test_deleting_ones_own_day_leaves_the_meeting_for_the_others(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    _meeting(ana)
    when = MONDAY + timedelta(days=7)
    page = _meeting_pages(ben, when)[0]
    assert ana.delete(f"/api/notes/{_day(ana, when)['id']}").status_code == 200
    assert _get(ben, page['id'])['id'] == page['id']


def test_open_action_items_go_on_to_the_next_meeting(as_user, monkeypatch):
    ana, ben = as_user('ana'), as_user('ben')
    _meeting(ana)                                            # every Monday, from 23-11
    first = _get(ana, _meeting_pages(ana, MONDAY)[0]['id'])
    second_id = _meeting_pages(ana, MONDAY + timedelta(days=7))[0]['id']
    # Monday's meeting: three action items, one done, one empty.
    first['content'][3]['items'] = [{'id': 'a1', 'html': 'Order primers', 'priority': 'high'},
                                    {'id': 'a2', 'html': 'Book the confocal', 'done': True},
                                    {'id': 'a3', 'html': ''}]
    first = _ok_put(ben, first)
    # The next meeting's page, opened: the open one is on it, marked where it came from.
    second = _get(ben, second_id)
    items = second['content'][3]['items']
    assert [(i['html'], i['from_week'], i['priority']) for i in items] == [('Order primers', MONDAY.isoformat(), 'high')]
    before = _get(ana, first['id'])['content'][3]['items']
    assert [(i['id'], i['moved']) for i in before if i['moved']] == [('a1', (MONDAY + timedelta(days=7)).isoformat())]
    # Added during the meeting, after: follows on the next opening; nothing doubled.
    first = _get(ana, first['id'])
    first['content'][3]['items'].append({'id': 'a4', 'html': 'Send seeds to Zoe'})
    _ok_put(ana, first)
    items = _get(ben, second_id)['content'][3]['items']
    assert sorted(i['html'] for i in items) == ['Order primers', 'Send seeds to Zoe']
    # On the next meeting's own day its items stay put: the page is being written on.
    monkeypatch.setattr(meetings, 'today', lambda: MONDAY + timedelta(days=7))
    ana.get('/api/me')
    third_id = _meeting_pages(ana, MONDAY + timedelta(days=14))[0]['id']
    assert _get(ana, third_id)['content'][3]['items'] == []
    monkeypatch.setattr(meetings, 'today', lambda: TODAY + timedelta(days=7))
    second = _get(ana, second_id)
    second['content'][3]['items'][0]['done'] = True        # 'Order primers' done at the second meeting
    _ok_put(ana, second)
    # Once the second meeting's day has come, what is still open there goes on to the third.
    items = _get(ana, third_id)['content'][3]['items']
    assert [(i['html'], i['from_week']) for i in items] == [('Send seeds to Zoe', (MONDAY + timedelta(days=7)).isoformat())]


def _ok_put(client, note):
    r = client.put(f"/api/notes/{note['id']}", json={'content': note['content']})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['note']


def test_an_action_item_goes_on_ones_own_to_do_list(as_user, monkeypatch):
    from app import bookings
    monkeypatch.setattr(bookings, 'today', lambda: TODAY)
    ana, ben, zoe = as_user('ana'), as_user('ben'), as_user('zoe')
    _meeting(ana)
    page = _get(ana, _meeting_pages(ana, MONDAY)[0]['id'])
    page['content'][3]['items'] = [{'id': 'a1', 'html': 'Order primers', 'priority': 'high'},
                                   {'id': 'a2', 'html': 'Book the confocal'}, {'id': 'a3', 'html': ''}]
    page = _ok_put(ana, page)
    version = page['version']
    # Ben, invited, takes the first: it is on his list of this week, saying where it came from.
    r = ben.post(f"/api/notes/{page['id']}/tasks/a1/todo")
    assert r.status_code == 200, r.get_json()
    todo = _get(ben, r.get_json()['todo'])
    assert todo['type'] == 'todo' and todo['owner'] == 'ben'
    item = next(b for b in todo['content'] if b['type'] == 'tasks')['items'][0]
    assert (item['html'], item['priority'], item['from_note'], item['from_week']) == (
        'Order primers', 'high', page['id'], MONDAY.isoformat())
    # The meeting's page is not changed; it says whose list the item is on.
    seen = _get(ana, page['id'])
    assert seen['version'] == version
    assert seen['on_todo'] == {'a1': [{'username': 'ben', 'done_at': None}]}
    # Not twice; not an empty one; not by someone not at the meeting.
    assert ben.post(f"/api/notes/{page['id']}/tasks/a1/todo").status_code == 400
    assert ben.post(f"/api/notes/{page['id']}/tasks/a3/todo").status_code == 400
    assert zoe.post(f"/api/notes/{page['id']}/tasks/a2/todo").status_code == 404
    # Ana takes it too; ben ticks his: the meeting shows the tick, and a mark kept on later edits.
    assert ana.post(f"/api/notes/{page['id']}/tasks/a1/todo").status_code == 200
    item['done'] = True
    todo['content'][0]['items'][0] = item
    saved = _ok_put(ben, todo)
    assert saved['content'][0]['items'][0]['from_note'] == page['id']
    taken = _get(ana, page['id'])['on_todo']['a1']
    assert [t['username'] for t in taken] == ['ben', 'ana'] and taken[0]['done_at'] and taken[1]['done_at'] is None
    # Removed from ben's list: no longer listed, and he may take it again.
    saved['content'][0]['items'] = []
    _ok_put(ben, saved)
    assert [t['username'] for t in _get(ana, page['id'])['on_todo']['a1']] == ['ana']
    assert ben.post(f"/api/notes/{page['id']}/tasks/a1/todo").status_code == 200
