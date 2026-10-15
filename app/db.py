"""
The notebook's database.

The data model follows Trilium's (TriliumNext, https://github.com/TriliumNext/Trilium):
content lives in notes, and where a note sits in the tree is a separate
branch, so one note can appear in several places. Notes carry attributes,
labels (#name=value) and relations (~name=@note), and every change to a note
is kept as a revision. Links between notes, and to plasmids, are indexed so a
note can show what links to it. See NOTICE.
"""

import os
import sqlite3
from typing import Optional

_path: Optional[str] = None

SCHEMA = """
-- A note: a page of a notebook, a day, a protocol, or a folder of them.
-- type: notebook | library | year | month | day | page | protocol
-- space: 'notebook' (owned by `owner`) or 'library' (the shared protocols).
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    space TEXT NOT NULL,
    owner TEXT,
    content TEXT NOT NULL DEFAULT '[]',
    revision INTEGER NOT NULL DEFAULT 0,
    -- Goes up on every save, so a save started from an older one is noticed.
    version INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_owner ON notes(space, owner);

-- Where a note sits: under which parent, in which order. A note placed in a
-- second spot has a second branch (Trilium's "clone").
CREATE TABLE IF NOT EXISTS branches (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (note_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_branches_parent ON branches(parent_id, position);
CREATE INDEX IF NOT EXISTS idx_branches_note ON branches(note_id);

-- Labels (#date=2026-10-15) and relations (~usesProtocol=@<note id>).
CREATE TABLE IF NOT EXISTS attributes (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('label', 'relation')),
    name TEXT NOT NULL,
    value TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_attributes_note ON attributes(note_id);
CREATE INDEX IF NOT EXISTS idx_attributes_name ON attributes(name, value);

-- Every saved version of a note, numbered from 1; notes.revision is the
-- number of the one it holds now.
CREATE TABLE IF NOT EXISTS revisions (
    note_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    kind TEXT NOT NULL,
    note TEXT,
    changed_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (note_id, number)
);

-- Each person's favourite protocols, listed in their sidebar.
CREATE TABLE IF NOT EXISTS favorites (
    username TEXT NOT NULL,
    note_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (username, note_id)
);

-- What each note links to, kept from its content: other notes and plasmids.
CREATE TABLE IF NOT EXISTS links (
    note_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    PRIMARY KEY (note_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_type, target_id);
"""


# Columns added after the first release, put into older databases on start-up.
_ADDED_COLUMNS = [
    # The words of a note's content, without markup, for searching.
    ('search_text', "TEXT NOT NULL DEFAULT ''"),
]


def set_path(path: str) -> None:
    global _path
    _path = path


def path() -> str:
    return _path or os.environ.get('NOTEBOOK_DATABASE_PATH', '/notebook/notebook.db')


class _Connection:
    """`with connect() as conn:` commits on success and rolls back on error."""

    def __enter__(self) -> sqlite3.Connection:
        conn = sqlite3.connect(path(), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 10000')
        self.conn = conn
        return conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False


def connect() -> _Connection:
    return _Connection()


def initialize(db_path: Optional[str] = None) -> None:
    if db_path:
        set_path(db_path)
    directory = os.path.dirname(path())
    if directory:
        os.makedirs(directory, exist_ok=True)
    with connect() as conn:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(SCHEMA)
        columns = {r['name'] for r in conn.execute('PRAGMA table_info(notes)')}
        for name, decl in _ADDED_COLUMNS:
            if name not in columns:
                conn.execute(f'ALTER TABLE notes ADD COLUMN {name} {decl}')
