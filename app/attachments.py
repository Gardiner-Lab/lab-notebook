"""
Photos and files attached to notes, as in Trilium.

An attachment belongs to one note, and anyone who can read the note can see
it; only someone who can change the note adds or removes them. Files are kept
in the notebook's database, so the suite's backup takes them with the rest.

Any kind of file can be attached: Word, PowerPoint, Excel, PDF, data files.
Photos in common formats are shown in pages, and PDFs open in the browser's
own PDF viewer. Everything else is sent as a download, with its real type so
it opens in Word, PowerPoint and so on; SVG, HTML and other types a browser
could run as a page are sent as plain bytes, so a file cannot run scripts in
the notebook for whoever opens it. Removing an attachment takes it off the note's
list, but keeps it for the versions in the note's history that show it.

A photo can be marked up (drawn and written on) in the page. That never changes
the photo: the marked-up picture is a new attachment, made from the original,
and the marks are kept with it so they can be changed again later. Marking up
a marked-up picture again replaces it on the list; the original stays.
"""

import hashlib
import json
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
# Opened in the browser's own viewer, in a tab of its own.
PREVIEW_TYPES = {'application/pdf'}
# Never sent as what they are: a browser could run them as a page.
RISKY = ('text/html', 'application/xhtml', 'image/svg', 'text/xml', 'application/xml',
         'text/javascript', 'application/javascript', 'application/x-javascript')
# What a file is, to show it with the right icon.
KINDS = [('pdf', ('application/pdf',)),
         ('word', ('msword', 'wordprocessingml', 'opendocument.text', 'rtf')),
         ('powerpoint', ('powerpoint', 'presentationml', 'opendocument.presentation')),
         ('excel', ('excel', 'spreadsheetml', 'opendocument.spreadsheet', 'text/csv', 'tab-separated')),
         ('archive', ('zip', 'x-7z', 'x-tar', 'gzip', 'x-rar')),
         ('sequence', ('genbank', 'x-snapgene', 'fasta')),
         ('text', ('text/',))]
mimetypes.add_type('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')
for ext in ('.gb', '.gbk', '.ape'):
    mimetypes.add_type('chemical/x-genbank', ext)
