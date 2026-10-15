"""
What the notebook takes from the other tools, read-only.

    Plasmids        from the Plasmid Editor's library, to link to; a link opens
                    the plasmid in the editor.
    MoClo reactions the assemblies people saved in the MoClo Library Tool, as
                    active tables that work out each DNA's volume the way MoClo
                    does: 40 fmol of vector, 80 fmol of each insert, in 20 µL,
                    ng = fmol × bp × 660 / 10⁶ and µL = ng ÷ concentration.
    MoClo protocol  the Golden Gate assembly protocol from MoClo's guide, put
                    into the protocol library once, where it can be used and
                    adapted like any other.
"""

import html
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from app import content as content_mod
from app.db import connect
from app.people import Person, directory_path

VECTOR_FMOL = 40
INSERT_FMOL = 80
REACTION_UL = 20
FIXED = [('10x Buffer G', '2'), ('100 mM ATP', '0.2'), ('{enzyme}', '1'), ('T4 DNA ligase', '0.4')]


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


def editor_path() -> str:
    return os.environ.get('EDITOR_DATABASE_PATH', '/editor/plasmid_editor.db')


# --- plasmids ------------------------------------------------------------------

def plasmids(person: Person, query: str = '', limit: int = 25) -> List[dict]:
    """Plasmids in the editor's library this person may open, best matches first."""
    q = (query or '').strip()
    rows = _read(editor_path(),
                 'SELECT s.id, s.name, length(s.sequence) AS length, s.circular, s.shared, '
                 '  s.confirmed_at, s.glycerol_stock, u.username AS owner '
                 'FROM sequences s LEFT JOIN users u ON u.id = s.owner_id '
                 'WHERE (? = \'\' OR s.name LIKE ?) ORDER BY '
                 '  CASE WHEN s.name LIKE ? THEN 0 ELSE 1 END, s.updated_at DESC LIMIT 400',
                 (q, f'%{q}%', f'{q}%'))
    found = []
    for r in rows:
        if r['shared'] or person.oversees(r['owner']):
            found.append({'id': r['id'], 'name': r['name'], 'length': r['length'],
                          'circular': bool(r['circular']), 'owner': r['owner'],
                          'confirmed': bool(r['confirmed_at']), 'glycerol_stock': r['glycerol_stock']})
        if len(found) >= limit:
            break
    return found


# --- MoClo reactions -----------------------------------------------------------

def _directory_id(username: str) -> Optional[str]:
    rows = _read(directory_path(), 'SELECT id FROM users WHERE username = ?', (username,))
    return rows[0]['id'] if rows else None


