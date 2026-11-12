"""A week's to-do list: one page per week, under every day page of that week (app/todos.py)."""
from datetime import date, timedelta

from app import exporting, notes, todos
from app.db import connect
from app.people import Person

MONDAY = date(2026, 11, 9)          # week 46


def _day(client, when):
    return client.post('/api/days', json={'date': when.isoformat()}).get_json()['note']


def _get(client, note_id):
    return client.get(f'/api/notes/{note_id}').get_json()['note']


def _children(client, note_id):
    return [c['id'] for c in client.get(f'/api/notes/{note_id}/children').get_json()['children']]


def _make(client, day_id):
    r = client.post(f'/api/notes/{day_id}/todo')
    assert r.status_code == 200, r.get_json()
    return r.get_json()['note']


def _save_tasks(client, todo, items):
    block = next(b for b in todo['content'] if b['type'] == 'tasks')
    block['items'] = items
    r = client.put(f"/api/notes/{todo['id']}", json={'content': todo['content'], 'base_version': todo['version']})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['note']


def _tasks(note):
    return next(b for b in note['content'] if b['type'] == 'tasks')['items']


def test_a_week_has_one_list_under_every_day_of_it(as_user):
    ana = as_user('ana')
    tue, thu = _day(ana, MONDAY + timedelta(days=1)), _day(ana, MONDAY + timedelta(days=3))
    other_week = _day(ana, MONDAY + timedelta(days=7))
    assert _get(ana, tue['id'])['todo'] is None
    todo = _make(ana, thu['id'])
    assert todo['type'] == 'todo' and todo['title'] == 'To do · week 46 (09-11-2026 – 15-11-2026)'
    assert _tasks(todo) == []
    # The same page under each day of the week, first; not under next week's.
    for d in (tue, thu):
        assert _children(ana, d['id'])[0] == todo['id'] and _get(ana, d['id'])['todo'] == todo['id']
    assert todo['id'] not in _children(ana, other_week['id'])
    # Made again from another day of the week: the same list.
    assert _make(ana, tue['id'])['id'] == todo['id']
    # A day of the week started later gets it too.
    sat = _day(ana, MONDAY + timedelta(days=5))
    assert _children(ana, sat['id']) == [todo['id']]


def test_tasks_tag_records_and_are_ticked_by_whom(as_user):
    ana = as_user('ana')
    todo = _make(ana, _day(ana, MONDAY)['id'])
    todo = _save_tasks(ana, todo, [
        {'id': 't1', 'html': 'Miniprep <a data-plasmid="p1">pGFP-35S</a> clone 3'},
        {'id': 't2', 'html': 'Order primers', 'done': True},
        # What only the notebook sets is not taken from the page.
        {'id': 't3', 'html': 'Sneaky', 'moved': '2030-01-07', 'from_item': 'x'}])
    t1, t2, t3 = _tasks(todo)
    assert 'data-plasmid="p1"' in t1['html'] and t2['by'] == 'ana' and t2['at']
    assert t3['moved'] is None and t3['from_item'] is None
    # The plasmid's link is indexed, so the to-do page shows as linking to it; and its words are searched.
    assert todo['id'] in [n['id'] for n in ana.get('/api/mentions?type=plasmid&id=p1').get_json()['notes']]
    assert any(r['id'] == todo['id'] for r in ana.get('/api/search?q=miniprep').get_json()['notes'])


