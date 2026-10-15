"""The notebook: days, pages, who may see and change what, history and links."""

import io
from datetime import date


def _me(client):
    r = client.get('/api/me')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _page(client, parent, title='Page', content=None):
    r = client.post('/api/notes', json={'parent_id': parent, 'title': title, 'content': content})
    assert r.status_code == 201, r.get_json()
    return r.get_json()['note']


def test_nothing_without_the_suite_saying_who_you_are(world):
    client = world['app'].test_client()
    assert client.get('/api/me').status_code == 401
    page = client.get('/')
    assert page.status_code == 302 and '/account/login' in page.headers['Location']
    assert client.get('/health').get_json()['status'] == 'healthy'


def test_starting_a_day_files_it_under_year_and_month(as_user):
    ana = as_user('ana')
    r = ana.post('/api/days', json={'date': '2026-10-15'})
    assert r.status_code == 201
    day = r.get_json()['note']
    assert day['title'] == '2026-10-15 Thursday' and day['type'] == 'day'
    assert [p['title'] for p in day['path']] == ["ana's notebook", '2026', '2026-10 October', '2026-10-15 Thursday']
    assert {'type': 'label', 'name': 'dateNote', 'value': '2026-10-15'} in [
        {k: a[k] for k in ('type', 'name', 'value')} for a in day['attributes']]

    # The same day again is the same page; today works without a date.
    assert ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']['id'] == day['id']
    today = ana.post('/api/days', json={}).get_json()['note']
    assert today['path'][-1]['title'].startswith(date.today().isoformat())
    assert ana.post('/api/days', json={'date': '15/10/2026'}).status_code == 400


def test_notebooks_are_private_except_to_the_lab_lead_and_admins(as_user):
    ana, ben, lead, boss, zoe = (as_user(u) for u in ('ana', 'ben', 'lead', 'boss', 'zoe'))
    day = ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']

    assert ben.get(f"/api/notes/{day['id']}").status_code == 403      # same lab, not the lead
    assert zoe.get(f"/api/notes/{day['id']}").status_code == 403      # another lab
    seen = lead.get(f"/api/notes/{day['id']}")
    assert seen.status_code == 200 and seen.get_json()['note']['can_edit'] is False
    assert boss.get(f"/api/notes/{day['id']}").status_code == 200
    # Leads and admins read; only the owner writes.
    assert lead.put(f"/api/notes/{day['id']}", json={'content': []}).status_code == 403

    assert [n['owner'] for n in _me(lead)['others']] == ['ana']
    assert 'ana' in [n['owner'] for n in _me(boss)['others']]
    assert _me(ben)['others'] == []
    assert _me(zoe)['others'] == []


def test_text_is_cleaned_and_ticks_are_stamped_by_the_server(as_user):
    ana = as_user('ana')
    day = ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']
    content = [
        {'id': 't1', 'type': 'text',
         'html': '<p onclick="x()">Hi <script>alert(1)</script><b>bold</b> '
                 '<a data-plasmid="p1" href="javascript:alert(1)">pGFP</a></p>'},
        {'id': 's1', 'type': 'steps', 'title': 'Do',
         'items': [{'id': 'i1', 'text': 'Thaw', 'done': True, 'by': 'someone-else', 'at': '1999-01-01'},
                   {'id': 'i2', 'text': 'Mix', 'done': False}]},
        {'id': 'x', 'type': 'script', 'code': 'evil'},
    ]
    r = ana.put(f"/api/notes/{day['id']}", json={'content': content, 'base_version': day['version']})
    assert r.status_code == 200, r.get_json()
    saved = r.get_json()['note']
    html = saved['content'][0]['html']
    assert '<script' not in html and 'onclick' not in html and 'javascript:' not in html
    assert '<b>bold</b>' in html and 'data-plasmid="p1"' in html
    assert [b['type'] for b in saved['content']] == ['text', 'steps']
    first, second = saved['content'][1]['items']
    assert first['by'] == 'ana' and first['at'] != '1999-01-01', 'a new tick is stamped here, not by the browser'
    assert second['by'] is None

    # Saving again keeps the original tick, whoever saves later.
    again = ana.put(f"/api/notes/{day['id']}", json={'content': saved['content'],
                                                     'base_version': saved['version']}).get_json()['note']
    assert again['content'][1]['items'][0] == first