def saved_reactions(person: Person) -> List[dict]:
    """The assemblies this person saved in MoClo that have reactions to set up."""
    user_id = _directory_id(person.username)
    if not user_id:
        return []
    rows = _read(directory_path(), 'SELECT id, item_type, title, summary, created_at FROM saved_items '
                                   'WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    found = []
    for r in rows:
        try:
            summary = json.loads(r['summary'] or '{}')
        except (TypeError, ValueError):
            continue
        reactions = [x for x in (summary.get('reactions') or []) if isinstance(x, dict) and x.get('fragments')]
        if reactions:
            found.append({'id': r['id'], 'title': r['title'], 'kind': r['item_type'],
                          'created_at': r['created_at'],
                          'reactions': [{'label': x.get('label') or f"Level {x.get('level', '')}",
                                         'enzyme': x.get('enzyme') or 'BsaI',
                                         'fragments': len(x.get('fragments') or [])} for x in reactions]})
    return found


def reaction_table(reaction: dict) -> dict:
    """One MoClo reaction as an active table: fill in the concentrations, the volumes follow."""
    enzyme = reaction.get('enzyme') or 'BsaI'
    rows = []
    for frag in reaction.get('fragments') or []:
        vector = frag.get('role') == 'vector'
        name = str(frag.get('name') or ('Vector' if vector else 'Insert'))
        rows.append([f"{name} ({'acceptor vector' if vector else 'insert'})", str(frag.get('size') or ''),
                     str(VECTOR_FMOL if vector else INSERT_FMOL), '', '', '', None])
    for component, volume in FIXED:
        rows.append([component.format(enzyme=enzyme), '', '', '', '', volume, None])
    rows.append(['MQ water', '', '', '', '', f'={REACTION_UL}-SUM(F1:F{len(rows)})', None])
    return {
        'type': 'table',
        'title': f"{reaction.get('label') or 'Reaction'} · {enzyme} · {REACTION_UL} µL",
        'scale': None,
        'columns': [
            {'name': 'Component', 'kind': 'text'},
            {'name': 'Plasmid size', 'kind': 'number', 'unit': 'bp'},
            {'name': 'Amount', 'kind': 'number', 'unit': 'fmol'},
            {'name': 'Concentration', 'kind': 'fill', 'unit': 'ng/µL'},
            {'name': 'DNA', 'kind': 'formula', 'unit': 'ng', 'formula': '=B*C*660/1000000'},
            {'name': 'Volume', 'kind': 'formula', 'unit': 'µL', 'formula': '=E/D'},
            {'name': 'Added', 'kind': 'check'},
        ],
        'rows': [{'cells': r} for r in rows],
    }


def reaction_section(person: Person, item_id: str) -> dict:
    """A saved MoClo assembly as a section to put into a page: one table per reaction."""
    user_id = _directory_id(person.username)
    rows = _read(directory_path(), 'SELECT * FROM saved_items WHERE id = ? AND user_id = ?',
                 (item_id, user_id or ''))
    if not rows:
        raise LookupError('Saved assembly not found')
    item = rows[0]
    summary = json.loads(item['summary'] or '{}')
    reactions = [x for x in (summary.get('reactions') or []) if isinstance(x, dict) and x.get('fragments')]
    if not reactions:
        raise LookupError('That saved item has no reactions')
    blocks: List[Dict[str, Any]] = [{
        'type': 'text',
        'html': (f'<p>Golden Gate assembly of <b>{html.escape(item["title"])}</b>, from the MoClo '
                 f'Library Tool: {VECTOR_FMOL} fmol of vector and {INSERT_FMOL} fmol of each insert in '
                 f'{REACTION_UL} µL. Enter each plasmid\'s concentration and the volumes follow.</p>'),
    }]
    blocks += [reaction_table(r) for r in reactions]
    return {'type': 'section', 'title': f'MoClo reaction: {item["title"]}',
            'source': {'kind': 'moclo-reaction', 'id': item['id'], 'version': None, 'name': item['title']},
            'blocks': blocks}


# --- the MoClo protocol in the library -------------------------------------------

MOCLO_PROTOCOL_KEY = 'moclo-golden-gate'


def moclo_protocol() -> List[dict]:
    """MoClo's Golden Gate assembly protocol (from its protocol guide) as notebook blocks."""
    def steps(*items):
        return [{'text': t} for t in items]
    return [
        {'type': 'text', 'html': (
            '<p>Modular Cloning (MoClo) Golden Gate assembly, from the MoClo Library Tool\'s protocol guide. '
            'Level 0 parts go into Level 1 cassettes with <b>BsaI</b>; Level 1 cassettes into Level 2 '
            'multi-gene constructs with <b>BpiI</b>.</p>'
            '<p>Use a 2:1 molar ratio of insert to vector: about 40 fmol of acceptor vector and 80 fmol '
            'of each insert. ng = (fmol × bp × 660) / 1,000,000. Set the number of reactions to scale '
            'the totals.</p>')},
        {'type': 'table', 'title': 'Reaction setup (20 µL each)',
         'scale': {'label': 'Reactions', 'value': 1, 'base': 1},
         'columns': [
             {'name': 'Component', 'kind': 'text'},
             {'name': 'Per reaction', 'kind': 'number', 'unit': 'µL'},
             {'name': 'Total', 'kind': 'formula', 'unit': 'µL', 'formula': '=B*N'},
             {'name': 'Final concentration', 'kind': 'text'},
             {'name': 'Lot', 'kind': 'fill'},
             {'name': 'Added', 'kind': 'check'}],
         'rows': [{'cells': c} for c in [
             ['10x Buffer G', '2', '', '1x', '', None],
             ['100 mM ATP', '0.2', '', '1 mM', '', None],
             ['Acceptor vector (~40 fmol)', '', '', 'calculate from size', '', None],
             ['Insert DNA (~80 fmol each)', '', '', '2:1 insert:vector', '', None],
             ['BsaI (Level 1) or BpiI (Level 2)', '1', '', '10 units', '', None],
             ['T4 DNA ligase', '0.4', '', '2 units', '', None],
             ['MQ water', '=20-SUM(B1:B6)', '', 'to 20 µL', '', None]]]},
        {'type': 'table', 'title': 'Thermal cycling', 'scale': None,
         'columns': [{'name': 'Step', 'kind': 'text'}, {'name': 'Temperature', 'kind': 'text'},
                     {'name': 'Time', 'kind': 'text'}, {'name': 'Cycles', 'kind': 'text'},
                     {'name': 'Purpose', 'kind': 'text'}],
         'rows': [{'cells': c} for c in [
             ['1', '37 °C', '10 min', '60 cycles of steps 1–2', 'Digestion (BsaI/BpiI)'],
             ['2', '22 °C', '10 min', '', 'Ligation (T4 ligase)'],
             ['3', '37 °C', '10 min', '1', 'Final digestion'],
             ['4', '65 °C', '20 min', '1', 'Enzyme inactivation'],
             ['5', '12 °C', 'hold', '', 'Until transformation']]]},
        {'type': 'text', 'html': '<p>For difficult assemblies with many inserts, raise the cycles from 60 '
                                 'to 80–100.</p>'},
        {'type': 'steps', 'title': 'Procedure', 'items': steps(
            'Plan the assembly in the MoClo tool: check part compatibility and overhangs',
            'For plant transformation: include a selection marker (e.g. BASTA) next to the left T-DNA '
            'border, and check the vector replicates in Agrobacterium',
            'Thaw all components on ice and label the PCR tubes',
            'Add in order: buffer, ATP, DNA, enzyme, ligase, water',
            'Mix gently by pipetting and spin down briefly',
            'Run the MoClo program (60 cycles, about 20 hours; can run overnight)',
            'Transform 5–10 µL into competent E. coli and plate on selective medium; 37 °C overnight',
            'Pick 4–8 colonies and screen by colony PCR, or miniprep and restriction digest',
            'Confirm the construct by whole-plasmid sequencing')},
        {'type': 'text', 'html': (
            '<p><b>Storage.</b> Enzymes at −20 °C; reaction mix at 4 °C (short term) or −20 °C; '
            'transformed cells as glycerol stocks at −80 °C; plasmids at −20 °C in TE or water.</p>')},
    ]


def seed_library() -> None:
    """Put MoClo's protocol into the library, once: deleting it keeps it out."""
    from app import notes
    library = notes.library_root()
    with connect() as conn:
        if conn.execute("SELECT 1 FROM attributes WHERE name = 'seed' AND value = ?",
                        (MOCLO_PROTOCOL_KEY,)).fetchone():
            return
        blocks = content_mod.clean_blocks(moclo_protocol(), username='MoClo Library Tool')
        note_id = notes._create(conn, title='MoClo Golden Gate assembly', type='protocol', space='library',
                                owner=None, by=None, parent_id=library, content=blocks)
        notes._label(conn, note_id, 'seed', MOCLO_PROTOCOL_KEY)
        notes._label(conn, note_id, 'source', 'MoClo Library Tool')
