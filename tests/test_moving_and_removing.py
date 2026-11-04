"""Steps put in a new order, a protocol put on any page, and a day, month or year taken away again."""
from datetime import datetime

from test_bookings_on_days import AMS, booking_db  # noqa: F401  (the fixture)
from test_notebook import _me, _page


def _steps(*texts, ticked=()):
    return {'id': 's1', 'type': 'steps', 'title': 'Do',
            'items': [{'id': f'i{n}', 'text': t, 'done': n in ticked} for n, t in enumerate(texts)]}


def test_steps_put_in_a_new_order_keep_their_ticks(as_user):
    """The page saves the steps in the order they were dragged to; a tick belongs to its step, not its place."""
    ana = as_user('ana')
    page = _page(ana, _me(ana)['notebook'], 'Run', [_steps('Thaw', 'Mix', 'Spin', 'Load', ticked=(1,))])
    items = page['content'][0]['items']
    assert [i['text'] for i in items] == ['Thaw', 'Mix', 'Spin', 'Load'] and items[1]['by'] == 'ana'
    ticked_at = items[1]['at']

    # Mix (ticked) dragged to the end, Load to the top.
    order = [items[3], items[0], items[2], items[1]]
    saved = ana.put(f"/api/notes/{page['id']}", json={'content': [{**page['content'][0], 'items': order}],
                                                     'base_version': page['version']}).get_json()['note']
    again = saved['content'][0]['items']
    assert [i['text'] for i in again] == ['Load', 'Thaw', 'Spin', 'Mix']
    assert again[3]['by'] == 'ana' and again[3]['at'] == ticked_at, 'the tick went with its step'
    assert [i['by'] for i in again[:3]] == [None, None, None]


def _protocol(client, title='Colony PCR'):
    made = client.post('/api/notes', json={'parent_id': _me(client)['library'], 'type': 'protocol', 'title': title,
                                           'content': [_steps('Pick a colony', 'Add to mix', ticked=(0,))]})
    assert made.status_code == 201, made.get_json()
    return made.get_json()['note']


def test_the_page_picker_offers_the_pages_you_may_add_to(as_user):
    ana, lead = as_user('ana'), as_user('lead')
    mine = _page(ana, _me(ana)['notebook'], 'Cloning week')
    ana.post('/api/days', json={'date': '2026-10-15'})
    found = ana.get('/api/search?q=Cloning&types=page,day&editable=1').get_json()['notes']
    assert [n['id'] for n in found] == [mine['id']]
    assert {n['type'] for n in ana.get('/api/search?types=page,day&editable=1').get_json()['notes']} == {'page', 'day'}
    # Her lab's lead can read her pages, but is not offered them to add to.
    assert mine['id'] in [n['id'] for n in lead.get('/api/search?q=Cloning&types=page').get_json()['notes']]
    assert lead.get('/api/search?q=Cloning&types=page&editable=1').get_json()['notes'] == []


def test_a_protocol_is_added_as_a_page_under_today(as_user):
    """Not more content in the day: a page of its own, named for the protocol, with fresh ticks."""
    ana = as_user('ana')
    protocol = _protocol(ana)
    today = ana.post('/api/days', json={}).get_json()['note']

    made = ana.post(f"/api/protocols/{protocol['id']}/use", json={})
    assert made.status_code == 201, made.get_json()
    page = made.get_json()['note']
    assert page['type'] == 'page' and page['title'] == 'Colony PCR'
    assert [p['id'] for p in page['path']][-2] == today['id'], 'a page under today'
    section = page['content'][0]
    assert section['type'] == 'section' and section['source']['id'] == protocol['id'] and section['source']['version'] == 1
    items = section['blocks'][0]['items']
    assert [i['text'] for i in items] == ['Pick a colony', 'Add to mix']
    assert [i['by'] for i in items] == [None, None], 'the protocol\'s own tick is not carried over'

    # Today's own page is left as it was, and the protocol lists the page as where it was used.
    assert ana.get(f"/api/notes/{today['id']}").get_json()['note']['content'] == today['content']
    used = ana.get(f"/api/notes/{protocol['id']}").get_json()['note']['backlinks']
    assert [b['id'] for b in used] == [page['id']]
    # Each use is a page of its own.
    again = ana.post(f"/api/protocols/{protocol['id']}/use", json={}).get_json()['note']
    assert again['id'] != page['id']
    kids = ana.get(f"/api/notes/{today['id']}/children").get_json()['children']
    assert [k['title'] for k in kids] == ['Colony PCR', 'Colony PCR']


