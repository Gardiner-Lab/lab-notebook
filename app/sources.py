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


def _public_column(path: str) -> str:
    """The editor's "Public" flag, or none (0) in an editor database from before it."""
    names = {r['name'] for r in _read(path, 'PRAGMA table_info(sequences)')}
    return 's.public' if 'public' in names else '0 AS public'


def editor_path() -> str:
    return os.environ.get('EDITOR_DATABASE_PATH', '/editor/plasmid_editor.db')


# --- plasmids ------------------------------------------------------------------

def plasmids(person: Person, query: str = '', limit: int = 25) -> List[dict]:
    """Plasmids in the editor's library this person may open, best matches first."""
    q = (query or '').strip()
    path = editor_path()
    rows = _read(path,
                 f'SELECT s.id, s.name, length(s.sequence) AS length, s.circular, {_public_column(path)}, '
                 '  s.confirmed_at, s.glycerol_stock, u.username AS owner '
                 'FROM sequences s LEFT JOIN users u ON u.id = s.owner_id '
                 'WHERE (? = \'\' OR s.name LIKE ?) ORDER BY '
                 '  CASE WHEN s.name LIKE ? THEN 0 ELSE 1 END, s.updated_at DESC LIMIT 400',
                 (q, f'%{q}%', f'{q}%'))
    found = []
    for r in rows:
        # As the editor has it: always its owner's labs'; every lab's once public.
        if person.oversees(r['owner']) or person.shares_lab(r['owner']) or r['public']:
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


# --- how to write a protocol, by example ----------------------------------------------

HOWTO_KEY = 'how-to-write-a-protocol'


def _table(title, columns, rows, scale=None):
    return {'type': 'table', 'title': title, 'scale': scale,
            'columns': [dict(zip(('name', 'kind', 'unit', 'formula'), c)) for c in columns],
            'rows': [{'cells': r} for r in rows]}


