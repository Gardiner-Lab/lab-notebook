"""
Who is signed in, and whose notebooks they may open.

The notebook has no accounts of its own: it runs inside the Gardiner Lab suite,
whose proxy says who is signed in in an X-Suite-User header (set on every
request, and stripped from what the browser sends). Administrators are marked
in the suite's account directory (MoClo's users table); labs, and who leads
them, are in the suite's own database. Both are read, never written.

Only run this behind the suite's proxy: reachable directly, anyone could set
the header themselves.
"""

import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional

from flask import g, request

HEADER = 'X-Suite-User'


@dataclass
class Person:
    username: str
    is_admin: bool = False
    lab: Optional[str] = None
    lab_role: str = 'member'          # 'lab_lead' or 'member'

    @property
    def role(self) -> str:
        if self.is_admin:
            return 'admin'
        return 'lab_lead' if self.lab_role == 'lab_lead' else 'member'

    @property
    def is_lab_lead(self) -> bool:
        return self.role == 'lab_lead'

    def oversees(self, username: Optional[str]) -> bool:
        """May open this person's notebook: themselves, an admin, or their lab's lead."""
        if not username:
            return False
        if username == self.username or self.is_admin:
            return True
        if not self.is_lab_lead or not self.lab:
            return False
        other = membership(username)
        return bool(other and other.get('lab') and other['lab'].casefold() == self.lab.casefold())

    def to_dict(self) -> dict:
        return {'username': self.username, 'role': self.role, 'lab': self.lab,
                'is_admin': self.is_admin}


def _read(path: str, sql: str, args=()) -> List[sqlite3.Row]:
    if not path or not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def directory_path() -> str:
    return os.environ.get('MOCLO_DATABASE_PATH', '/moclo/moclo.db')


def suite_path() -> str:
    return os.environ.get('SUITE_DATABASE_PATH', '/suite/suite.db')


def account(username: str) -> Optional[dict]:
    """The person's entry in the suite's account directory."""
    rows = _read(directory_path(), 'SELECT * FROM users WHERE username = ?', (username,))
    if not rows:
        return None
    row = dict(rows[0])
    row['is_admin'] = bool(row.get('is_admin'))
    return row


def memberships() -> Dict[str, dict]:
    """username -> {'lab': name, 'role': 'lab_lead' | 'member'}, from the suite."""
    rows = _read(suite_path(), 'SELECT members.username, labs.name AS lab, members.role FROM members '
                               'LEFT JOIN labs ON labs.id = members.lab_id')
    return {r['username']: {'lab': r['lab'], 'role': r['role']} for r in rows}


def membership(username: str) -> Optional[dict]:
    return memberships().get(username)


def people() -> List[str]:
    """Everyone with an account, by name."""
    return [r['username'] for r in _read(directory_path(), 'SELECT username FROM users ORDER BY username')]


def current() -> Optional[Person]:
    """Whoever the suite says is signed in, for this request."""
    if 'person' in g:
        return g.person
    username = request.headers.get(HEADER, '').strip()
    person = None
    if username:
        entry = account(username)
        member = membership(username) or {}
        person = Person(username=username, is_admin=bool(entry and entry['is_admin']),
                        lab=member.get('lab'), lab_role=member.get('role') or 'member')
    g.person = person
    return person