def test_a_save_from_an_older_version_is_held_back(as_user):
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Plan')
    ok = ana.put(f"/api/notes/{page['id']}", json={'title': 'Plan A', 'base_version': page['version']})
    assert ok.status_code == 200
    stale = ana.put(f"/api/notes/{page['id']}", json={'title': 'Plan B', 'base_version': page['version']})
    assert stale.status_code == 409 and stale.get_json()['stale'] is True
    assert stale.get_json()['note']['title'] == 'Plan A'


def test_history_keeps_versions_and_restores_them(as_user, monkeypatch):
    from app import notes
    monkeypatch.setattr(notes, 'REVISION_WINDOW_MINUTES', 0)        # every save its own version
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Gel', [{'type': 'text', 'html': '<p>one</p>'}])
    v = page['version']
    for text in ('two', 'three'):
        v = ana.put(f"/api/notes/{page['id']}", json={'content': [{'type': 'text', 'html': f'<p>{text}</p>'}],
                                                     'base_version': v}).get_json()['note']['version']
    history = ana.get(f"/api/notes/{page['id']}/revisions").get_json()
    assert [r['number'] for r in history['revisions']] == [3, 2, 1] and history['current'] == 3
    assert history['revisions'][0]['changed_by'] == 'ana'

    restored = ana.post(f"/api/notes/{page['id']}/revisions/1/restore").get_json()['note']
    assert restored['content'][0]['html'] == '<p>one</p>' and restored['revision'] == 4
    assert ana.get(f"/api/notes/{page['id']}/revisions").get_json()['revisions'][0]['kind'] == 'restored'
    assert as_user('lead').post(f"/api/notes/{page['id']}/revisions/2/restore").status_code == 403


def test_quick_edits_make_one_version(as_user):
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Typing')
    v = page['version']
    for n in range(4):
        v = ana.put(f"/api/notes/{page['id']}", json={'content': [{'type': 'text', 'html': f'<p>{n}</p>'}],
                                                     'base_version': v}).get_json()['note']['version']
    revisions = ana.get(f"/api/notes/{page['id']}/revisions").get_json()['revisions']
    assert [r['number'] for r in revisions] == [2, 1], 'autosaves within minutes fold into one version'


def test_the_protocol_library_is_shared_and_its_authors_keep_it(as_user):
    ana, ben, lead, zoe = (as_user(u) for u in ('ana', 'ben', 'lead', 'zoe'))
    library = _me(ana)['library']
    protocols = ana.get(f'/api/notes/{library}/children').get_json()['children']
    assert [p['title'] for p in protocols] == ['How to write a protocol (start here)', 'MoClo Golden Gate assembly']

    mine = _page(ana, library, 'Miniprep', [
        {'type': 'steps', 'items': [{'text': 'Spin down'}]},
        {'type': 'table', 'columns': [{'name': 'Item'}, {'name': 'Done', 'kind': 'check'}],
         'rows': [{'cells': ['Buffer P1', True]}]}])
    assert mine['type'] == 'page'
    proto = ana.post('/api/notes', json={'parent_id': library, 'title': 'Miniprep', 'type': 'protocol'}).get_json()['note']
    assert proto['type'] == 'protocol' and proto['space'] == 'library'

    edit = {'title': 'Miniprep (Qiagen)'}
    assert ben.get(f"/api/notes/{proto['id']}").status_code == 200         # everyone can use it
    assert ben.put(f"/api/notes/{proto['id']}", json=edit).status_code == 403
    assert zoe.put(f"/api/notes/{proto['id']}", json=edit).status_code == 403
    assert lead.put(f"/api/notes/{proto['id']}", json=edit).status_code == 200   # the author's lab lead
    assert ana.put(f"/api/notes/{proto['id']}", json={'title': 'Miniprep v2'}).status_code == 200
    # Only admins change the protocol MoClo supplied.
    moclo = protocols[1]['id']
    assert ana.put(f'/api/notes/{moclo}', json=edit).status_code == 403
    assert as_user('boss').put(f'/api/notes/{moclo}', json={'title': 'MoClo Golden Gate assembly'}).status_code == 200


