"""Pages shared within a chair group to work on together, and shown in more than one notebook."""

import sqlite3

import pytest


def _me(client):
    return client.get('/api/me').get_json()


def _page(client, parent, title, content=None):
    r = client.post('/api/notes', json={'parent_id': parent, 'title': title, 'type': 'page', 'content': content})
    assert r.status_code == 201, r.get_json()
    return r.get_json()['note']


def _children(client, parent):
    r = client.get(f'/api/notes/{parent}/children')
    assert r.status_code == 200, r.get_json()
    return [c['title'] for c in r.get_json()['children']]


def _save(client, note, **changes):
    current = client.get(f"/api/notes/{note['id']}").get_json()['note']
    return client.put(f"/api/notes/{note['id']}", json={'base_version': current['version'], **changes})


@pytest.fixture()
def chair(world):
    """Gardiner Lab and Other Lab in one chair group; Third Lab (tom) in none."""
    conn = sqlite3.connect(world['paths']['suite'])
    conn.executescript("ALTER TABLE labs ADD COLUMN chair_group_id TEXT;"
                       "UPDATE labs SET chair_group_id = 'cg1' WHERE id IN (1, 2);"
                       "INSERT INTO labs (id, name) VALUES (3, 'Third Lab');"
                       "INSERT INTO members VALUES ('tom', 3, 'member');")
    conn.commit()
    conn.close()
    conn = sqlite3.connect(world['paths']['moclo'])
    conn.execute("INSERT INTO users VALUES ('tom', 'tom', 0)")
    conn.commit()
    conn.close()
    return world


def test_a_page_is_shared_within_the_chair_group_to_work_on(chair, as_user):
    ana, zoe, tom, ben = (as_user(u) for u in ('ana', 'zoe', 'tom', 'ben'))
    root = _me(ana)['notebook']
    project = _page(ana, root, 'Joint project')
    sub = _page(ana, project['id'], 'Plan')
    private = _page(ana, root, 'Not shared')

    # Whom it can go to: people and labs of the chair group, not beyond.
    offer = ana.get(f"/api/notes/{project['id']}/shares").get_json()
    assert offer['can_share']
    assert sorted(offer['people']) == ['ben', 'lead', 'olead', 'zoe']
    assert sorted(lab['name'] for lab in offer['labs']) == ['Gardiner Lab', 'Other Lab']
    assert ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'person', 'target': 'tom'}).status_code == 400
    assert ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'lab', 'target': '3'}).status_code == 400

    # Before it is shared, someone of another lab cannot open it.
    assert zoe.get(f"/api/notes/{project['id']}").status_code == 403
    r = ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'person', 'target': 'zoe'})
    assert r.status_code == 201, r.get_json()

    # zoe finds it under "shared with me", opens the page and what is under it, and changes both.
    assert [p['title'] for p in _me(zoe)['shared_pages']] == ['Joint project']
    got = zoe.get(f"/api/notes/{project['id']}").get_json()['note']
    assert got['can_edit'] and got['can_add'] and not got['can_share'] and not got['can_delete']
    assert got['shared_in'] == [{'id': project['id'], 'title': 'Joint project', 'with': ['zoe']}]
    assert _children(zoe, project['id']) == ['Plan']
    assert _save(zoe, sub, title='Plan (zoe was here)').status_code == 200
    assert ana.get(f"/api/notes/{sub['id']}").get_json()['note']['title'] == 'Plan (zoe was here)'

    # A page zoe adds under it stays in ana's notebook, and ana can change it.
    added = _page(zoe, sub['id'], 'Results by zoe')
    assert added['owner'] == 'ana' and added['created_by'] == 'zoe'
    assert _save(ana, added, title='Results').status_code == 200
    assert zoe.get(f"/api/notes/{added['id']}").get_json()['note']['can_edit']

    # The rest of ana's notebook stays hers.
    assert zoe.get(f"/api/notes/{private['id']}").status_code == 403
    assert zoe.post('/api/notes', json={'parent_id': root, 'title': 'Sneaky', 'type': 'page'}).status_code == 403
    assert tom.get(f"/api/notes/{project['id']}").status_code == 403
    # Only ana shares it on, and only she deletes the shared page itself; zoe may delete what is under it.
    assert zoe.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'person', 'target': 'olead'}).status_code == 403
    assert zoe.delete(f"/api/notes/{project['id']}").status_code == 403
    assert zoe.delete(f"/api/notes/{added['id']}").status_code == 200
    assert 'Results' in [d['title'] for d in ana.get('/api/deleted').get_json()['deleted']]

    # Shared with a lab: everyone in it works on it.
    olead = as_user('olead')
    assert olead.get(f"/api/notes/{project['id']}").status_code == 403
    ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'lab', 'target': '2'})
    assert olead.get(f"/api/notes/{project['id']}").get_json()['note']['can_edit']
    # ben (ana's lab) is not given it by a share with another lab.
    assert ben.get(f"/api/notes/{project['id']}").status_code == 403

    # Retracted: gone for zoe again (the lab share still gives it to olead).
    shares = ana.get(f"/api/notes/{project['id']}/shares").get_json()['shares']
    zoe_share = next(s for s in shares if s['target'] == 'zoe')
    ana.delete(f"/api/shares/{zoe_share['id']}")
    olead_share = next(s for s in shares if s['target'] == '2')
    ana.delete(f"/api/shares/{olead_share['id']}")
    assert zoe.get(f"/api/notes/{project['id']}").status_code == 403
    assert _me(zoe)['shared_pages'] == []