def test_a_task_moved_on_waits_for_next_weeks_list_and_can_come_back(as_user):
    ana = as_user('ana')
    todo = _save_tasks(ana, _make(ana, _day(ana, MONDAY)['id']), [
        {'id': 't1', 'html': 'Genotype the <b>T2</b> plants'}, {'id': 't2', 'html': 'Done already', 'done': True}])
    assert ana.post(f"/api/notes/{todo['id']}/tasks/t2/move").status_code == 400      # done: stays
    r = ana.post(f"/api/notes/{todo['id']}/tasks/t1/move")
    assert r.status_code == 200 and r.get_json()['next'] is None
    assert _tasks(r.get_json()['note'])[0]['moved'] == '2026-11-16'
    assert ana.post(f"/api/notes/{todo['id']}/tasks/t1/move").status_code == 400      # already moved
    # Back, and on again: it waits for next week's list, once.
    assert ana.post(f"/api/notes/{todo['id']}/tasks/t1/back").status_code == 200
    assert _tasks(_get(ana, todo['id']))[0]['moved'] is None
    ana.post(f"/api/notes/{todo['id']}/tasks/t1/move")
    later = _make(ana, _day(ana, MONDAY + timedelta(days=8))['id'])
    carried = _tasks(later)
    assert len(carried) == 1 and carried[0]['html'] == 'Genotype the <b>T2</b> plants'
    assert carried[0]['from_week'] == '2026-11-09' and carried[0]['from_item'] == 't1' and not carried[0]['by']
    # Brought back while not ticked there: it leaves next week's list.
    ana.post(f"/api/notes/{todo['id']}/tasks/t1/back")
    assert _tasks(_get(ana, later['id'])) == []
    # Moved again, now next week's list is made: it goes straight onto it; ticked there, it stays.
    ana.post(f"/api/notes/{todo['id']}/tasks/t1/move")
    later = _get(ana, later['id'])
    assert [t['from_item'] for t in _tasks(later)] == ['t1']
    item = dict(_tasks(later)[0], done=True)
    _save_tasks(ana, later, [item])
    assert ana.post(f"/api/notes/{todo['id']}/tasks/t1/back").status_code == 400


def test_only_who_may_change_the_day_changes_the_list(as_user):
    ana, lead = as_user('ana'), as_user('lead')
    day = _day(ana, MONDAY)
    assert lead.post(f"/api/notes/{day['id']}/todo").status_code == 403           # reads ana's, may not change it
    todo = _make(ana, day['id'])
    assert _get(lead, todo['id'])['can_edit'] is False
    _save_tasks(ana, todo, [{'id': 't1', 'html': 'x'}])
    assert lead.post(f"/api/notes/{todo['id']}/tasks/t1/move").status_code == 403
    assert as_user('zoe').get(f"/api/notes/{todo['id']}").status_code == 403         # another lab's member
    # Not a day: no list from it.
    page = ana.post('/api/notes', json={'parent_id': day['id'], 'title': 'Plan'}).get_json()['note']
    assert ana.post(f"/api/notes/{page['id']}/todo").status_code == 403


def test_deleting_a_day_keeps_the_list_while_another_day_shows_it(as_user):
    ana = as_user('ana')
    mon, tue = _day(ana, MONDAY), _day(ana, MONDAY + timedelta(days=1))
    todo = _make(ana, mon['id'])
    assert ana.delete(f"/api/notes/{mon['id']}").status_code == 200
    assert _get(ana, todo['id'])['id'] == todo['id']
    assert ana.delete(f"/api/notes/{tue['id']}").status_code == 200
    assert ana.get(f"/api/notes/{todo['id']}").status_code == 404


def test_a_list_exports(as_user):
    ana = as_user('ana')
    todo = _save_tasks(ana, _make(ana, _day(ana, MONDAY)['id']), [
        {'id': 't1', 'html': 'Miniprep <a data-plasmid="p1">pGFP-35S</a>'}, {'id': 't2', 'html': 'Order', 'done': True}])
    ana.post(f"/api/notes/{todo['id']}/tasks/t1/move")
    for fmt in ('pdf', 'docx'):
        r = ana.post(f"/api/notes/{todo['id']}/export", json={'format': fmt, 'timezone': 'Europe/Amsterdam',
                                                              'origin': 'http://lab.example:8080'})
        assert r.status_code == 202, r.get_json()
        job = r.get_json()['job']
        exporting.wait(job['id'])
        assert ana.get(f"/api/exports/{job['id']}").get_json()['job']['status'] == 'done'


def test_the_week_label_keeps_the_list_to_its_week(as_user):
    ana = as_user('ana')
    todo = _make(ana, _day(ana, MONDAY)['id'])
    label = next(a for a in todo['attributes'] if a['name'] == 'weekNote')
    assert label['value'] == '2026-11-09'
    assert ana.delete(f"/api/attributes/{label['id']}").status_code == 400