def test_a_protocol_goes_into_a_day_as_the_version_used(as_user):
    ana = as_user('ana')
    library = _me(ana)['library']
    moclo = next(c for c in ana.get(f'/api/notes/{library}/children').get_json()['children']
                 if c['title'] == 'MoClo Golden Gate assembly')
    snap = ana.get(f"/api/protocols/{moclo['id']}/snapshot").get_json()['section']
    assert snap['source'] == {'kind': 'protocol', 'id': moclo['id'], 'version': 1,
                              'name': 'MoClo Golden Gate assembly'}
    kinds = [b['type'] for b in snap['blocks']]
    assert 'table' in kinds and 'steps' in kinds

    day = ana.post('/api/days', json={'date': '2026-10-16'}).get_json()['note']
    saved = ana.put(f"/api/notes/{day['id']}", json={'content': [snap], 'base_version': day['version']}).get_json()['note']
    assert saved['content'][0]['source']['version'] == 1
    # The protocol shows the days that used it.
    backlinks = ana.get(f"/api/notes/{moclo['id']}").get_json()['note']['backlinks']
    assert [b['id'] for b in backlinks] == [day['id']]
    # The lead sees it among the backlinks; ben cannot see ana's day, so does not.
    assert as_user('lead').get(f"/api/notes/{moclo['id']}").get_json()['note']['backlinks']
    assert as_user('ben').get(f"/api/notes/{moclo['id']}").get_json()['note']['backlinks'] == []


def test_moclo_reactions_become_active_tables(as_user):
    ana = as_user('ana')
    saved = ana.get('/api/moclo/reactions').get_json()['saved']
    assert [(s['id'], s['title']) for s in saved] == [('s1', 'pGFP L1')]
    section = ana.get('/api/moclo/reactions/s1/section').get_json()['section']
    table = section['blocks'][1]
    assert [c['name'] for c in table['columns']] == ['Component', 'Plasmid size', 'Amount', 'Concentration',
                                                    'DNA', 'Volume', 'Added']
    assert table['columns'][4]['formula'] == '=B*C*660/1000000' and table['columns'][5]['formula'] == '=E/D'
    first = table['rows'][0]['cells']
    assert first[:3] == ['pL1V (acceptor vector)', '5000', '40']
    assert table['rows'][1]['cells'][2] == '80'
    assert table['rows'][-1]['cells'][5] == '=20-SUM(F1:F7)'
    # Someone else's saved assemblies are not theirs to see.
    assert as_user('ben').get('/api/moclo/reactions/s1/section').status_code == 404


def test_plasmids_to_link_follow_the_editors_rules(as_user):
    found = as_user('ana').get('/api/plasmids?q=pGFP').get_json()['plasmids']
    assert [p['id'] for p in found] == ['p1'] and found[0]['length'] == 400
    assert [p['id'] for p in as_user('ben').get('/api/plasmids').get_json()['plasmids']] == ['p1']
    assert {p['id'] for p in as_user('boss').get('/api/plasmids').get_json()['plasmids']} == {'p1', 'p2'}
    assert {p['id'] for p in as_user('zoe').get('/api/plasmids').get_json()['plasmids']} == {'p1', 'p2'}


def test_a_note_can_sit_in_two_places_and_move(as_user):
    ana = as_user('ana')
    root = _me(ana)['notebook']
    folder = _page(ana, root, 'Project GFP')
    other = _page(ana, root, 'Results')
    note = _page(ana, folder['id'], 'Western blot')
    r = ana.post(f"/api/notes/{note['id']}/placements", json={'parent_id': other['id']})
    assert r.status_code == 201 and len(r.get_json()['note']['placements']) == 2
    kids = ana.get(f"/api/notes/{other['id']}/children").get_json()['children']
    assert kids[0]['id'] == note['id'] and kids[0]['cloned'] is True

    # Moving: not into itself, and not into someone else's notebook.
    branch = {c['id']: c['branch_id'] for c in ana.get(f'/api/notes/{root}/children').get_json()['children']}
    assert ana.post(f"/api/branches/{branch[folder['id']]}/move", json={'parent_id': note['id']}).status_code == 400
    assert ana.post(f"/api/branches/{branch[other['id']]}/move", json={'parent_id': folder['id']}).status_code == 200
    assert [c['id'] for c in ana.get(f"/api/notes/{folder['id']}/children").get_json()['children']] ==         [note['id'], other['id']]
    ben_root = _me(as_user('ben'))['notebook']
    assert ana.post(f"/api/notes/{note['id']}/placements", json={'parent_id': ben_root}).status_code == 403

    placements = ana.get(f"/api/notes/{note['id']}").get_json()['note']['placements']
    assert ana.delete(f"/api/branches/{placements[0]['branch_id']}").status_code == 200
    assert ana.delete(f"/api/branches/{placements[1]['branch_id']}").status_code == 400   # its last place