def howto_protocol() -> List[dict]:
    """A protocol about writing protocols, whose examples are templates to copy."""
    text = lambda html: {'type': 'text', 'html': html}
    return [
        text('<p>This protocol shows how to write one, by example. Every table below is a working template: '
             'change the numbers to see what happens, then use <b>⋯ › Make a copy</b> to start your own '
             'protocol from this one, and delete what you do not need.</p>'
             '<h3>1. Make a protocol</h3>'
             '<ul><li>Open the <b>🧪 Protocols</b> tab and click <b>＋ New protocol</b>, or <b>＋ New folder</b> '
             'to group protocols.</li>'
             '<li>Give it a clear title: it is what people search for.</li>'
             '<li>Add blocks with the <b>Add:</b> bar at the bottom: <b>¶ Text</b>, <b>▦ Table</b> and '
             '<b>☑ Steps</b>. Hover over a block for ↑ ↓ to move it and ✕ to remove it.</li>'
             '<li>Text has a small bar for <b>bold</b>, <i>italic</i>, headings and lists. Type <b>@</b> to '
             'link a plasmid, which opens in the Plasmid Editor, or another protocol or page.</li>'
             '<li>Everything saves as you go. <b>🕘 History</b> keeps every version, and can roll back to any of them.</li>'
             '</ul>'
             '<h3>2. Who can change it</h3>'
             '<p>Everyone can use every protocol. A protocol can be changed by whoever wrote it, their lab lead '
             'and administrators. Star it (<b>☆ Favourite</b>) to keep it in your sidebar.</p>'
             '<h3>3. Using it on a day</h3>'
             '<p><b>＋ Use today</b> puts the protocol into today\'s page, or use <b>🧪 Protocol…</b> on any '
             'page. The page keeps a copy of the version used: change the volumes, fill in the yellow cells and '
             'tick things off there, and the protocol itself stays as it is. The protocol lists the days it '
             'was used on.</p>'
             '<h3>4. Active tables</h3>'
             '<p>Tables work things out. Each column has a <b>kind</b>, set with <b>⚙ Columns</b> under the '
             'table:</p>'
             '<ul><li><b>Text</b>: words, as typed.</li>'
             '<li><b>Number</b>: a number, as typed.</li>'
             '<li><b>Formula</b>: worked out by the column\'s formula, e.g. <code>=B*N</code>.</li>'
             '<li><b>Scaled by reactions</b>: type the amount for one, and it shows the amount for all.</li>'
             '<li><b>Fill in on the day</b>: left empty here, and shown yellow to be filled in when used.</li>'
             '<li><b>Tick off</b>: a checkbox that records who ticked it, and when.</li></ul>'
             '<p>Click a worked-out (purple) cell to see its formula. The examples follow.</p>'),

        text('<h3>Example 1: a master mix that scales</h3>'
             '<p>Set <b>Reactions</b> to how many you are making. <i>Total</i> is the column formula '
             '<code>=B*N</code>: column B of the same row times N, the number of reactions. The water is a '
             'cell formula of its own, <code>=20-SUM(B1:B6)</code>, which makes each reaction up to 20 µL.</p>'),
        _table('PCR master mix (20 µL reactions)',
               [('Component', 'text', '', ''), ('Per reaction', 'number', 'µL', ''),
                ('Total', 'formula', 'µL', '=B*N'), ('Lot', 'fill', '', ''), ('Added', 'check', '', '')],
               [['5x reaction buffer', '4', '', '', None],
                ['10 mM dNTPs', '0.4', '', '', None],
                ['Primer forward, 10 µM', '1', '', '', None],
                ['Primer reverse, 10 µM', '1', '', '', None],
                ['Polymerase', '0.2', '', '', None],
                ['Template DNA', '1', '', '', None],
                ['Water', '=20-SUM(B1:B6)', '', '', None]],
               scale={'label': 'Reactions', 'value': 4, 'base': 1}),

        text('<h3>Example 2: a scaled column</h3>'
             '<p>The <i>Amount</i> column is <b>Scaled by reactions</b>, here counted in plates: type what one '
             'plate needs and it shows what all of them need. Change <b>Plates</b> to see it.</p>'),
        _table('LB agar plates (25 mL each)',
               [('Ingredient', 'text', '', ''), ('Amount', 'scaled', '', ''), ('Unit', 'text', '', '')],
               [['LB broth powder', '0.625', 'g'],
                ['Agar', '0.375', 'g'],
                ['Water', '25', 'mL'],
                ['Kanamycin, 50 mg/mL (add below 55 °C)', '25', 'µL']],
               scale={'label': 'Plates', 'value': 10, 'base': 1}),

        text('<h3>Example 3: calculations</h3>'
             '<p>A dilution worked out per sample: <i>Stock to add</i> is <code>=C*D/B</code> '
             '(wanted concentration × final volume ÷ stock concentration) and <i>Water</i> is <code>=D-E</code>. '
             'The last row overrides both columns with cell formulas of its own, <code>=SUM(E1:E3)</code> and '
             '<code>=SUM(F1:F3)</code>, to add them up. Cells refer to each other as in a spreadsheet: A1 is '
             'column A of the first row, and A1:A3 is a range.</p>'
             '<p>A result waits, and stays empty, until everything it needs has been filled in. A blank stock '
             'concentration would leave that row\'s volumes, and the totals, empty rather than wrong.</p>'),
        _table('Dilute plasmids to 50 ng/µL',
               [('Sample', 'text', '', ''), ('Stock', 'number', 'ng/µL', ''), ('Wanted', 'number', 'ng/µL', ''),
                ('Final volume', 'number', 'µL', ''), ('Stock to add', 'formula', 'µL', '=C*D/B'),
                ('Water', 'formula', 'µL', '=D-E')],
               [['pGFP clone 1', '412', '50', '20', '', ''],
                ['pGFP clone 2', '268', '50', '20', '', ''],
                ['pRFP clone 4', '190', '50', '20', '', ''],
                ['Total', '', '', '', '=SUM(E1:E3)', '=SUM(F1:F3)']]),

        text('<h3>Example 4: recording what was done</h3>'
             '<p>Yellow <b>fill in</b> cells stay empty in the protocol and are filled in on the day. '
             '<b>Tick off</b> cells record who ticked them and when, so the page shows who did each step.</p>'),
        _table('Heat-shock transformation: record',
               [('Step', 'text', '', ''), ('Setting', 'text', '', ''), ('Actual', 'fill', '', ''),
                ('Time', 'fill', '', ''), ('Done', 'check', '', '')],
               [['Thaw competent cells on ice', '10 min', '', '', None],
                ['Add DNA, mix gently, on ice', '5 µL, 30 min', '', '', None],
                ['Heat shock', '42 °C, 45 s', '', '', None],
                ['Recover in SOC, shaking', '37 °C, 1 h', '', '', None],
                ['Plate on selective medium', '100 µL', '', '', None]]),

        text('<h3>Example 5: steps to tick off</h3>'
             '<p>A <b>☑ Steps</b> block is a numbered list to tick off as you go. Like ticks in tables, '
             'each records who ticked it and when.</p>'),
        {'type': 'steps', 'title': 'Writing your first protocol', 'items': [
            {'text': 'Open this protocol and choose ⋯ › Make a copy'},
            {'text': 'Rename the copy, and move it into a folder with ⋯ › Move to…'},
            {'text': 'Delete the examples you do not need (hover, then ✕)'},
            {'text': 'Change the tables: ⚙ Columns for names, kinds, units and formulas; ＋ Row for rows'},
            {'text': 'Star it, and try it out with ＋ Use today'},
        ]},

        text('<h3>Formula cheat sheet</h3>'
             '<ul><li>Start with <code>=</code>. Use <code>+ - * / ^</code> and brackets.</li>'
             '<li><code>B</code> in a column formula means column B in the same row. <code>B2</code> is one cell, '
             '<code>B1:B6</code> a range.</li>'
             '<li><code>N</code> is the number set above the table (reactions, plates…).</li>'
             '<li>Functions: <code>SUM</code>, <code>MIN</code>, <code>MAX</code>, <code>AVERAGE</code>, '
             '<code>ROUND(x, 2)</code>, <code>ABS</code>, <code>IF(B1&gt;10, 1, 0)</code>.</li>'
             '<li>A cell of its own that starts with <code>=</code> overrides its column\'s formula, as in the '
             'Total row above.</li>'
             '<li>Errors say what is wrong: <code>#DIV/0</code> (divided by zero), <code>#REF</code> (no such '
             'cell), <code>#CYCLE</code> (a formula that needs itself).</li></ul>'),
    ]


