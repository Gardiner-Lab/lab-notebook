import json
import os
import sqlite3
import tempfile

import pytest

os.environ['NOTEBOOK_NO_APP'] = '1'


def _make(path, script, rows=()):
    conn = sqlite3.connect(path)
    conn.executescript(script)
    for sql, args in rows:
        conn.execute(sql, args)
    conn.commit()
    conn.close()


@pytest.fixture()
def world(monkeypatch):
    """A notebook beside a suite: two labs, a lead, an admin, MoClo and the editor."""
    d = tempfile.mkdtemp()
    paths = {k: os.path.join(d, f'{k}.db') for k in ('notebook', 'moclo', 'suite', 'editor')}
    _make(paths['moclo'],
          'CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE, is_admin INTEGER DEFAULT 0);'
          'CREATE TABLE saved_items (id TEXT PRIMARY KEY, user_id TEXT, item_type TEXT, ref_id TEXT, '
          'title TEXT, summary TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);',
          [('INSERT INTO users VALUES (?, ?, ?)', (u, u, 1 if u == 'boss' else 0))
           for u in ('ana', 'ben', 'lead', 'boss', 'zoe', 'olead')]
          + [('INSERT INTO saved_items (id, user_id, item_type, title, summary) VALUES (?, ?, ?, ?, ?)',
              ('s1', 'ana', 'plasmid', 'pGFP L1', json.dumps({'reactions': [{
                  'label': 'Level 1', 'level': '1', 'enzyme': 'BsaI',
                  'fragments': [{'name': 'pL1V', 'size': 5000, 'role': 'vector'},
                                {'name': 'p35S', 'size': 3500, 'role': 'insert'},
                                {'name': 'GFP', 'size': 3200, 'role': 'insert'}]}]})))])
    _make(paths['suite'],
          'CREATE TABLE labs (id INTEGER PRIMARY KEY, name TEXT);'
          'CREATE TABLE members (username TEXT PRIMARY KEY, lab_id INTEGER, role TEXT);',
          [('INSERT INTO labs VALUES (1, ?)', ('Gardiner Lab',)), ('INSERT INTO labs VALUES (2, ?)', ('Other Lab',))]
          + [('INSERT INTO members VALUES (?, ?, ?)', m) for m in
             [('ana', 1, 'member'), ('ben', 1, 'member'), ('lead', 1, 'lab_lead'), ('zoe', 2, 'member'),
              ('olead', 2, 'lab_lead')]])
    _make(paths['editor'],
          'CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT);'
          'CREATE TABLE sequences (id TEXT PRIMARY KEY, name TEXT, sequence TEXT, circular INTEGER, '
          'shared INTEGER, owner_id TEXT, confirmed_at TEXT, glycerol_stock TEXT, '
          'updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);',
          [('INSERT INTO users VALUES (?, ?)', (u, u)) for u in ('ana', 'zoe')]
          + [('INSERT INTO sequences (id, name, sequence, circular, shared, owner_id) VALUES (?, ?, ?, 1, ?, ?)', s)
             for s in [('p1', 'pGFP-35S', 'ACGT' * 100, 1, 'ana'), ('p2', 'pSecret', 'ACGT' * 50, 0, 'zoe')]])
    monkeypatch.setenv('NOTEBOOK_DATABASE_PATH', paths['notebook'])
    monkeypatch.setenv('MOCLO_DATABASE_PATH', paths['moclo'])
    monkeypatch.setenv('SUITE_DATABASE_PATH', paths['suite'])
    monkeypatch.setenv('EDITOR_DATABASE_PATH', paths['editor'])
    from app.main import create_app
    app = create_app()
    app.testing = True
    return {'app': app, 'paths': paths}


@pytest.fixture()
def as_user(world):
    """as_user('ana') -> a client signed in as ana, the way the suite's proxy does it."""
    def make(username):
        client = world['app'].test_client()
        client.environ_base['HTTP_X_SUITE_USER'] = username
        return client
    return make
