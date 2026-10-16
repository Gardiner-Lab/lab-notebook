"""
Exports: a note and everything under it, as a PDF or a Word document.

Anyone who can read a note can export it, from any level of the tree: a page,
a day, a month, a whole notebook, a protocol, a folder or the whole library.
What is under it comes along, as far as the person may see it (another lab's
protocols in a library folder are left out). Photos are shown where they are,
a PDF's pages are put in where it is attached, and other files are embedded in
the PDF, or put beside the Word document in a zip.

An export can take a while (a year of a notebook, with its photos), so it runs
as a job: started, followed, then fetched. Jobs are kept in this process (the
notebook runs as one worker) and their files for an hour.
"""

import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app

from app import notes
from app.db import connect
from app.people import Person

log = logging.getLogger(__name__)

FORMATS = ('pdf', 'docx')
MAX_NOTES = 5000
KEEP_SECONDS = 3600
# Exports at once; more wait their turn.
_slots = threading.Semaphore(2)
_jobs: Dict[str, dict] = {}
_threads: Dict[str, threading.Thread] = {}
_lock = threading.Lock()

TYPE_NAMES = {'notebook': 'Notebook', 'library': 'Protocol library', 'year': 'Year', 'month': 'Month',
              'day': 'Day', 'page': 'Page', 'folder': 'Folder', 'protocol': 'Protocol'}
# Shown as text in the export: a table or a list of lines.
TABLE_TYPES = ('text/csv', 'text/tab-separated-values')
TEXT_TYPES = ('text/', 'chemical/x-genbank', 'chemical/x-fasta')
IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp'}


@dataclass
class Entry:
    """One note of an export, in the order it is printed."""
    id: str
    title: str
    type: str
    space: str
    owner: Optional[str]
    depth: int
    where: str
    created_by: Optional[str]
    created_at: Optional[str]
    updated_by: Optional[str]
    updated_at: Optional[str]
    revision: int
    labels: List[str]
    content: list
    attachments: List[dict]
    # The id of the note already printed, when this one is a second place of it.
    repeat_of: Optional[str] = None
    has_children: bool = False


