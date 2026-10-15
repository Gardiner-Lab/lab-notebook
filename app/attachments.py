"""
Photos and files attached to notes, as in Trilium.

An attachment belongs to one note, and anyone who can read the note can see
it; only someone who can change the note adds or removes them. Files are kept
in the notebook's database, so the suite's backup takes them with the rest.

Photos in common formats are shown in pages. Everything else, SVG and HTML
included, is only ever sent as a download, so a file cannot run scripts in the
notebook for whoever opens it. Removing an attachment takes it off the note's
list, but keeps it for the versions in the note's history that show it.
"""

import hashlib
import mimetypes
import re
from typing import Dict, List, Optional

from app import content as content_mod
from app import notes
from app.db import connect
from app.people import Person

MAX_BYTES = 25 * 1024 * 1024
# Shown in pages. Anything else is downloaded.
INLINE_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'}
_SIGNATURES = [(b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'), (b'GIF8', 'image/gif'),
               (b'BM', 'image/bmp')]


def _sniff(data: bytes, filename: str) -> str:
    """The type a file really is, by its first bytes for photos; by its name otherwise."""
    for magic, kind in _SIGNATURES:
        if data.startswith(magic):
            return kind
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    guessed = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    # A file named like a photo but not one is not shown as one.
    return 'application/octet-stream' if guessed in INLINE_TYPES else guessed


def _clean_name(filename: str) -> str:
    name = re.sub(r'[\x00-\x1f/\\]', '_', (filename or '').strip())[:200]
    return name or 'file'


def _summary(row) -> dict:
    return {'id': row['id'], 'note_id': row['note_id'], 'filename': row['filename'], 'mime': row['mime'],
            'size': row['size'], 'image': row['mime'] in INLINE_TYPES,
            'created_by': row['created_by'], 'created_at': row['created_at']}


def _note_any(conn, note_id: str):
    """The note, deleted or not: its photos still show where they were used."""
    row = conn.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    if row is None:
        raise notes.NotFound('Note not found')
    return row


def listed(conn, note_id: str) -> List[dict]:
    return [_summary(r) for r in conn.execute(
        'SELECT id, note_id, filename, mime, size, created_by, created_at FROM attachments '
        'WHERE note_id = ? AND deleted_at IS NULL ORDER BY created_at, rowid', (note_id,))]


def add(person: Person, note_id: str, files: List[tuple]) -> List[dict]:
    """Attach files, given as (filename, bytes), to a note this person may change."""
    with connect() as conn:
        note = notes._row(conn, note_id)
    if not notes.can_edit(person, note):
        raise notes.Forbidden('You cannot add files to this note')
    if not files:
        raise ValueError('Choose a file to attach')
    added = []
    with connect() as conn:
        for filename, data in files:
            if len(data) > MAX_BYTES:
                raise ValueError(f'{_clean_name(filename)} is larger than {MAX_BYTES // (1024 * 1024)} MB')
            if not data:
                raise ValueError(f'{_clean_name(filename)} is empty')
            att_id = content_mod.new_id() + content_mod.new_id()
            name = _clean_name(filename)
            conn.execute('INSERT INTO attachments (id, note_id, filename, mime, size, sha256, data, created_by) '
                         'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (att_id, note_id, name, _sniff(data, name), len(data),
                          hashlib.sha256(data).hexdigest(), data, person.username))
            added.append(att_id)
        return [a for a in listed(conn, note_id) if a['id'] in added]


def fetch(person: Person, att_id: str) -> Dict:
    """An attachment's bytes, for someone who may read its note."""
    with connect() as conn:
        row = conn.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
        if row is None:
            raise notes.NotFound('No such file')
        note = _note_any(conn, row['note_id'])
    if not notes.can_view(person, note):
        raise notes.Forbidden('This file is not yours to open')
    return {'data': bytes(row['data']), 'mime': row['mime'], 'filename': row['filename'],
            'inline': row['mime'] in INLINE_TYPES, 'sha256': row['sha256']}


def remove(person: Person, att_id: str) -> None:
    with connect() as conn:
        row = conn.execute('SELECT * FROM attachments WHERE id = ? AND deleted_at IS NULL', (att_id,)).fetchone()
        if row is None:
            raise notes.NotFound('No such file')
        if not notes.can_edit(person, notes._row(conn, row['note_id'])):
            raise notes.Forbidden('You cannot remove files from this note')
        conn.execute('UPDATE attachments SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ? WHERE id = ?',
                     (person.username, att_id))


def copy_all(conn, from_note: str, to_note: str, username: str) -> Dict[str, str]:
    """Give a copied note its own copies of the original's attachments: old id -> new id."""
    mapping: Dict[str, str] = {}
    for r in conn.execute('SELECT * FROM attachments WHERE note_id = ? AND deleted_at IS NULL', (from_note,)).fetchall():
        new = content_mod.new_id() + content_mod.new_id()
        conn.execute('INSERT INTO attachments (id, note_id, filename, mime, size, sha256, data, created_by) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     (new, to_note, r['filename'], r['mime'], r['size'], r['sha256'], r['data'], username))
        mapping[r['id']] = new
    return mapping


def size_label(n: Optional[int]) -> str:
    n = n or 0
    return f'{n / 1048576:.1f} MB' if n >= 1048576 else f'{max(1, round(n / 1024))} kB'
