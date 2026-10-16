"""
A note's content: a list of blocks, checked and cleaned on every save.

    text     {id, type, html}                       rich text, cleaned to a safe subset
    table    {id, type, title, scale, columns, rows}  an active table (see tables.js)
    steps    {id, type, title, items}               steps to tick off
    section  {id, type, title, source, blocks}      a protocol or MoClo reaction put
                                                    into a page, with where it came from

Ticks (a step done, a checkbox cell) record who ticked them and when. Those are
set here, from the person saving and the time, never taken from the browser:
a tick that is new in this save gets them, one that was already there keeps
its own.
"""

import html
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import nh3

TEXT_TAGS = {'p', 'br', 'b', 'strong', 'i', 'em', 'u', 's', 'sub', 'sup', 'h1', 'h2', 'h3',
             'ul', 'ol', 'li', 'a', 'code', 'pre', 'blockquote', 'span', 'mark', 'hr', 'img'}
# A picture or file is named by its attachment, never by an address: the page
# works out where to fetch it from, so text cannot point images elsewhere.
TEXT_ATTRIBUTES = {'a': {'href', 'data-plasmid', 'data-note', 'data-seed', 'data-stock', 'data-attachment', 'class', 'title'},
                   'img': {'data-attachment', 'alt', 'title'},
                   'span': {'class'}, 'mark': {'class'}}
COLUMN_KINDS = ('text', 'number', 'scaled', 'fill', 'check', 'formula')
MAX_HTML = 200_000
MAX_CELL = 2_000
MAX_COLUMNS = 40
MAX_ROWS = 500
MAX_ITEMS = 300
MAX_BLOCKS = 400

# Links to other notes, to plasmids, to the seed bank's lines, lots and plants, and to
# Lab Stocks' glycerol stocks and primers (both by code).
_LINK = re.compile(r'data-(note|plasmid|seed|stock)="([^"]{1,80})"')


def new_id() -> str:
    return secrets.token_hex(6)


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def clean_html(html: Any) -> str:
    return nh3.clean(str(html or '')[:MAX_HTML], tags=TEXT_TAGS, attributes=TEXT_ATTRIBUTES,
                     url_schemes={'http', 'https', 'mailto'}, link_rel='noopener noreferrer')


def _text(value: Any, limit: int = 300) -> str:
    return str(value if value is not None else '')[:limit]


def _number(value: Any, default: float) -> float:
    try:
        n = float(value)
        return n if n == n and abs(n) < 1e12 else default    # not NaN, not absurd
    except (TypeError, ValueError):
        return default


def _ticks(blocks: List[dict]) -> Dict[Tuple, dict]:
    """Every tick in some content, by where it is: (block, row or item, column)."""
    found: Dict[Tuple, dict] = {}
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'section':
            found.update(_ticks(block.get('blocks')))
        elif block.get('type') == 'steps':
            for item in block.get('items') or []:
                if isinstance(item, dict) and item.get('by'):
                    found[(block.get('id'), item.get('id'), None)] = item
        elif block.get('type') == 'table':
            columns = block.get('columns') or []
            for row in block.get('rows') or []:
                for c, cell in enumerate((row or {}).get('cells') or []):
                    if c < len(columns) and (columns[c] or {}).get('kind') == 'check' \
                            and isinstance(cell, dict) and cell.get('by'):
                        found[(block.get('id'), row.get('id'), c)] = cell
    return found


