"""The notebook: days, pages, who may see and change what, history and links."""

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
    assert [p['title'] for p in protocols] == ['MoClo Golden Gate assembly']

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
    moclo = protocols[0]['id']
    assert ana.put(f'/api/notes/{moclo}', json=edit).status_code == 403
    assert as_user('boss').put(f'/api/notes/{moclo}', json={'title': 'MoClo Golden Gate assembly'}).status_code == 200


def test_a_protocol_goes_into_a_day_as_the_version_used(as_user):
    ana = as_user('ana')
    library = _me(ana)['library']
    moclo = ana.get(f'/api/notes/{library}/children').get_json()['children'][0]
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
    assert [n['id'] for n in ana.get('/api/search?q=clone 4').get_json()['notes']] == [gel['id']]
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
    assert set(listed) == {'MoClo Golden Gate assembly', 'Miniprep'}
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
