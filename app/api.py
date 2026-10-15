"""The notebook's JSON API, under /api."""

from datetime import date
from functools import wraps

from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request

from app import attachments, notes, people, sources

api = Blueprint('api', __name__)


def signed_in(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        person = people.current()
        if person is None:
            return jsonify({'error': 'Sign in through the lab suite first'}), 401
        try:
            return view(person, *args, **kwargs)
        except notes.Forbidden as exc:
            return jsonify({'error': str(exc)}), 403
        except (notes.NotFound, LookupError) as exc:
            return jsonify({'error': str(exc).strip("'")}), 404
        except notes.Stale as exc:
            return jsonify({'error': str(exc), 'stale': True, 'note': exc.note}), 409
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    return wrapper


def _body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@api.get('/me')
@signed_in
def me(person):
    return jsonify({'person': person.to_dict(),
                    'notebook': notes.notebook_root(person.username),
                    'library': notes.library_root(),
                    'others': notes.notebooks(person)})


@api.get('/notes/<note_id>')
@signed_in
def get_note(person, note_id):
    return jsonify({'note': notes.get(person, note_id)})


@api.get('/notes/<note_id>/children')
@signed_in
def get_children(person, note_id):
    return jsonify({'children': notes.children(person, note_id)})


@api.post('/notes')
@signed_in
def create_note(person):
    data = _body()
    note_id = notes.create(person, str(data.get('parent_id') or ''), str(data.get('title') or ''),
                           str(data.get('type') or 'page'), data.get('content'))
    return jsonify({'note': notes.get(person, note_id)}), 201


@api.put('/notes/<note_id>')
@signed_in
def save_note(person, note_id):
    data = _body()
    return jsonify({'note': notes.save(person, note_id, data.get('title'), data.get('content'),
                                       data.get('base_version'))})


@api.post('/notes/<note_id>/copy')
@signed_in
def copy_note(person, note_id):
    return jsonify({'note': notes.get(person, notes.copy(person, note_id))}), 201


@api.delete('/notes/<note_id>')
@signed_in
def delete_note(person, note_id):
    notes.delete(person, note_id)
    return jsonify({'ok': True})


@api.post('/notes/<note_id>/attachments')
@signed_in
def add_attachments(person, note_id):
    files = [(f.filename or 'file', f.read(attachments.MAX_BYTES + 1)) for f in request.files.getlist('file')]
    return jsonify({'attachments': attachments.add(person, note_id, files)}), 201


@api.get('/attachments/<att_id>')
@signed_in
def get_attachment(person, att_id):
    found = attachments.fetch(person, att_id)
    shown = (found['inline'] or found['preview']) and request.args.get('download') is None
    name = quote(found['filename'])
    response = Response(found['data'], mimetype=attachments.sent_as(found['mime']))
    response.headers['Content-Disposition'] = (f"{'inline' if shown else 'attachment'}; "
                                               f"filename*=UTF-8''{name}")
    # Never read as anything but what it is, and never run as a page. A PDF is
    # shown by the browser's own viewer, which a sandbox would block.
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = ("default-src 'none'" if found['preview'] and shown
                                                    else "default-src 'none'; sandbox")
    response.headers['Cache-Control'] = 'private, max-age=86400'
    response.headers['ETag'] = found['sha256']
    return response


@api.delete('/attachments/<att_id>')
@signed_in
def remove_attachment(person, att_id):
    attachments.remove(person, att_id)
    return jsonify({'ok': True})


@api.get('/deleted')
@signed_in
def list_deleted(person):
    return jsonify({'deleted': notes.deleted(person)})


@api.get('/deleted/<note_id>')
@signed_in
def get_deleted(person, note_id):
    return jsonify({'note': notes.deleted_note(person, note_id)})


@api.post('/deleted/<note_id>/restore')
@signed_in
def restore_deleted(person, note_id):
    restored = notes.undelete(person, note_id)
    # Shown as its owner or the library sees it; an admin may restore what they cannot open.
    try:
        return jsonify({'note': notes.get(person, restored)})
    except notes.Forbidden:
        return jsonify({'note': None, 'restored': restored})


@api.post('/branches/<branch_id>/move')
@signed_in
def move_branch(person, branch_id):
    data = _body()
    notes.move(person, branch_id, str(data.get('parent_id') or ''), data.get('position'))
    return jsonify({'ok': True})


@api.delete('/branches/<branch_id>')
@signed_in
def remove_branch(person, branch_id):
    notes.remove_placement(person, branch_id)
    return jsonify({'ok': True})


@api.post('/notes/<note_id>/placements')
@signed_in
def add_placement(person, note_id):
    notes.place_also(person, note_id, str(_body().get('parent_id') or ''))
    return jsonify({'note': notes.get(person, note_id)}), 201


@api.post('/notes/<note_id>/attributes')
@signed_in
def add_attribute(person, note_id):
    data = _body()
    attr = notes.add_attribute(person, note_id, str(data.get('type') or 'label'),
                               str(data.get('name') or ''), str(data.get('value') or ''))
    return jsonify({'attribute': attr}), 201


@api.delete('/attributes/<attr_id>')
@signed_in
def remove_attribute(person, attr_id):
    notes.remove_attribute(person, attr_id)
    return jsonify({'ok': True})


@api.get('/notes/<note_id>/revisions')
@signed_in
def list_revisions(person, note_id):
    return jsonify(notes.revisions(person, note_id))


@api.get('/notes/<note_id>/revisions/<int:number>')
@signed_in
def get_revision(person, note_id, number):
    return jsonify({'revision': notes.revision(person, note_id, number)})


@api.post('/notes/<note_id>/revisions/<int:number>/restore')
@signed_in
def restore_revision(person, note_id, number):
    return jsonify({'note': notes.restore(person, note_id, number)})


@api.post('/days')
@signed_in
def start_day(person):
    raw = str(_body().get('date') or '').strip()
    try:
        when = date.fromisoformat(raw) if raw else None
    except ValueError:
        raise ValueError('date must be YYYY-MM-DD')
    return jsonify({'note': notes.get(person, notes.day(person, when))}), 201


@api.get('/search')
@signed_in
def search(person):
    types = [t for t in request.args.get('types', '').split(',') if t]
    return jsonify({'notes': notes.search(person, request.args.get('q', ''), types or None)})


@api.get('/protocols')
@signed_in
def list_protocols(person):
    return jsonify({'protocols': notes.protocols(person, request.args.get('q', ''))})


@api.get('/favorites')
@signed_in
def list_favorites(person):
    return jsonify({'favorites': notes.favorites(person)})


@api.put('/favorites/<note_id>')
@signed_in
def add_favorite(person, note_id):
    notes.set_favorite(person, note_id, True)
    return jsonify({'favorites': notes.favorites(person)})


@api.delete('/favorites/<note_id>')
@signed_in
def remove_favorite(person, note_id):
    notes.set_favorite(person, note_id, False)
    return jsonify({'favorites': notes.favorites(person)})


@api.get('/protocols/<protocol_id>/snapshot')
@signed_in
def protocol_snapshot(person, protocol_id):
    return jsonify({'section': notes.protocol_snapshot(person, protocol_id)})


@api.get('/plasmids')
@signed_in
def find_plasmids(person):
    return jsonify({'plasmids': sources.plasmids(person, request.args.get('q', ''))})


@api.get('/moclo/reactions')
@signed_in
def moclo_reactions(person):
    return jsonify({'saved': sources.saved_reactions(person)})


@api.get('/moclo/reactions/<item_id>/section')
@signed_in
def moclo_reaction_section(person, item_id):
    return jsonify({'section': sources.reaction_section(person, item_id)})