def test_attributes_and_deleting(as_user):
    ana = as_user('ana')
    root = _me(ana)['notebook']
    page = _page(ana, root, 'Seeds')
    attr = ana.post(f"/api/notes/{page['id']}/attributes", json={'type': 'label', 'name': '#project', 'value': 'GFP'})
    assert attr.status_code == 201 and attr.get_json()['attribute']['name'] == 'project'
    assert ana.post(f"/api/notes/{page['id']}/attributes", json={'name': 'bad name!'}).status_code == 400
    assert as_user('lead').post(f"/api/notes/{page['id']}/attributes", json={'name': 'x'}).status_code == 403
    found = ana.get('/api/search?q=Seed').get_json()['notes']
    assert [n['id'] for n in found] == [page['id']]
    assert as_user('ben').get('/api/search?q=Seed').get_json()['notes'] == []

    assert ana.delete(f"/api/notes/{page['id']}").status_code == 200
    assert ana.get(f"/api/notes/{page['id']}").status_code == 404
    assert ana.delete(f'/api/notes/{root}').status_code == 403


def test_search_finds_words_in_pages_and_labels(as_user):
    ana, ben, lead = as_user('ana'), as_user('ben'), as_user('lead')
    root = _me(ana)['notebook']
    gel = _page(ana, root, 'Gel run', [
        {'type': 'text', 'html': '<p>Ran the <b>colony PCR</b> products on a 1% agarose gel.</p>'},
        {'type': 'table', 'columns': [{'name': 'Lane'}, {'name': 'Sample'}], 'rows': [{'cells': ['1', 'pGFP clone 4']}]},
        {'type': 'steps', 'items': [{'text': 'Stain with SYBR Safe'}]}])
    _page(ana, root, 'Agarose stock recipe')

    found = ana.get('/api/search?q=agarose').get_json()['notes']
    assert [n['title'] for n in found] == ['Agarose stock recipe', 'Gel run'], 'title matches come first'
    assert 'agarose gel' in found[1]['snippet'] and found[1]['where'] == ''
    # Every word must appear, in text, table cells or steps.
    assert [n['id'] for n in ana.get('/api/search?q=SYBR colony').get_json()['notes']] == [gel['id']]
    assert [n['id'] for n in ana.get('/api/search?q=lane pgfp').get_json()['notes']] == [gel['id']]
    assert ana.get('/api/search?q=<b>').get_json()['notes'] == [], 'markup is not searched'
    # Others find it only where they may open it.
    assert ben.get('/api/search?q=agarose').get_json()['notes'] == []
    assert len(lead.get('/api/search?q=agarose').get_json()['notes']) == 2

    ana.post(f"/api/notes/{gel['id']}/attributes", json={'name': 'project', 'value': 'GFP'})
    assert [n['id'] for n in ana.get('/api/search?q=%23project').get_json()['notes']] == [gel['id']]
    assert [n['id'] for n in ana.get('/api/search?q=%23project=gfp').get_json()['notes']] == [gel['id']]
    assert ana.get('/api/search?q=%23project=RFP').get_json()['notes'] == []

    # Saving changes what is found.
    ana.put(f"/api/notes/{gel['id']}", json={'content': [{'type': 'text', 'html': '<p>Western blot</p>'}]})
    assert [n['id'] for n in ana.get('/api/search?q=agarose').get_json()['notes']] != [gel['id']]
    assert [n['id'] for n in ana.get('/api/search?q=western').get_json()['notes']] == [gel['id']]