def test_a_protocol_is_added_as_a_page_under_any_page_you_may_add_to(as_user):
    ana, lead = as_user('ana'), as_user('lead')
    protocol = _protocol(ana)
    mine = _page(ana, _me(ana)['notebook'], 'Cloning week', [{'id': 't', 'type': 'text', 'html': '<p>Plan</p>'}])

    made = ana.post(f"/api/protocols/{protocol['id']}/use", json={'parent_id': mine['id']})
    assert made.status_code == 201, made.get_json()
    page = made.get_json()['note']
    assert [p['id'] for p in page['path']][-2] == mine['id']
    assert ana.get(f"/api/notes/{mine['id']}").get_json()['note']['content'] == mine['content'], 'the page itself is untouched'

    # Not under a page that is not theirs to add to, and only a protocol can be used.
    assert lead.post(f"/api/protocols/{protocol['id']}/use", json={'parent_id': mine['id']}).status_code == 403
    assert ana.post(f"/api/protocols/{mine['id']}/use", json={}).status_code == 400


def test_a_mistyped_year_can_be_deleted_with_what_is_under_it_and_brought_back(as_user):
    ana = as_user('ana')
    ana.post('/api/days', json={'date': '2026-10-15'})
    six = ana.post('/api/days', json={'date': '0006-03-04'}).get_json()['note']
    odd = ana.post('/api/days', json={'date': '6202-03-04'}).get_json()['note']
    root = _me(ana)['notebook']
    years = lambda: {c['title'] for c in ana.get(f'/api/notes/{root}/children').get_json()['children']}
    assert years() == {'2026', '6', '6202'}

    year_of = lambda day: day['path'][-3]['id']
    for day in (six, odd):
        assert ana.delete(f"/api/notes/{year_of(day)}").status_code == 200
    assert years() == {'2026'}
    # The day under each went with it, and is not found as a page any more; the real day is untouched.
    assert ana.get(f"/api/notes/{six['id']}").status_code == 404
    assert [n['title'] for n in ana.get('/api/search?q=&types=day').get_json()['notes']] == ['15-10-2026 Thursday']
    assert {d['title'] for d in ana.get('/api/deleted').get_json()['deleted']} >= {'6', '6202'}

    # Nothing is lost: a year comes back with its months and days.
    back = ana.post(f"/api/deleted/{year_of(odd)}/restore")
    assert back.status_code == 200
    assert '6202' in years() and ana.get(f"/api/notes/{odd['id']}").status_code == 200


def test_one_wrong_day_can_be_deleted_on_its_own(as_user):
    ana = as_user('ana')
    keep = ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']
    wrong = ana.post('/api/days', json={'date': '2026-10-16'}).get_json()['note']
    assert wrong['can_delete'] is True
    assert ana.delete(f"/api/notes/{wrong['id']}").status_code == 200
    assert ana.get(f"/api/notes/{wrong['id']}").status_code == 404
    assert ana.get(f"/api/notes/{keep['id']}").status_code == 200
    # Someone else's notebook is not theirs to tidy.
    assert as_user('ben').delete(f"/api/notes/{keep['id']}").status_code == 403


def test_a_deleted_day_cannot_come_back_beside_a_new_one_for_the_same_date(as_user):
    ana = as_user('ana')
    old = ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']
    assert ana.delete(f"/api/notes/{old['id']}").status_code == 200
    new = ana.post('/api/days', json={'date': '2026-10-15'}).get_json()['note']
    assert new['id'] != old['id']

    refused = ana.post(f"/api/deleted/{old['id']}/restore")
    assert refused.status_code == 400 and 'again' in refused.get_json()['error']
    assert ana.get(f"/api/notes/{old['id']}").status_code == 404, 'nothing half-restored'

    # Once the new one is gone, the old one (and what was written on it) is back.
    assert ana.delete(f"/api/notes/{new['id']}").status_code == 200
    assert ana.post(f"/api/deleted/{old['id']}/restore").status_code == 200
    assert ana.get(f"/api/notes/{old['id']}").status_code == 200


def test_a_day_with_a_booking_is_kept_as_the_notebook_would_only_make_it_again(as_user, booking_db):  # noqa: F811
    ana = as_user('ana')
    today = datetime.now(AMS).date()
    booking_db['add']('b1', 'scope', today, '10:00', '11:00', 'ana', people=['ana'])
    ana.get('/api/me')                                    # the notebook gives a booked day its page
    day = ana.post('/api/days', json={'date': today.isoformat()}).get_json()['note']
    year, month = day['path'][-3], day['path'][-2]

    for note in (day, month, year):
        refused = ana.delete(f"/api/notes/{note['id']}")
        assert refused.status_code == 400 and 'booking' in refused.get_json()['error'], note['title']
        assert ana.get(f"/api/notes/{note['id']}").status_code == 200

    # Cancelled in Booking, it goes like any other.
    booking_db['run']("UPDATE bookings SET status = 'cancelled' WHERE id = 'b1'")
    assert ana.delete(f"/api/notes/{day['id']}").status_code == 200
