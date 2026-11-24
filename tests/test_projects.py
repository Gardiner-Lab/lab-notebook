"""Projects: work packages, tasks, what waits for what, the schedule, and tasks on meeting pages (app/projects.py)."""
from datetime import date

import pytest

from app import meetings, projects

TODAY = date(2026, 11, 25)


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch):
    monkeypatch.setattr(projects, '_today', lambda: TODAY)
    monkeypatch.setattr(meetings, 'today', lambda: TODAY)


def _ok(r, code=200):
    assert r.status_code == code, r.get_json()
    return r.get_json()


def _project(client, members=('ben',)):
    p = _ok(client.post('/api/projects', json={'title': 'Petunia CRISPR', 'members': list(members)}), 201)['project']
    p = _ok(client.post(f"/api/projects/{p['id']}/workpackages", json={'title': 'WP1 Constructs'}), 201)['project']
    return p


def _task(client, project, **data):
    body = {'wp_id': project['workpackages'][0]['id'], 'start_on': '2026-12-01', 'duration': 5, **data}
    return _ok(client.post(f"/api/projects/{project['id']}/tasks", json=body), 201)


def _by_title(project, title):
    return next(t for t in project['tasks'] if t['title'] == title)


def test_a_chain_of_tasks_moves_when_one_finishes_later(as_user):
    ana = as_user('ana')
    p = _project(ana)
    a = _task(ana, p, title='Design guides')
    b = _task(ana, a['project'], title='Clone', duration=3, after=[{'id': a['task_id']}])
    c = _task(ana, b['project'], title='Transform', duration=2, after=[{'id': b['task_id'], 'lag': 2}])
    p = c['project']
    assert (_by_title(p, 'Design guides')['start'], _by_title(p, 'Design guides')['end']) == ('2026-12-01', '2026-12-05')
    assert (_by_title(p, 'Clone')['start'], _by_title(p, 'Clone')['end']) == ('2026-12-06', '2026-12-08')
    assert (_by_title(p, 'Transform')['start'], _by_title(p, 'Transform')['end']) == ('2026-12-11', '2026-12-12')
    # The first takes three days longer: both after it move, and are named.
    r = _ok(ana.put(f"/api/tasks/{a['task_id']}", json={'duration': 8}))
    assert [m['title'] for m in r['moved']] == ['Clone', 'Transform']
    assert _by_title(r['project'], 'Transform')['start'] == '2026-12-14'
    # Done early, on 03-12: the rest come forward.
    r = _ok(ana.put(f"/api/tasks/{a['task_id']}", json={'done': True, 'done_on': '2026-12-03'}))
    p = r['project']
    assert _by_title(p, 'Design guides')['end'] == '2026-12-03' and _by_title(p, 'Design guides')['done_by'] == 'ana'
    assert _by_title(p, 'Clone')['start'] == '2026-12-04' and _by_title(p, 'Transform')['start'] == '2026-12-09'
    # A task waiting for two starts after the later one.
    d = _task(ana, p, title='Sequence', start_on='2026-12-20', duration=1)
    r = _ok(ana.put(f"/api/tasks/{c['task_id']}", json={'after': [{'id': b['task_id'], 'lag': 2},
                                                                    {'id': d['task_id']}]}))
    assert _by_title(r['project'], 'Transform')['start'] == '2026-12-21'


def test_subtasks_span_their_task_and_wait_with_it(as_user):
    ana = as_user('ana')
    p = _project(ana)
    first = _task(ana, p, title='Order parts', duration=4)                      # 01-12 .. 04-12
    parent = _task(ana, first['project'], title='Golden Gate', start_on='2026-12-01', duration=1,
                   after=[{'id': first['task_id']}])
    s1 = _task(ana, parent['project'], title='Level 1', parent_id=parent['task_id'], duration=2)
    s2 = _task(ana, s1['project'], title='Level 2', parent_id=parent['task_id'], duration=3,
               after=[{'id': s1['task_id']}])
    p = s2['project']
    # The subtasks wait for what their task waits for; the task spans them.
    assert _by_title(p, 'Level 1')['start'] == '2026-12-05' and _by_title(p, 'Level 2')['start'] == '2026-12-07'
    g = _by_title(p, 'Golden Gate')
    assert (g['start'], g['end'], g['subtasks']) == ('2026-12-05', '2026-12-09', 2)
    # Something waiting for the task waits for its last subtask.
    after = _task(ana, p, title='Plant', duration=1, after=[{'id': parent['task_id']}])
    assert _by_title(after['project'], 'Plant')['start'] == '2026-12-10'
    # A subtask takes its task's work package.
    wp2 = _ok(ana.post(f"/api/projects/{p['id']}/workpackages", json={'title': 'WP2'}), 201)['project']['workpackages'][1]
    moved = _ok(ana.put(f"/api/tasks/{parent['task_id']}", json={'wp_id': wp2['id']}))['project']
    assert {_by_title(moved, t)['wp_id'] for t in ('Golden Gate', 'Level 1', 'Level 2')} == {wp2['id']}