def test_the_protocol_list_and_favourites(as_user):
    ana, ben = as_user('ana'), as_user('ben')
    library = _me(ana)['library']
    folder = ana.post('/api/notes', json={'parent_id': library, 'title': 'Cloning', 'type': 'folder'}).get_json()['note']
    mini = ana.post('/api/notes', json={'parent_id': folder['id'], 'title': 'Miniprep', 'type': 'protocol',
                                        'content': [{'type': 'steps', 'items': [{'text': 'Lyse with buffer P2'}]}]}).get_json()['note']
    listed = {p['title']: p for p in ben.get('/api/protocols').get_json()['protocols']}
    assert set(listed) == {'How to write a protocol (start here)', 'MoClo Golden Gate assembly', 'Miniprep'}
    assert listed['Miniprep']['folder'] == 'Cloning' and listed['Miniprep']['created_by'] == 'ana'
    assert listed['Miniprep']['can_edit'] is False and listed['Miniprep']['favorite'] is False
    assert [p['title'] for p in ben.get('/api/protocols?q=lyse').get_json()['protocols']] == ['Miniprep']

    # Used on a day: counted.
    day = ana.post('/api/days', json={'date': '2026-10-20'}).get_json()['note']
    snap = ana.get(f"/api/protocols/{mini['id']}/snapshot").get_json()['section']
    ana.put(f"/api/notes/{day['id']}", json={'content': [snap]})
    assert {p['title']: p['uses'] for p in ana.get('/api/protocols').get_json()['protocols']}['Miniprep'] == 1

    # Favourites are each person's own.
    r = ben.put(f"/api/favorites/{mini['id']}")
    assert r.status_code == 200 and [f['title'] for f in r.get_json()['favorites']] == ['Miniprep']
    assert ana.get('/api/favorites').get_json()['favorites'] == []
    assert ben.get(f"/api/notes/{mini['id']}").get_json()['note']['favorite'] is True
    assert {p['title']: p['favorite'] for p in ben.get('/api/protocols').get_json()['protocols']}['Miniprep'] is True
    assert ben.put(f"/api/favorites/{day['id']}").status_code in (400, 403, 404)
    assert ben.delete(f"/api/favorites/{mini['id']}").get_json()['favorites'] == []
    # A deleted protocol leaves the favourites.
    ben.put(f"/api/favorites/{mini['id']}")
    ana.delete(f"/api/notes/{mini['id']}")
    assert ben.get('/api/favorites').get_json()['favorites'] == []


def test_the_how_to_protocol_teaches_by_example(as_user):
    ana = as_user('ana')
    found = ana.get('/api/protocols?q=how to write').get_json()['protocols']
    assert [p['title'] for p in found] == ['How to write a protocol (start here)']
    note = ana.get(f"/api/notes/{found[0]['id']}").get_json()['note']
    tables = [b for b in note['content'] if b['type'] == 'table']
    kinds = {c['kind'] for t in tables for c in t['columns']}
    assert kinds == {'text', 'number', 'formula', 'scaled', 'fill', 'check'}, 'every kind of column is shown'
    assert any(t['scale'] for t in tables) and any(b['type'] == 'steps' for b in note['content'])
    assert note['can_edit'] is False and as_user('boss').get(f"/api/notes/{found[0]['id']}").get_json()['note']['can_edit']
    # First in the library, and its marker label stays.
    assert ana.get('/api/protocols').get_json()['protocols'][0]['id'] == found[0]['id']
    seed = next(a for a in note['attributes'] if a['name'] == 'seed')
    assert as_user('boss').delete(f"/api/attributes/{seed['id']}").status_code == 400
    # Found by what it teaches.
    assert found[0]['id'] in [n['id'] for n in ana.get('/api/search?q=master mix').get_json()['notes']]