class _Cleaner:
    def __init__(self, previous: Optional[List[dict]], username: str):
        self.before = _ticks(previous or [])
        self.username = username
        self.stamp = now()
        self.seen_ids = set()

    def _id(self, value: Any) -> str:
        bid = _text(value, 40) or new_id()
        while bid in self.seen_ids:
            bid = new_id()
        self.seen_ids.add(bid)
        return bid

    def _tick(self, key: Tuple, ticked: bool) -> Optional[dict]:
        if not ticked:
            return None
        old = self.before.get(key)
        if old:
            return {'by': old['by'], 'at': old.get('at')}
        return {'by': self.username, 'at': self.stamp}

    def block(self, block: Any, nested: bool = False) -> Optional[dict]:
        if not isinstance(block, dict):
            return None
        kind = block.get('type')
        bid = self._id(block.get('id'))
        if kind == 'text':
            return {'id': bid, 'type': 'text', 'html': clean_html(block.get('html'))}
        if kind == 'steps':
            items = []
            for item in (block.get('items') or [])[:MAX_ITEMS]:
                if not isinstance(item, dict):
                    continue
                iid = _text(item.get('id'), 40) or new_id()
                tick = self._tick((bid, iid, None), bool(item.get('done') or item.get('by')))
                items.append({'id': iid, 'text': _text(item.get('text'), MAX_CELL),
                              'by': tick['by'] if tick else None, 'at': tick['at'] if tick else None})
            return {'id': bid, 'type': 'steps', 'title': _text(block.get('title')), 'items': items}
        if kind == 'table':
            return self.table(block, bid)
        if kind == 'section' and not nested:
            source = block.get('source') if isinstance(block.get('source'), dict) else {}
            inner = [b for b in (self.block(x, nested=True) for x in (block.get('blocks') or [])[:MAX_BLOCKS])
                     if b]
            return {'id': bid, 'type': 'section', 'title': _text(block.get('title')),
                    'source': {'kind': _text(source.get('kind'), 40), 'id': _text(source.get('id'), 80),
                               'version': source.get('version') if isinstance(source.get('version'), int) else None,
                               'name': _text(source.get('name'))},
                    'blocks': inner}
        return None

    def table(self, block: dict, bid: str) -> dict:
        columns = []
        for col in (block.get('columns') or [])[:MAX_COLUMNS]:
            col = col if isinstance(col, dict) else {}
            kind = col.get('kind') if col.get('kind') in COLUMN_KINDS else 'text'
            columns.append({'name': _text(col.get('name'), 120), 'kind': kind,
                            'unit': _text(col.get('unit'), 30), 'formula': _text(col.get('formula'), 500)})
        rows = []
        for row in (block.get('rows') or [])[:MAX_ROWS]:
            row = row if isinstance(row, dict) else {}
            rid = _text(row.get('id'), 40) or new_id()
            given = row.get('cells') if isinstance(row.get('cells'), list) else []
            cells = []
            for c, col in enumerate(columns):
                value = given[c] if c < len(given) else None
                if col['kind'] == 'check':
                    cells.append(self._tick((bid, rid, c), bool(value)))
                else:
                    cells.append(_text(value, MAX_CELL) if value is not None else '')
            rows.append({'id': rid, 'cells': cells})
        scale = block.get('scale') if isinstance(block.get('scale'), dict) else None
        if scale is not None:
            scale = {'label': _text(scale.get('label'), 60) or 'Reactions',
                     'value': _number(scale.get('value'), 1.0), 'base': _number(scale.get('base'), 1.0) or 1.0}
        return {'id': bid, 'type': 'table', 'title': _text(block.get('title')),
                'scale': scale, 'columns': columns, 'rows': rows}


def clean_blocks(blocks: Any, previous: Optional[List[dict]] = None, username: str = '') -> List[dict]:
    """Content as it is stored: unknown blocks dropped, text cleaned, ticks stamped."""
    if not isinstance(blocks, list):
        raise ValueError('content must be a list of blocks')
    cleaner = _Cleaner(previous, username)
    return [b for b in (cleaner.block(x) for x in blocks[:MAX_BLOCKS]) if b]


_TAG = re.compile(r'<[^>]+>')


def plain_text(blocks: List[dict]) -> str:
    """The words in some content, without markup: what search looks through."""
    words: List[str] = []

    def walk(items):
        for block in items or []:
            kind = block.get('type')
            words.append(str(block.get('title') or ''))
            if kind == 'text':
                words.append(html.unescape(_TAG.sub(' ', block.get('html') or '')))
            elif kind == 'steps':
                words.extend(str(i.get('text') or '') for i in block.get('items') or [])
            elif kind == 'table':
                words.extend(str(c.get('name') or '') for c in block.get('columns') or [])
                for row in block.get('rows') or []:
                    words.extend(c for c in row.get('cells') or [] if isinstance(c, str) and not c.startswith('='))
            elif kind == 'section':
                walk(block.get('blocks'))
    walk(blocks)
    return re.sub(r'\s+', ' ', ' '.join(words)).strip()


def links(blocks: List[dict]) -> List[Tuple[str, str]]:
    """The notes and plasmids some content links to: [(type, id)]."""
    found = set()

    def walk(items):
        for block in items or []:
            if block.get('type') == 'text':
                found.update(_LINK.findall(block.get('html') or ''))
            elif block.get('type') == 'section':
                walk(block.get('blocks'))
                if block.get('source', {}).get('kind') == 'protocol' and block['source'].get('id'):
                    found.add(('note', block['source']['id']))
    walk(blocks)
    return sorted(found)