def test_a_shared_page_shows_in_both_notebooks(chair, as_user):
    ana, zoe, olead = (as_user(u) for u in ('ana', 'zoe', 'olead'))
    project = _page(ana, _me(ana)['notebook'], 'Joint project', [{'type': 'text', 'html': '<p>first</p>'}])
    plan = _page(ana, project['id'], 'Plan')
    ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'person', 'target': 'zoe'})
    mine = _page(zoe, _me(zoe)['notebook'], 'My projects')

    # zoe shows ana's page under her own: one note, two places.
    r = zoe.post(f"/api/notes/{project['id']}/placements", json={'parent_id': mine['id']})
    assert r.status_code == 201, r.get_json()
    assert _children(zoe, mine['id']) == ['Joint project']
    assert _save(zoe, project, content=[{'type': 'text', 'html': '<p>changed by zoe</p>'}]).status_code == 200
    assert 'changed by zoe' in ana.get(f"/api/notes/{project['id']}").get_json()['note']['content'][0]['html']

    # ana does not see zoe's page through it; she is told it is somewhere else as well.
    seen = ana.get(f"/api/notes/{project['id']}").get_json()['note']
    assert [p['parent_title'] for p in seen['placements']] == ["ana's notebook"] and seen['other_places'] == 1
    # zoe cannot take it out of ana's notebook, only out of her own page.
    home = seen['placements'][0]
    assert zoe.delete(f"/api/branches/{home['branch_id']}").status_code == 403

    # Sharing her own page does not hand on ana's page shown under it.
    zoe.post(f"/api/notes/{mine['id']}/shares", json={'target_type': 'person', 'target': 'olead'})
    assert olead.get(f"/api/notes/{mine['id']}").status_code == 200
    assert _children(olead, mine['id']) == []
    assert olead.get(f"/api/notes/{project['id']}").status_code == 403

    # Deleting her own page leaves ana's page alone.
    assert zoe.delete(f"/api/notes/{mine['id']}").status_code == 200
    assert ana.get(f"/api/notes/{project['id']}").status_code == 200
    assert ana.get(f"/api/notes/{plan['id']}").status_code == 200

    # Only a page shared to work on goes into someone else's notebook.
    other = _page(ana, _me(ana)['notebook'], 'Private')
    again = _page(zoe, _me(zoe)['notebook'], 'Again')
    assert zoe.post(f"/api/notes/{other['id']}/placements", json={'parent_id': again['id']}).status_code == 403

    # Retracted: the copy-free placement in zoe's notebook stops showing it.
    zoe.post(f"/api/notes/{project['id']}/placements", json={'parent_id': again['id']})
    share = ana.get(f"/api/notes/{project['id']}/shares").get_json()['shares'][0]
    ana.delete(f"/api/shares/{share['id']}")
    assert _children(zoe, again['id']) == []


def test_without_chair_groups_a_page_is_shared_within_the_lab(as_user):
    ana, zoe = as_user('ana'), as_user('zoe')
    project = _page(ana, _me(ana)['notebook'], 'Lab project')
    offer = ana.get(f"/api/notes/{project['id']}/shares").get_json()
    assert sorted(offer['people']) == ['ben', 'lead'] and [lab['name'] for lab in offer['labs']] == ['Gardiner Lab']
    assert ana.post(f"/api/notes/{project['id']}/shares", json={'target_type': 'person', 'target': 'zoe'}).status_code == 400
    # A lab member cannot share someone else's page, even one they may read as lead.
    assert as_user('lead').post(f"/api/notes/{project['id']}/shares",
                                json={'target_type': 'person', 'target': 'ben'}).status_code == 403