def test_make_a_copy_to_start_from(as_user, world):
    ana, ben = as_user('ana'), as_user('ben')
    howto = ana.get('/api/protocols?q=how to write').get_json()['protocols'][0]
    r = ben.post(f"/api/notes/{howto['id']}/copy")
    assert r.status_code == 201
    copy = r.get_json()['note']
    assert copy['title'] == 'How to write a protocol (start here) (copy)' and copy['type'] == 'protocol'
    assert copy['space'] == 'library' and copy['created_by'] == 'ben' and copy['can_edit'] is True
    original = ben.get(f"/api/notes/{howto['id']}").get_json()['note']
    assert [b['type'] for b in copy['content']] == [b['type'] for b in original['content']]
    assert {b['id'] for b in copy['content']}.isdisjoint({b['id'] for b in original['content']})

    # A page with ticks: copied into the copier's notebook, without the ticks.
    day = ana.post('/api/days', json={'date': '2026-10-21'}).get_json()['note']
    ana.put(f"/api/notes/{day['id']}", json={'content': [
        {'type': 'steps', 'items': [{'text': 'Thaw', 'done': True}]},
        {'type': 'table', 'columns': [{'name': 'x'}, {'name': 'ok', 'kind': 'check'}], 'rows': [{'cells': ['a', True]}]}]})
    page = ana.post(f"/api/notes/{day['id']}/copy").get_json()['note']
    assert page['type'] == 'page' and page['path'][-2]['id'] == day['path'][-2]['id'], 'beside the original'
    assert page['content'][0]['items'][0]['by'] is None and page['content'][1]['rows'][0]['cells'][1] is None
    # Someone who may only read a notebook copies into their own.
    lead_copy = as_user('lead').post(f"/api/notes/{page['id']}/copy").get_json()['note']
    assert lead_copy['owner'] == 'lead' and lead_copy['path'][0]['title'] == "lead's notebook"
    assert ben.post(f"/api/notes/{page['id']}/copy").status_code == 403


def test_the_database_can_be_read_from_a_read_only_copy(world):
    """The suite's backup opens it read-only: that fails for a database in WAL mode."""
    import sqlite3
    path = world['paths']['notebook']
    assert sqlite3.connect(path).execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    ro = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    assert ro.execute("SELECT COUNT(*) FROM notes WHERE type = 'protocol'").fetchone()[0] == 2


def test_no_one_sees_into_another_labs_notebooks(as_user):
    """A lab lead reads their own lab's notebooks, never another lab's, by any route."""
    ana, zoe, olead = as_user('ana'), as_user('zoe'), as_user('olead')
    day = ana.post('/api/days', json={'date': '2026-10-22'}).get_json()['note']
    ana.put(f"/api/notes/{day['id']}", json={'content': [{'type': 'text', 'html': '<p>Secret gel result</p>'}]})
    zday = zoe.post('/api/days', json={'date': '2026-10-22'}).get_json()['note']

    # The other lab's lead reads their own lab, and nothing of ana's.
    assert olead.get(f"/api/notes/{zday['id']}").status_code == 200
    assert [n['owner'] for n in _me(olead)['others']] == ['zoe']
    for client in (olead, zoe):
        assert client.get(f"/api/notes/{day['id']}").status_code == 403
        assert client.get(f"/api/notes/{day['id']}/children").status_code == 403
        assert client.get(f"/api/notes/{day['id']}/revisions").status_code == 403
        assert client.get(f"/api/notes/{day['id']}/revisions/1").status_code == 403
        assert client.post(f"/api/notes/{day['id']}/copy").status_code == 403
        assert client.get('/api/search?q=secret').get_json()['notes'] == []
        dated = client.get('/api/search?q=%23dateNote=2026-10-22').get_json()['notes']
        assert all(n['owner'] != 'ana' for n in dated)
    # And ana's lead cannot read the other lab.
    assert as_user('lead').get(f"/api/notes/{zday['id']}").status_code == 403