def fill_search_text() -> None:
    """Notes saved before search looked into content get their words now."""
    with connect() as conn:
        rows = conn.execute("SELECT id, content FROM notes WHERE search_text = '' AND content != '[]'").fetchall()
        for r in rows:
            conn.execute('UPDATE notes SET search_text = ? WHERE id = ?',
                         (content_mod.plain_text(json.loads(r['content'] or '[]')), r['id']))


SEEDS = [
    # (key, title, blocks, source label)
    (HOWTO_KEY, 'How to write a protocol (start here)', howto_protocol, 'Lab Notebook'),
    (MOCLO_PROTOCOL_KEY, 'MoClo Golden Gate assembly', moclo_protocol, 'MoClo Library Tool'),
]


def seed_library() -> None:
    """Put the starting protocols into the library, each once: deleting one keeps it out."""
    from app import notes
    library = notes.library_root()
    with connect() as conn:
        for key, title, blocks, source in SEEDS:
            if conn.execute("SELECT 1 FROM attributes WHERE name = 'seed' AND value = ?", (key,)).fetchone():
                continue
            cleaned = content_mod.clean_blocks(blocks(), username=source)
            note_id = notes._create(conn, title=title, type='protocol', space='library',
                                    owner=None, by=None, parent_id=library, content=cleaned)
            notes._label(conn, note_id, 'seed', key)
            notes._label(conn, note_id, 'source', source)