def test_loops_and_waiting_for_oneself_are_refused(as_user):
    ana = as_user('ana')
    p = _project(ana)
    a = _task(ana, p, title='A')
    b = _task(ana, a['project'], title='B', after=[{'id': a['task_id']}])
    r = ana.put(f"/api/tasks/{a['task_id']}", json={'after': [{'id': b['task_id']}]})
    assert r.status_code == 400 and 'loop' in r.get_json()['error']
    assert ana.put(f"/api/tasks/{a['task_id']}", json={'after': [{'id': a['task_id']}]}).status_code == 400
    sub = _task(ana, b['project'], title='A.1', parent_id=a['task_id'])
    assert ana.put(f"/api/tasks/{sub['task_id']}", json={'after': [{'id': a['task_id']}]}).status_code == 400
    # Nothing changed by the refusals.
    p = _ok(ana.get(f"/api/projects/{p['id']}"))['project']
    assert _by_title(p, 'A')['after'] == []


def test_members_work_on_it_and_only_the_owner_manages_it(as_user):
    ana, ben, zoe = as_user('ana'), as_user('ben'), as_user('zoe')
    p = _project(ana)
    t = _task(ana, p, title='Design guides', people=['ben'])
    assert _by_title(t['project'], 'Design guides')['people'] == ['ben']
    # Ben, a member: adds a work package and tasks, changes them; cannot rename or invite.
    _ok(ben.post(f"/api/projects/{p['id']}/workpackages", json={'title': 'WP2'}), 201)
    _ok(ben.put(f"/api/tasks/{t['task_id']}", json={'duration': 2}))
    assert ben.put(f"/api/projects/{p['id']}", json={'title': 'Mine'}).status_code == 403
    assert ben.post(f"/api/projects/{p['id']}/members", json={'username': 'zoe'}).status_code == 403
    # Zoe is not a member: nothing of it, nor the task's page.
    note_id = _by_title(t['project'], 'Design guides')['note_id']
    assert zoe.get(f"/api/projects/{p['id']}").status_code == 403
    assert zoe.get(f'/api/notes/{note_id}').status_code == 403
    assert [x['id'] for x in zoe.get('/api/projects').get_json()['projects']] == []
    # Invited (another lab's), she may; a task is given only to members.
    assert ana.put(f"/api/tasks/{t['task_id']}", json={'people': ['olead']}).status_code == 400
    _ok(ana.post(f"/api/projects/{p['id']}/members", json={'username': 'zoe'}), 201)
    assert zoe.get(f'/api/notes/{note_id}').status_code == 200
    # Taken off: no longer.
    _ok(ana.delete(f"/api/projects/{p['id']}/members/zoe"))
    assert zoe.get(f'/api/notes/{note_id}').status_code == 403