def test_deleted_notes_can_be_brought_back(as_user):
    ana, ben, lead, boss = (as_user(u) for u in ('ana', 'ben', 'lead', 'boss'))
    root = _me(ana)['notebook']
    project = _page(ana, root, 'Project GFP', [{'type': 'text', 'html': '<p>plan</p>'}])
    gel = _page(ana, project['id'], 'Gel')
    blot = _page(ana, project['id'], 'Blot')
    ana.delete(f"/api/notes/{blot['id']}")            # on its own, first
    ana.delete(f"/api/notes/{project['id']}")         # then the project, with the gel

    listed = {d['title']: d for d in ana.get('/api/deleted').get_json()['deleted']}
    assert {t: (d['pages'], d['deleted_by']) for t, d in listed.items()} == {'Project GFP': (2, 'ana'), 'Blot': (1, 'ana')}
    assert listed['Blot']['was_under'] == 'Project GFP' and listed['Blot']['parent_deleted'] is True
    assert ana.get(f"/api/deleted/{project['id']}").get_json()['note']['content'][0]['html'] == '<p>plan</p>'
    assert ana.get('/api/search?q=gel').get_json()['notes'] == []

    # Others: not ben; ana's lead reads notebooks but does not restore them; an admin can.
    assert ben.get('/api/deleted').get_json()['deleted'] == []
    assert ben.post(f"/api/deleted/{project['id']}/restore").status_code == 403
    assert lead.get('/api/deleted').get_json()['deleted'] == []
    assert {d['title'] for d in boss.get('/api/deleted').get_json()['deleted']} == {'Project GFP', 'Blot'}

    # Restoring the project brings the gel back with it, where it was; the blot stays deleted.
    r = ana.post(f"/api/deleted/{project['id']}/restore")
    assert r.status_code == 200 and r.get_json()['note']['path'][-2]['id'] == root
    kids = [c['title'] for c in ana.get(f"/api/notes/{project['id']}/children").get_json()['children']]
    assert kids == ['Gel']
    assert [d['title'] for d in ana.get('/api/deleted').get_json()['deleted']] == ['Blot']

    # An admin restores the blot for ana: back under its project.
    r = boss.post(f"/api/deleted/{blot['id']}/restore")
    assert r.status_code == 200
    assert sorted(c['title'] for c in ana.get(f"/api/notes/{project['id']}/children").get_json()['children']) == ['Blot', 'Gel']
    assert ana.get('/api/deleted').get_json()['deleted'] == []
    assert ana.post(f"/api/deleted/{gel['id']}/restore").status_code == 404


def test_a_note_whose_place_is_gone_comes_back_at_the_top(as_user):
    ana = as_user('ana')
    root = _me(ana)['notebook']
    folder = _page(ana, root, 'Old folder')
    note = _page(ana, folder['id'], 'Keep me')
    ana.delete(f"/api/notes/{note['id']}")
    ana.delete(f"/api/notes/{folder['id']}")
    restored = ana.post(f"/api/deleted/{note['id']}/restore").get_json()['note']
    assert [p['title'] for p in restored['path']] == ["ana's notebook", 'Keep me']

    # A deleted protocol: its author restores it, and it is a favourite again.
    library = _me(ana)['library']
    proto = ana.post('/api/notes', json={'parent_id': library, 'title': 'PCR', 'type': 'protocol'}).get_json()['note']
    as_user('ben').put(f"/api/favorites/{proto['id']}")
    ana.delete(f"/api/notes/{proto['id']}")
    assert as_user('ben').get('/api/favorites').get_json()['favorites'] == []
    assert as_user('lead').get('/api/deleted').get_json()['deleted'][0]['title'] == 'PCR'   # ana's lead may change it
    ana.post(f"/api/deleted/{proto['id']}/restore")
    assert [f['title'] for f in as_user('ben').get('/api/favorites').get_json()['favorites']] == ['PCR']


PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def _attach(client, note_id, *files):
    data = {'file': [(io.BytesIO(body), name) for name, body in files]}
    return client.post(f'/api/notes/{note_id}/attachments', data=data, content_type='multipart/form-data')


def test_photos_and_files_attach_to_notes(as_user):
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Gel photos')
    r = _attach(ana, page['id'], ('gel.png', PNG), ('protocol.pdf', b'%PDF-1.4 test'))
    assert r.status_code == 201
    gel, pdf = r.get_json()['attachments']
    assert (gel['filename'], gel['image'], gel['mime'], gel['created_by']) == ('gel.png', True, 'image/png', 'ana')
    assert pdf['image'] is False and pdf['size'] == len(b'%PDF-1.4 test')
    assert [a['id'] for a in ana.get(f"/api/notes/{page['id']}").get_json()['note']['attachments']] == [gel['id'], pdf['id']]

    # A photo shows in the page; anything else only downloads, and is never read as a page.
    shown = ana.get(f"/api/attachments/{gel['id']}")
    assert shown.status_code == 200 and shown.data == PNG and shown.mimetype == 'image/png'
    assert shown.headers['Content-Disposition'].startswith('inline')
    assert shown.headers['X-Content-Type-Options'] == 'nosniff' and 'sandbox' in shown.headers['Content-Security-Policy']
    got = ana.get(f"/api/attachments/{pdf['id']}")
    assert got.headers['Content-Disposition'].startswith('attachment') and got.mimetype == 'application/octet-stream'
    assert ana.get(f"/api/attachments/{gel['id']}?download").headers['Content-Disposition'].startswith('attachment')

    # Text can show it by its attachment, never by an address of its own.
    saved = ana.put(f"/api/notes/{page['id']}", json={'content': [{'type': 'text', 'html':
        f'<p><img data-attachment="{gel["id"]}" alt="gel" src="https://evil.example/x.png" onerror="alert(1)"></p>'}]}).get_json()['note']
    html = saved['content'][0]['html']
    assert f'data-attachment="{gel["id"]}"' in html and 'src=' not in html and 'onerror' not in html


