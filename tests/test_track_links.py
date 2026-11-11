"""
A page links to a Genome Browser track as it does to a plasmid or a seed lot,
and the Genome Browser asks which pages link to one of its tracks.
"""

from app import content


def _me(client):
    return client.get('/api/me').get_json()


def test_a_track_link_is_kept_and_indexed():
    html = content.clean_html('<p>Coverage: <a data-track="abc123" onclick="x()">Rep1</a></p>') \
        if hasattr(content, 'clean_html') else None
    if html is not None:
        assert 'data-track="abc123"' in html and 'onclick' not in html
    blocks = [{'type': 'text', 'html': '<p><a data-track="abc123">Rep1</a> and <a data-seed="GL-L-0001">Col</a></p>'}]
    assert ('track', 'abc123') in content.links(blocks)


def test_the_genome_browser_asks_which_pages_link_to_a_track(as_user):
    ana = as_user('ana')
    day = ana.post('/api/days', json={'date': '2026-11-10'}).get_json()['note']
    text = {'type': 'text', 'html': '<p>Heat stress coverage: <a data-track="trk42">Rep1 coverage</a></p>'}
    saved = ana.put(f"/api/notes/{day['id']}", json={'content': [text], 'base_version': day['version']})
    assert saved.status_code == 200, saved.get_json()
    # The link survives the server's cleaning of the text.
    assert 'data-track="trk42"' in saved.get_json()['note']['content'][0]['html']

    found = ana.get('/api/mentions?type=track&id=trk42').get_json()['notes']
    assert [n['id'] for n in found] == [day['id']]
    assert found[0]['owner'] == 'ana' and found[0]['title']
    # Ana's lead sees her day; Ben, in another lab, does not.
    assert [n['id'] for n in as_user('lead').get('/api/mentions?type=track&id=trk42').get_json()['notes']] == [day['id']]
    assert as_user('ben').get('/api/mentions?type=track&id=trk42').get_json()['notes'] == []
    # Another track, or a kind of record the notebook does not link to, has none.
    assert ana.get('/api/mentions?type=track&id=other').get_json()['notes'] == []
    assert ana.get('/api/mentions?type=secret&id=trk42').get_json()['notes'] == []


def test_an_export_links_a_track_to_the_genome_browser(monkeypatch):
    from app import exporting
    monkeypatch.setenv('GENOME_URL', '/genome')
    ctx = exporting.Context.__new__(exporting.Context)
    ctx.origin = 'https://trellis.example'
    assert ctx.track_link('trk42') == 'https://trellis.example/genome/?track=trk42'