def test_a_tasks_page_holds_notes_and_links_like_any_page(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    p = _project(ana)
    t = _task(ana, p, title='Design guides')
    note = _ok(ben.get(f"/api/notes/{_by_title(t['project'], 'Design guides')['note_id']}"))['note']
    assert note['type'] == 'task' and note['can_edit'] and not note['can_delete'] and not note['can_add']
    assert note['task']['project']['title'] == 'Petunia CRISPR' and note['task']['workpackage']['title'] == 'WP1 Constructs'
    html = '<p>Use <a data-stock="GL-C-0003">Basta</a> and <a data-note="proto1">the CRISPR protocol</a></p>'
    saved = _ok(ben.put(f"/api/notes/{note['id']}", json={'title': 'Renamed', 'content': [{'type': 'text', 'html': html}]}))['note']
    assert saved['title'] == 'Design guides' and 'Basta' in saved['content'][0]['html']
    found = _ok(ana.get('/api/mentions?type=stock&id=GL-C-0003'))['notes']
    assert [n['id'] for n in found] == [note['id']]
    assert ana.delete(f"/api/notes/{note['id']}").status_code == 400
    # Renamed as a task: its page follows.
    _ok(ana.put(f"/api/tasks/{t['task_id']}", json={'title': 'Design sgRNAs'}))
    assert _ok(ana.get(f"/api/notes/{note['id']}"))['note']['title'] == 'Design sgRNAs'
    # Deleted with its task.
    _ok(ana.delete(f"/api/tasks/{t['task_id']}"))
    assert ana.get(f"/api/notes/{note['id']}").status_code == 404


def test_a_task_on_a_meeting_agenda_keeps_what_was_said_about_it(as_user):
    ana, ben, zoe = as_user('ana'), as_user('ben'), as_user('zoe')
    p = _project(ana)
    t = _task(ana, p, title='Design guides')
    task = _by_title(t['project'], 'Design guides')
    m = _ok(ana.post('/api/meetings', json={'title': 'Lab meeting', 'starts_on': '2026-11-23', 'repeat': 'weekly',
                                            'start_time': '14:00', 'end_time': '15:00', 'people': ['ben', 'zoe']}), 201)
    week = _ok(ben.get('/api/meetings/week?start=2026-11-30'))
    item = next(i for i in week['items'] if i['id'] == m['meeting']['id'])
    page = _ok(ben.get(f"/api/notes/{item['note_id']}"))['note']
    # Ben (a member) puts the task on the agenda and writes under it.
    section = _ok(ben.get(f"/api/projects/section?kind=task&id={task['id']}"))['section']
    assert section['source']['name'] == 'Petunia CRISPR › WP1 Constructs'
    section['blocks'][0]['html'] = '<p>Guides 3 and 7 chosen; order oligos</p>'
    page['content'].insert(1, section)
    _ok(ben.put(f"/api/notes/{page['id']}", json={'content': page['content']}))
    on_task = _ok(ana.get(f"/api/notes/{task['note_id']}"))['note']['task']['discussed']
    assert [(d['id'], d['type'], d['date']) for d in on_task] == [(page['id'], 'meeting', '2026-11-30')]
    assert on_task[0]['text'] == 'Guides 3 and 7 chosen; order oligos'
    # Zoe, at the meeting but not in the project, cannot pick its tasks.
    assert zoe.get(f"/api/projects/section?kind=task&id={task['id']}").status_code == 403
    assert _ok(zoe.get('/api/projects/pick'))['projects'] == []
    # A work package too, on a day page.
    wp = t['project']['workpackages'][0]
    day = _ok(ana.post('/api/days', json={'date': '2026-11-25'}), 201)['note']
    s = _ok(ana.get(f"/api/projects/section?kind=workpackage&id={wp['id']}"))['section']
    s['blocks'][0]['html'] = '<p>Constructs on track</p>'
    _ok(ana.put(f"/api/notes/{day['id']}", json={'content': day['content'] + [s]}))
    said = _ok(ana.get(f"/api/workpackages/{wp['id']}/discussed"))['discussed']
    assert [(d['id'], d['text']) for d in said] == [(day['id'], 'Constructs on track')]


def test_the_week_of_meetings_and_a_page_opened_further_ahead(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    m = _ok(ana.post('/api/meetings', json={'title': 'Lab meeting', 'starts_on': '2026-11-23', 'repeat': 'weekly',
                                            'start_time': '14:00', 'end_time': '15:00', 'people': ['ben']}), 201)['meeting']
    _ok(ana.post('/api/meetings', json={'title': 'Journal club', 'starts_on': '2026-11-26', 'repeat': 'fortnightly',
                                        'start_time': '09:00', 'end_time': '10:00', 'people': []}), 201)
    week = _ok(ana.get('/api/meetings/week?start=2026-11-25'))
    assert week['start'] == '2026-11-23'
    assert [(i['title'], i['date'], bool(i['note_id'])) for i in week['items']] == [
        ('Lab meeting', '2026-11-23', True), ('Journal club', '2026-11-26', True)]
    # Ben sees his, not ana's own journal club.
    assert [i['title'] for i in _ok(ben.get('/api/meetings/week'))['items']] == ['Lab meeting']
    # Three weeks ahead: no page yet; opened, it is made, under both days.
    later = _ok(ben.get('/api/meetings/week?start=2026-12-14'))['items'][0]
    assert later['date'] == '2026-12-14' and later['note_id'] is None
    page = _ok(ben.post(f"/api/meetings/{m['id']}/dates/2026-12-14"))['note']
    assert page['type'] == 'meeting' and page['meeting']['date'] == '2026-12-14'
    assert _ok(ben.get('/api/meetings/week?start=2026-12-14'))['items'][0]['note_id'] == page['id']
    assert ben.post(f"/api/meetings/{m['id']}/dates/2026-12-15").status_code == 400
    # Skipped: shown as such.
    _ok(ana.delete(f"/api/notes/{page['id']}"))
    assert _ok(ana.get('/api/meetings/week?start=2026-12-14'))['items'][0]['skipped']


def test_the_gantt_chart_exports_as_a_pdf_with_its_tasks(as_user):
    from io import BytesIO
    from pypdf import PdfReader
    ana, zoe = as_user('ana'), as_user('zoe')
    p = _project(ana)
    a = _task(ana, p, title='Design guides')
    _task(ana, a['project'], title='Clone', after=[{'id': a['task_id'], 'lag': 2}], people=['ben'])
    svg = ('<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120" viewBox="0 0 800 120">'
           '<style>text { fill: #2b2620; }</style><script>alert(1)</script>'
           '<image href="http://example.org/x.png" width="10" height="10"/>'
           '<rect x="10" y="10" width="200" height="20" fill="#2e7d5b" onclick="alert(2)"/>'
           '<text x="10" y="60">Design guides</text></svg>')
    r = ana.post(f"/api/projects/{p['id']}/gantt.pdf", json={'svg': svg})
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and r.data.startswith(b'%PDF')
    text = ' '.join(page.extract_text() for page in PdfReader(BytesIO(r.data)).pages)
    for words in ('Petunia CRISPR', 'WP1 Constructs', 'Design guides', 'Clone', '01-12-2026', 'Design guides +2 d', 'ben'):
        assert words in text, words
    assert zoe.post(f"/api/projects/{p['id']}/gantt.pdf", json={'svg': svg}).status_code == 403
    assert ana.post(f"/api/projects/{p['id']}/gantt.pdf", json={'svg': '<p>not a chart</p>'}).status_code == 400