@dataclass
class Context:
    person: Person
    tz: object
    origin: str
    base: str
    title: str
    subtitle: str
    entries: List[Entry]
    included: set = field(default_factory=set)
    stamp: str = ''

    def when(self, stamp: Optional[str]) -> str:
        """A stored UTC time, in the exporter's time zone."""
        if not stamp:
            return ''
        try:
            moment = datetime.strptime(str(stamp)[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=dt_timezone.utc)
        except ValueError:
            return str(stamp)[:16]
        return moment.astimezone(self.tz).strftime('%Y-%m-%d %H:%M')

    def absolute(self, path: str) -> str:
        return f'{self.origin}{path}' if path.startswith('/') and self.origin else path

    def note_link(self, note_id: str) -> str:
        if note_id in self.included:
            return f'#n-{note_id}'
        return self.absolute(f'{self.base}/#note={note_id}')

    def plasmid_link(self, plasmid_id: str) -> str:
        editor = os.environ.get('EDITOR_URL', '/editor').rstrip('/')
        return self.absolute(f'{editor}/editor?open={plasmid_id}')

    def seed_link(self, code: str) -> str:
        kinds = {'L': 'line', 'S': 'lot', 'P': 'plant'}
        parts = code.split('-')
        kind = kinds.get(parts[-2] if len(parts) > 1 else '', 'line')
        return self.absolute(f"{os.environ.get('SEEDS_URL', '/seeds').rstrip('/')}/#{kind}={code}")

    def stock_link(self, code: str) -> str:
        parts = code.split('-')
        kind = 'primer' if len(parts) > 1 and parts[-2] == 'O' else 'glycerol'
        return self.absolute(f"{os.environ.get('STOCKS_URL', '/stocks').rstrip('/')}/#{kind}={code}")


# --- what goes in ------------------------------------------------------------------

def _attachments_of(conn, note_id: str) -> List[dict]:
    """The note's files without their bytes: listed (not removed) ones, then any the text still shows."""
    return [dict(r) for r in conn.execute(
        'SELECT id, note_id, filename, mime, size, deleted_at FROM attachments WHERE note_id = ? '
        'ORDER BY created_at, rowid', (note_id,))]


def load(person: Person, att_id: str) -> Optional[dict]:
    """An attachment with its bytes, if this person may read the note it belongs to."""
    with connect() as conn:
        row = conn.execute('SELECT a.*, n.space, n.owner, n.type, n.lab, n.created_by AS note_author, n.id AS nid '
                           'FROM attachments a JOIN notes n ON n.id = a.note_id WHERE a.id = ?', (att_id,)).fetchone()
        if row is None:
            return None
        note = conn.execute('SELECT * FROM notes WHERE id = ?', (row['note_id'],)).fetchone()
    if note is None or not notes.can_view(person, note):
        return None
    return {'id': row['id'], 'filename': row['filename'], 'mime': row['mime'], 'size': row['size'],
            'data': bytes(row['data'])}


def collect(person: Person, root_id: str, children: bool = True, progress=None) -> Context:
    with connect() as conn:
        root = notes._row(conn, root_id)
    if not notes.can_view(person, root):
        raise notes.Forbidden('This notebook is not yours to open')
    entries: List[Entry] = []
    printed: Dict[str, str] = {}
    container = root['type'] in ('notebook', 'library')

    def add(row, depth: int, trail: tuple):
        if len(entries) >= MAX_NOTES:
            raise ValueError(f'More than {MAX_NOTES} pages: export a part of it at a time')
        kids = notes.children(person, row['id']) if children else []
        with connect() as conn:
            full = conn.execute('SELECT * FROM notes WHERE id = ?', (row['id'],)).fetchone()
            path = notes._path(conn, row['id'])
            labels = [f"#{a['name']}{'=' + a['value'] if a['value'] else ''}" for a in conn.execute(
                "SELECT name, value FROM attributes WHERE note_id = ? AND type = 'label' ORDER BY position, rowid",
                (row['id'],))
                if a['name'] not in ('dateNote', 'monthNote', 'yearNote', 'notebookRoot', 'protocolLibrary', 'seed')]
            files = _attachments_of(conn, row['id'])
        entries.append(Entry(
            id=full['id'], title=full['title'], type=full['type'], space=full['space'], owner=full['owner'],
            depth=depth, where=' › '.join(p['title'] for p in path[:-1]),
            created_by=full['created_by'], created_at=full['created_at'], updated_by=full['updated_by'],
            updated_at=full['updated_at'], revision=full['revision'], labels=labels,
            content=json.loads(full['content'] or '[]') if full['id'] not in printed else [],
            attachments=files if full['id'] not in printed else [],
            repeat_of=printed.get(full['id']), has_children=bool(kids)))
        if progress:
            progress(len(entries))
        if full['id'] in printed:
            return                      # a second place of a note: printed once, pointed to here
        printed[full['id']] = full['id']
        for kid in kids:
            if kid['id'] in trail:
                continue
            with connect() as conn:
                kid_row = conn.execute('SELECT * FROM notes WHERE id = ?', (kid['id'],)).fetchone()
            add(kid_row, depth + 1, trail + (kid['id'],))

    if container:
        for kid in (notes.children(person, root_id) if children else []):
            with connect() as conn:
                kid_row = conn.execute('SELECT * FROM notes WHERE id = ?', (kid['id'],)).fetchone()
            add(kid_row, 0, (root_id, kid['id']))
        title = root['title']
        subtitle = 'Protocol library' if root['type'] == 'library' else f"{root['owner']}'s notebook"
    else:
        add(root, 0, (root_id,))
        with connect() as conn:
            path = notes._path(conn, root_id)
        title = root['title']
        subtitle = ' › '.join(p['title'] for p in path[:-1])
    ctx = Context(person=person, tz=dt_timezone.utc, origin='', base='', title=title, subtitle=subtitle,
                  entries=entries)
    ctx.included = {e.id for e in entries}
    return ctx


# --- files -----------------------------------------------------------------------------

def kind_name(mime: str, filename: str) -> str:
    from app import attachments
    names = {'pdf': 'PDF', 'word': 'Word document', 'powerpoint': 'PowerPoint presentation',
             'excel': 'spreadsheet', 'archive': 'archive', 'sequence': 'sequence file', 'text': 'text file',
             'image': 'picture', 'file': 'file'}
    return names.get(attachments.kind(mime), 'file')


def size_label(n: int) -> str:
    from app import attachments
    return attachments.size_label(n)


def safe_filename(title: str, ext: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', title or 'Export').strip().rstrip('.')[:120] or 'Export'
    return f'{name}.{ext}'


def is_text(mime: str) -> bool:
    return mime.startswith(TEXT_TYPES) and not mime.startswith(('text/html', 'text/xml'))


def text_of(data: bytes, limit: int = 200_000) -> str:
    raw = data[:limit]
    for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', 'replace')


def pdf_reader(data: bytes):
    """A PDF to read pages from, or None when it cannot be (broken, or locked with a password)."""
    import io
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(''):
            return None
        len(reader.pages)
        return reader
    except Exception:          # pypdf raises many kinds of errors on damaged files
        return None


# --- jobs ---------------------------------------------------------------------------------

def _folder() -> str:
    path = os.path.join(tempfile.gettempdir(), 'notebook-exports')
    os.makedirs(path, exist_ok=True)
    return path


def _public(job: dict) -> dict:
    return {k: job[k] for k in ('id', 'status', 'stage', 'done', 'total', 'format', 'filename', 'error', 'title')}


def _tidy() -> None:
    now = time.time()
    with _lock:
        old = [j for j in _jobs.values() if now - j['created'] > KEEP_SECONDS and j['status'] in ('done', 'failed')]
        for j in old:
            _jobs.pop(j['id'], None)
            _threads.pop(j['id'], None)
            if j.get('path'):
                shutil.rmtree(os.path.dirname(j['path']), ignore_errors=True)


def _zone(name: str):
    try:
        return ZoneInfo(name) if name else dt_timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return dt_timezone.utc


def start(person: Person, note_id: str, fmt: str = 'pdf', children: bool = True, timezone: str = '',
          origin: str = '', base: str = '') -> dict:
    if fmt not in FORMATS:
        raise ValueError('Export as pdf or docx')
    with connect() as conn:
        row = notes._row(conn, note_id)
    if not notes.can_view(person, row):
        raise notes.Forbidden('This notebook is not yours to open')
    _tidy()
    origin = origin.rstrip('/') if re.fullmatch(r'https?://[A-Za-z0-9.\-\[\]:]+/?', origin or '') else ''
    job = {'id': secrets.token_hex(12), 'owner': person.username, 'status': 'queued', 'stage': 'Waiting to start',
           'done': 0, 'total': 0, 'format': fmt, 'filename': None, 'error': None, 'title': row['title'],
           'created': time.time(), 'path': None, 'mime': None}
    with _lock:
        _jobs[job['id']] = job
    app = current_app._get_current_object()
    thread = threading.Thread(target=_run, name=f"export-{job['id']}", daemon=True,
                              args=(app, job, person, note_id, fmt, children, _zone(timezone), origin, base))
    _threads[job['id']] = thread
    thread.start()
    return _public(job)


def _run(app, job, person, note_id, fmt, children, tz, origin, base):
    with _slots, app.app_context():
        try:
            job.update(status='working', stage='Gathering the pages')
            ctx = collect(person, note_id, children, progress=lambda n: job.update(total=n))
            ctx.tz, ctx.origin, ctx.base = tz, origin, base
            ctx.stamp = datetime.now(dt_timezone.utc).astimezone(tz).strftime('%Y-%m-%d %H:%M')

            def step(done, stage=None):
                job['done'] = done
                if stage:
                    job['stage'] = stage
            job['stage'] = 'Writing the pages'
            if fmt == 'pdf':
                from app import export_pdf
                data, ext, mime = export_pdf.render(ctx, step), 'pdf', 'application/pdf'
            else:
                from app import export_docx
                data, ext, mime = export_docx.render(ctx, step)
            folder = tempfile.mkdtemp(dir=_folder())
            filename = safe_filename(f'{ctx.title} {ctx.stamp[:10]}', ext)
            path = os.path.join(folder, filename)
            with open(path, 'wb') as out:
                out.write(data)
            job.update(status='done', stage='Ready', filename=filename, path=path, mime=mime, done=job['total'])
        except (notes.Forbidden, notes.NotFound, ValueError) as exc:
            job.update(status='failed', error=str(exc), stage='Failed')
        except Exception as exc:        # anything else: say so, and keep the details in the log
            log.exception('Export %s failed', job['id'])
            job.update(status='failed', error=f'The export failed: {exc}', stage='Failed')


def _own(person: Person, job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None or job['owner'] != person.username:
        raise notes.NotFound('No such export (they are kept for an hour)')
    return job


def status(person: Person, job_id: str) -> dict:
    return _public(_own(person, job_id))


def result(person: Person, job_id: str) -> dict:
    job = _own(person, job_id)
    if job['status'] != 'done' or not job['path'] or not os.path.exists(job['path']):
        raise ValueError('This export is not ready')
    return {'path': job['path'], 'mime': job['mime'], 'filename': job['filename']}


def wait(job_id: str, timeout: float = 300) -> None:
    """Wait for an export to finish (for the tests)."""
    thread = _threads.get(job_id)
    if thread:
        thread.join(timeout)


# --- gels -----------------------------------------------------------------------------------

_FONTS = ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'DejaVuSans-Bold.ttf', 'arialbd.ttf')


def gel_picture(data: bytes, lanes: List[dict]) -> Optional[bytes]:
    """A gel photo with each lane's number drawn on its well, as the page shows them; PNG."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None
    image = image.convert('RGB')
    w, h = image.size
    radius = max(9, round(w * 0.024))      # as big on the photo as on the page
    font = None
    for name in _FONTS:
        try:
            font = ImageFont.truetype(name, round(radius * 1.15))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    from app.content import order_lanes
    for n, lane in enumerate(order_lanes(lanes), 1):
        x, y = float(lane.get('x', 0)) * w, float(lane.get('y', 0)) * h
        text = str(n)
        tw = draw.textlength(text, font=font)
        half = max(radius, tw / 2 + radius * 0.35)
        draw.rounded_rectangle((x - half, y - radius, x + half, y + radius), radius=radius,
                               fill=(253, 224, 71), outline=(17, 24, 39), width=max(2, radius // 5))
        draw.text((x, y), text, fill=(17, 24, 39), font=font, anchor='mm')
    out = io.BytesIO()
    image.save(out, 'PNG', optimize=True)
    return out.getvalue()