def test_files_that_could_run_as_a_page_only_download(as_user):
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Risky')
    svg, html, fake = _attach(ana, page['id'], ('x.svg', b'<svg onload="alert(1)"/>'),
                              ('x.html', b'<script>alert(1)</script>'), ('photo.png', b'not really a png')).get_json()['attachments']
    for a in (svg, html, fake):
        assert a['image'] is False
        r = ana.get(f"/api/attachments/{a['id']}")
        assert r.headers['Content-Disposition'].startswith('attachment') and r.mimetype == 'application/octet-stream'


def test_who_may_see_and_add_attachments(as_user):
    ana, ben, lead, zoe = (as_user(u) for u in ('ana', 'ben', 'lead', 'zoe'))
    page = _page(ana, _me(ana)['notebook'], 'Private photo')
    att = _attach(ana, page['id'], ('gel.png', PNG)).get_json()['attachments'][0]
    assert lead.get(f"/api/attachments/{att['id']}").status_code == 200         # reads the lab's notebooks
    assert ben.get(f"/api/attachments/{att['id']}").status_code == 403
    assert zoe.get(f"/api/attachments/{att['id']}").status_code == 403
    assert _attach(lead, page['id'], ('x.png', PNG)).status_code == 403          # but does not add
    assert lead.delete(f"/api/attachments/{att['id']}").status_code == 403
    # Protocol photos: everyone sees them, the author adds them.
    proto = ana.post('/api/notes', json={'parent_id': _me(ana)['library'], 'title': 'Western', 'type': 'protocol'}).get_json()['note']
    patt = _attach(ana, proto['id'], ('setup.png', PNG)).get_json()['attachments'][0]
    assert zoe.get(f"/api/attachments/{patt['id']}").status_code == 200
    assert _attach(ben, proto['id'], ('x.png', PNG)).status_code == 403


def test_attachment_limits_and_removal(as_user, monkeypatch):
    from app import attachments
    monkeypatch.setattr(attachments, 'MAX_BYTES', 100)
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Limits')
    assert _attach(ana, page['id'], ('big.bin', b'x' * 101)).status_code == 400
    assert _attach(ana, page['id'], ('empty.txt', b'')).status_code == 400
    att = _attach(ana, page['id'], ('../../etc/pass\x00wd', b'abc')).get_json()['attachments'][0]
    assert '/' not in att['filename'] and '\x00' not in att['filename']

    assert ana.delete(f"/api/attachments/{att['id']}").status_code == 200
    assert ana.get(f"/api/notes/{page['id']}").get_json()['note']['attachments'] == []
    # Still there for the versions that show it.
    assert ana.get(f"/api/attachments/{att['id']}").status_code == 200
    assert ana.delete(f"/api/attachments/{att['id']}").status_code == 404


def test_a_copy_gets_its_own_attachments(as_user):
    ana = as_user('ana')
    proto = ana.post('/api/notes', json={'parent_id': _me(ana)['library'], 'title': 'Imaging', 'type': 'protocol'}).get_json()['note']
    att = _attach(ana, proto['id'], ('scope.png', PNG)).get_json()['attachments'][0]
    ana.put(f"/api/notes/{proto['id']}", json={'content': [{'type': 'text', 'html': f'<p><img data-attachment="{att["id"]}"></p>'}]})
    copy = as_user('ben').post(f"/api/notes/{proto['id']}/copy").get_json()['note']
    [mine] = copy['attachments']
    assert mine['id'] != att['id'] and mine['filename'] == 'scope.png' and mine['created_by'] == 'ben'
    assert f'data-attachment="{mine["id"]}"' in copy['content'][0]['html']
    assert as_user('ben').get(f"/api/attachments/{mine['id']}").data == PNG
