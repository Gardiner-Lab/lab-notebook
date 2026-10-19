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
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from flask import g, request

HEADER = 'X-Suite-User'


@dataclass
class Person:
    username: str
    is_admin: bool = False
    lab: Optional[str] = None
    lab_role: str = 'member'          # 'lab_lead' or 'member'
    lab_id: Optional[str] = None      # the suite's id for the lab, as text: what shares name
    # All their labs, first joined first: {'lab', 'lab_id', 'role'}; lab, lab_role and lab_id are the first's.
    labs: List[dict] = field(default_factory=list)

    @property
    def lab_ids(self) -> set:
        return {m['lab_id'] for m in self.labs if m.get('lab_id')} or ({self.lab_id} if self.lab_id else set())

    @property
    def led_lab_ids(self) -> set:
        return {m['lab_id'] for m in self.labs if m.get('lab_id') and m['role'] == 'lab_lead'}

    @property
    def role(self) -> str:
        if self.is_admin:
            return 'admin'
        return 'lab_lead' if self.lab_role == 'lab_lead' or any(m['role'] == 'lab_lead' for m in self.labs) \
            else 'member'

    @property
    def is_lab_lead(self) -> bool:
        """Leads at least one of their labs."""
        return self.role == 'lab_lead'

    def lab_names(self, led_only: bool = False) -> set:
        """Their labs (casefolded names); led_only, the ones they lead."""
        labs = self.labs or ([{'lab': self.lab, 'role': self.lab_role}] if self.lab else [])
        return {m['lab'].casefold() for m in labs if m.get('lab') and (not led_only or m['role'] == 'lab_lead')}

    def leads(self, lab: Optional[str]) -> bool:
        return bool(lab) and lab.casefold() in self.lab_names(led_only=True)

    def shares_lab(self, username: Optional[str]) -> bool:
        """In a lab together with this person."""
        if not username:
            return False
        if username == self.username:
            return True
        return bool(self.lab_names() & _names(membership(username)))

    def oversees(self, username: Optional[str]) -> bool:
        """May act for this person: themselves, an admin, or a lead of a lab they are in."""
        if not username:
            return False
        if username == self.username or self.is_admin:
            return True
        led = self.lab_names(led_only=True)
        return bool(led and led & _names(membership(username)))

    def to_dict(self) -> dict:
        return {'username': self.username, 'role': self.role, 'lab': self.lab, 'lab_id': self.lab_id,
                'labs': [{'lab': m['lab'], 'lab_id': m['lab_id'], 'role': m['role']} for m in self.labs],
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
    """
    username -> {'lab', 'lab_id', 'role'} of their first lab, and 'labs': all
    of them, first joined first, each with their role there ('lab_lead' or
    'member'; a lab admin is a lab lead). From the suite: lab_members, or the
    members table of a suite from before people could be in several labs.
    """
    rows = _read(suite_path(), 'SELECT m.username, labs.name AS lab, labs.id AS lab_id, m.role '
                               'FROM lab_members m JOIN labs ON labs.id = m.lab_id ORDER BY m.joined_at, m.rowid')
    if not rows:
        rows = _read(suite_path(), 'SELECT members.username, labs.name AS lab, labs.id AS lab_id, members.role '
                                   'FROM members JOIN labs ON labs.id = members.lab_id')
    found: Dict[str, dict] = {}
    for r in rows:
        lab = {'lab': r['lab'], 'lab_id': str(r['lab_id']) if r['lab_id'] is not None else None,
               'role': r['role'] or 'member'}
        found.setdefault(r['username'], {**lab, 'labs': []})['labs'].append(lab)
    return found


def _names(member: Optional[dict]) -> set:
    return {m['lab'].casefold() for m in (member or {}).get('labs', []) if m.get('lab')}


def membership(username: str) -> Optional[dict]:
    return memberships().get(username)


def labs() -> List[dict]:
    """The suite's labs: [{'id': id as text, 'name': name}], by name."""
    return [{'id': str(r['id']), 'name': r['name']}
            for r in _read(suite_path(), 'SELECT id, name FROM labs ORDER BY name COLLATE NOCASE')]


def lab_name(lab_id: Optional[str]) -> Optional[str]:
    return next((lab['name'] for lab in labs() if lab['id'] == lab_id), None) if lab_id else None


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
                        lab=member.get('lab'), lab_role=member.get('role') or 'member',
                        lab_id=member.get('lab_id'), labs=member.get('labs') or [])
    g.person = person
    return person
