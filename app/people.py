"""
Who is signed in, and whose notebooks they may open.

The notebook has no accounts of its own: it runs inside Trellis Tools,
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
    def in_demo(self) -> bool:
        """In the suite's teaching demo: every lab of theirs is one of the demo's (demo_lab_ids)."""
        cached = self.__dict__.get('_in_demo')
        if cached is None:
            mine = self.lab_ids
            cached = not self.is_admin and bool(mine) and mine <= demo_lab_ids()
            self.__dict__['_in_demo'] = cached
        return cached

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
        """
        May open this person's notebook (beyond what is shared): who sees whose.

        - Themselves, and an administrator of the suite: always.
        - A lab admin: everyone in a lab they are lab admin of, lab leads and other lab admins too.
        - A lab lead: everyone in a lab they lead except a lab admin. A notebook is one thing, not
          one per lab, so someone who is lab admin of any lab stays closed to lab leads.
        - A member: only their own.

        Someone who has left (archived) is open again to their labs' leads and lab admins, so the
        work of a lab admin who goes stays reachable rather than only by a restore from backup.
        """
        if not username:
            return False
        if username == self.username or self.is_admin:
            return True
        member = membership(username)
        if not member:
            return False
        theirs = {m['lab'].casefold() for m in member.get('labs', []) if m.get('lab')}
        their_rank = max((rank(m) for m in member.get('labs', [])), default=0)
        gone = username in archived()
        mine = self.labs or ([{'lab': self.lab, 'role': self.lab_role}] if self.lab else [])
        for lab in mine:
            if not lab.get('lab') or lab['lab'].casefold() not in theirs:
                continue
            here = rank(lab)
            if here == 2:
                return True
            if here == 1 and (their_rank < 2 or gone):
                return True
        return False

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
    'member') and 'admin': whether they are that lab's lab admin (a lab lead
    with lab_admin set in the suite). From the suite: lab_members, or the
    members table of a suite from before people could be in several labs.
    """
    rows = _read(suite_path(), 'SELECT m.username, labs.name AS lab, labs.id AS lab_id, m.role, m.lab_admin '
                               'FROM lab_members m JOIN labs ON labs.id = m.lab_id ORDER BY m.joined_at, m.rowid')
    if not rows:
        # A suite from before lab admins were told apart from lab leads.
        rows = _read(suite_path(), 'SELECT m.username, labs.name AS lab, labs.id AS lab_id, m.role, 0 AS lab_admin '
                                   'FROM lab_members m JOIN labs ON labs.id = m.lab_id ORDER BY m.joined_at, m.rowid')
    if not rows:
        rows = _read(suite_path(), 'SELECT members.username, labs.name AS lab, labs.id AS lab_id, members.role, '
                                   '0 AS lab_admin FROM members JOIN labs ON labs.id = members.lab_id')
    found: Dict[str, dict] = {}
    for r in rows:
        role = r['role'] or 'member'
        lab = {'lab': r['lab'], 'lab_id': str(r['lab_id']) if r['lab_id'] is not None else None,
               'role': role, 'admin': role == 'lab_lead' and bool(r['lab_admin'])}
        found.setdefault(r['username'], {**lab, 'labs': []})['labs'].append(lab)
    return found


def rank(lab: dict) -> int:
    """Standing in one lab: 2 its lab admin, 1 a lab lead, 0 a member (the suite's RANK)."""
    if lab.get('admin'):
        return 2
    return 1 if lab.get('role') == 'lab_lead' else 0


def _names(member: Optional[dict]) -> set:
    return {m['lab'].casefold() for m in (member or {}).get('labs', []) if m.get('lab')}


def membership(username: str) -> Optional[dict]:
    return memberships().get(username)


def labs() -> List[dict]:
    """The suite's labs: [{'id': id as text, 'name': name}], by name."""
    return [{'id': str(r['id']), 'name': r['name']}
            for r in _read(suite_path(), 'SELECT id, name FROM labs ORDER BY name COLLATE NOCASE')]


def chair_group_labs(lab_ids) -> set:
    """
    These labs and the labs they work with: every lab in a chair group with any
    of them (the suite's labs.chair_group_id). A lab in no chair group works
    with itself alone, as does every lab in a suite from before chair groups.
    """
    lab_ids = {str(i) for i in lab_ids if i}
    rows = _read(suite_path(), 'SELECT id, chair_group_id FROM labs')
    groups = {str(r['chair_group_id']) for r in rows if str(r['id']) in lab_ids and r['chair_group_id']}
    return lab_ids | {str(r['id']) for r in rows if r['chair_group_id'] and str(r['chair_group_id']) in groups}


def archived() -> Dict[str, str]:
    """
    People who have left: archived by their lab admin or an administrator on the
    suite's dashboard (suite.db: archived), username -> when (UTC). Their work
    stays for their labs; they are left out of lists of people to choose from.
    """
    return {r['username']: r['archived_at'] for r in _read(suite_path(), 'SELECT username, archived_at FROM archived')}


def colleagues(username: str) -> List[str]:
    """Everyone in a lab of this person's chair group(s) (their own labs included), but them and those who left, by name."""
    member = membership(username) or {}
    labs = chair_group_labs(m['lab_id'] for m in member.get('labs', []))
    gone = archived()
    return sorted(u for u, m in memberships().items()
                  if u != username and u not in gone and labs & {x['lab_id'] for x in m.get('labs', []) if x.get('lab_id')})


def demo_lab_ids() -> set:
    """
    The teaching demo's labs: those in the chair group the suite records as the demo's (suite.db
    settings 'demo.chair_group', set by the suite's demo/accounts.py). Its people see the demo's
    notebooks and protocols only: not every lab's protocols, nor what a real lab shares with them.
    """
    rows = _read(suite_path(), "SELECT value FROM settings WHERE key = 'demo.chair_group'")
    group = rows[0]['value'] if rows else None
    if not group:
        return set()
    return {str(r['id']) for r in _read(suite_path(), 'SELECT id FROM labs WHERE chair_group_id = ?', (group,))}


def demo_people() -> set:
    demo = demo_lab_ids()
    return {u for u, m in memberships().items()
            if demo and any(x.get('lab_id') in demo for x in m.get('labs', []))} if demo else set()


def people_for(person: 'Person') -> List[str]:
    """people(), but only the demo's for someone in the demo."""
    found = people()
    if person is not None and person.in_demo:
        demo = demo_people()
        found = [u for u in found if u in demo]
    return found


def labs_for(person: 'Person') -> List[dict]:
    """labs(), but only the demo's for someone in the demo."""
    found = labs()
    if person is not None and person.in_demo:
        demo = demo_lab_ids()
        found = [lab for lab in found if lab['id'] in demo]
    return found


def lab_name(lab_id: Optional[str]) -> Optional[str]:
    return next((lab['name'] for lab in labs() if lab['id'] == lab_id), None) if lab_id else None


def people() -> List[str]:
    """Everyone with an account who has not left, by name."""
    gone = archived()
    return [r['username'] for r in _read(directory_path(), 'SELECT username FROM users ORDER BY username')
            if r['username'] not in gone]


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