mimetypes.add_type('application/x-snapgene', '.dna')
mimetypes.add_type('chemical/x-fasta', '.fasta')
_SIGNATURES = [(b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'), (b'GIF8', 'image/gif'),
               (b'BM', 'image/bmp')]


def _sniff(data: bytes, filename: str) -> str:
    """The type a file really is, by its first bytes for photos; by its name otherwise."""
    for magic, kind in _SIGNATURES:
        if data.startswith(magic):
            return kind
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    if data.startswith(b'%PDF-'):
        return 'application/pdf'
    guessed = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    # A file named like a photo or a PDF but not one is not shown as one.
    return 'application/octet-stream' if guessed in INLINE_TYPES | PREVIEW_TYPES else guessed


def kind(mime: str) -> str:
    if mime in INLINE_TYPES:
        return 'image'
    for name, marks in KINDS:
        if any(m in mime for m in marks):
            return name
    return 'file'


def sent_as(mime: str) -> str:
    """The type a file is sent with: its own, unless a browser could run it."""
    return 'application/octet-stream' if mime.startswith(RISKY) else mime


def _clean_name(filename: str) -> str:
    name = re.sub(r'[\x00-\x1f/\\]', '_', (filename or '').strip())[:200]
    return name or 'file'


def _summary(row) -> dict:
    keys = row.keys()
    return {'id': row['id'], 'note_id': row['note_id'], 'filename': row['filename'], 'mime': row['mime'],
            'size': row['size'], 'image': row['mime'] in INLINE_TYPES,
            'preview': row['mime'] in PREVIEW_TYPES, 'kind': kind(row['mime']),
            'created_by': row['created_by'], 'created_at': row['created_at'],
            # Marked up from another photo of the note: which.
            'source_id': row['source_id'] if 'source_id' in keys else None}


def _note_any(conn, note_id: str):
    """The note, deleted or not: its photos still show where they were used."""
    row = conn.execute('SELECT * FROM notes WHERE id = ?', (note_id,)).fetchone()
    if row is None:
        raise notes.NotFound('Note not found')
    return row


def listed(conn, note_id: str) -> List[dict]:
    return [_summary(r) for r in conn.execute(
        'SELECT id, note_id, filename, mime, size, created_by, created_at, source_id FROM attachments '
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
            'inline': row['mime'] in INLINE_TYPES, 'preview': row['mime'] in PREVIEW_TYPES,
            'sha256': row['sha256']}


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
    rows = conn.execute('SELECT * FROM attachments WHERE note_id = ? AND deleted_at IS NULL', (from_note,)).fetchall()
    for r in rows:
        new = content_mod.new_id() + content_mod.new_id()
        conn.execute('INSERT INTO attachments (id, note_id, filename, mime, size, sha256, data, created_by, markup) '
                     'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (new, to_note, r['filename'], r['mime'], r['size'], r['sha256'], r['data'], username, r['markup']))
        mapping[r['id']] = new
    # A marked-up copy is made from the copy's own original, when it came along.
    for r in rows:
        if r['source_id'] and r['source_id'] in mapping:
            conn.execute('UPDATE attachments SET source_id = ? WHERE id = ?', (mapping[r['source_id']], mapping[r['id']]))
    return mapping


# --- marking up photos -------------------------------------------------------------

MARK_KINDS = ('pen', 'highlight', 'line', 'arrow', 'rect', 'ellipse', 'text')
MAX_MARKS = 2000
MAX_POINTS = 50_000
_COLOUR = re.compile(r'^#[0-9a-fA-F]{6}$')


def _marks(raw) -> List[dict]:
    """The marks drawn on a photo, checked: shapes with a colour, a width and their points."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError('The marks could not be read')
    if not isinstance(raw, list) or len(raw) > MAX_MARKS:
        raise ValueError(f'Marks must be a list of at most {MAX_MARKS}')
    marks, points = [], 0

    def number(v):
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise ValueError('A mark has a position that is not a number')
        if n != n or abs(n) > 1e6:
            raise ValueError('A mark is off the picture')
        return round(n, 1)
    for m in raw:
        if not isinstance(m, dict) or m.get('t') not in MARK_KINDS:
            raise ValueError('A mark of an unknown kind')
        pts = [number(v) for v in (m.get('p') or [])]
        points += len(pts)
        if points > MAX_POINTS or len(pts) % 2 or not pts:
            raise ValueError('A mark has too many points, or none')
        mark = {'t': m['t'], 'c': m.get('c') if _COLOUR.match(str(m.get('c') or '')) else '#ef4444',
                'w': min(max(number(m.get('w') or 4), 0.5), 400), 'p': pts}
        if m['t'] == 'text':
            mark['s'] = str(m.get('s') or '')[:500]
            if not mark['s'].strip():
                continue
        marks.append(mark)
    return marks


def marked(person: Person, att_id: str) -> Dict:
    """What a photo is marked up from, and its marks: what the editor opens to change them."""
    with connect() as conn:
        row = conn.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
        if row is None:
            raise notes.NotFound('No such file')
        note = _note_any(conn, row['note_id'])
    if not notes.can_view(person, note):
        raise notes.Forbidden('This file is not yours to open')
    if row['mime'] not in INLINE_TYPES:
        raise ValueError('Only photos can be marked up')
    source = row
    if row['source_id']:
        with connect() as conn:
            source = conn.execute('SELECT * FROM attachments WHERE id = ?', (row['source_id'],)).fetchone() or row
    return {'id': row['id'], 'source_id': source['id'], 'mime': source['mime'],
            'marks': json.loads(row['markup']) if row['source_id'] and row['markup'] else []}


def mark_up(person: Person, att_id: str, picture: bytes, marks) -> Dict:
    """
    Keep a photo marked up: `picture` is it with the marks drawn on (the page
    draws it), a new attachment of the note, made from the original photo.
    Marked up again, the earlier marked-up picture leaves the note's list.
    """
    marks = _marks(marks)
    with connect() as conn:
        row = conn.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
        if row is None:
            raise notes.NotFound('No such file')
        note = notes._row(conn, row['note_id'])
    if not notes.can_edit(person, note):
        raise notes.Forbidden('You cannot change the photos of this note')
    if row['mime'] not in INLINE_TYPES:
        raise ValueError('Only photos can be marked up')
    if not picture or len(picture) > MAX_BYTES:
        raise ValueError(f'The marked-up picture must be under {MAX_BYTES // (1024 * 1024)} MB')
    mime = _sniff(picture, 'marked.png')
    if mime not in ('image/png', 'image/jpeg'):
        raise ValueError('The marked-up picture must be a PNG or JPEG')
    source = row['source_id'] or row['id']
    with connect() as conn:
        original = conn.execute('SELECT filename FROM attachments WHERE id = ?', (source,)).fetchone()
        stem = (original['filename'] if original else row['filename']).rsplit('.', 1)[0]
        name = _clean_name(f"{stem} (marked up).{'png' if mime == 'image/png' else 'jpg'}")
        new_id = content_mod.new_id() + content_mod.new_id()
        conn.execute('INSERT INTO attachments (id, note_id, filename, mime, size, sha256, data, created_by, '
                     'source_id, markup) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (new_id, row['note_id'], name, mime, len(picture), hashlib.sha256(picture).hexdigest(),
                      picture, person.username, source, json.dumps(marks)))
        if row['source_id']:
            # The marked-up picture it replaces: off the list, kept for the history.
            conn.execute('UPDATE attachments SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ? '
                         'WHERE id = ? AND deleted_at IS NULL', (person.username, row['id']))
        return next(a for a in listed(conn, row['note_id']) if a['id'] == new_id)


def size_label(n: Optional[int]) -> str:
    n = n or 0
    return f'{n / 1048576:.1f} MB' if n >= 1048576 else f'{max(1, round(n / 1024))} kB'
