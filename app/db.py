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
-- type: notebook | library | year | month | day | page | protocol | todo | meeting | task
-- space 'project': a task's page, seen by its project's members (column project).
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

-- Photos and files attached to notes, kept here so a backup takes them along.
-- Removing one hides it from its note but keeps it for the note's history.
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    data BLOB NOT NULL,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    deleted_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachments_note ON attachments(note_id);

-- An office file turned into a PDF to be shown in the browser, kept by the file's checksum.
CREATE TABLE IF NOT EXISTS file_views (
    sha256 TEXT PRIMARY KEY,
    pdf BLOB NOT NULL,
    made_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

-- A protocol shared with another lab, or a notebook shared with a lab or a
-- person, by its lead. Kept until it is retracted. target is a lab's id (as
-- text) or a username.
CREATE TABLE IF NOT EXISTS shares (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('lab', 'person')),
    target TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (note_id, target_type, target)
);
CREATE INDEX IF NOT EXISTS idx_shares_target ON shares(target_type, target);

-- A day's bookings from the Booking tool, kept as they stood once the day was
-- over (app/bookings.py), and what was written about each.
CREATE TABLE IF NOT EXISTS day_bookings (
    note_id TEXT PRIMARY KEY,
    day TEXT NOT NULL,
    bookings TEXT NOT NULL,
    frozen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS booking_notes (
    note_id TEXT NOT NULL,
    booking_id TEXT NOT NULL,
    text TEXT NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (note_id, booking_id)
);

-- Tasks moved on to a week whose to-do page is not made yet (app/todos.py): they
-- go onto it when it is. week is that week's Monday (YYYY-MM-DD).
CREATE TABLE IF NOT EXISTS todo_pending (
    owner TEXT NOT NULL,
    week TEXT NOT NULL,
    html TEXT NOT NULL,
    from_note TEXT NOT NULL,
    from_item TEXT NOT NULL,
    from_week TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (from_note, from_item)
);
CREATE INDEX IF NOT EXISTS idx_todo_pending_week ON todo_pending(owner, week);

-- Meetings (app/meetings.py): set up by their organiser (owner), once or repeating
-- (repeat: none | weekly | fortnightly | four-weekly | monthly), from starts_on until
-- until (none: for good). Times are the lab's local time, HH:MM.
CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    title TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    until TEXT,
    repeat TEXT NOT NULL DEFAULT 'none',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    agenda TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_meetings_owner ON meetings(owner);
-- Who is invited: the meeting's pages are shared with them and sit under their days.
CREATE TABLE IF NOT EXISTS meeting_people (
    meeting_id TEXT NOT NULL,
    username TEXT NOT NULL,
    PRIMARY KEY (meeting_id, username)
);
CREATE INDEX IF NOT EXISTS idx_meeting_people_user ON meeting_people(username);
-- A date of a meeting whose page has been made (note_id); kept when the page is
-- deleted, so a date skipped is not made again.
CREATE TABLE IF NOT EXISTS meeting_dates (
    meeting_id TEXT NOT NULL,
    day TEXT NOT NULL,
    note_id TEXT,
    PRIMARY KEY (meeting_id, day)
);
CREATE INDEX IF NOT EXISTS idx_meeting_dates_note ON meeting_dates(note_id);

-- Projects (app/projects.py): work packages, tasks and subtasks, what waits for what.
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    username TEXT NOT NULL,
    added_by TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, username)
);
CREATE INDEX IF NOT EXISTS idx_project_members_user ON project_members(username);
CREATE TABLE IF NOT EXISTS workpackages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_workpackages_project ON workpackages(project_id);
-- A task: start_on is the start it is given (or was last given by what it waits for), duration in
-- calendar days; sched_start and sched_end are the dates worked out (app/projects.py schedule).
-- note_id: its page (a note of type 'task').
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    wp_id TEXT NOT NULL,
    parent_id TEXT,
    note_id TEXT,
    title TEXT NOT NULL,
    start_on TEXT NOT NULL,
    duration INTEGER NOT NULL DEFAULT 1,
    sched_start TEXT,
    sched_end TEXT,
    done_on TEXT,
    done_by TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_note ON tasks(note_id);
CREATE TABLE IF NOT EXISTS task_people (
    task_id TEXT NOT NULL,
    username TEXT NOT NULL,
    PRIMARY KEY (task_id, username)
);
-- task_id waits for after_id to finish, then lag days more.
CREATE TABLE IF NOT EXISTS task_deps (
    task_id TEXT NOT NULL,
    after_id TEXT NOT NULL,
    lag INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, after_id)
);
CREATE INDEX IF NOT EXISTS idx_task_deps_after ON task_deps(after_id);
"""


# Columns added after the first release, put into older databases on start-up.
_ADDED_COLUMNS = [
    # The words of a note's content, without markup, for searching.
    ('search_text', "TEXT NOT NULL DEFAULT ''"),
    # Who deleted a note, and the note whose deletion took it (itself, or a
    # page above it), so what went together comes back together.
    ('deleted_by', 'TEXT'),
    ('deleted_root', 'TEXT'),
    # The lab a protocol or library folder belongs to (the suite's lab id, as
    # text): its author's, when it was written. None: every lab's.
    ('lab', 'TEXT'),
    # The project a task's page belongs to (space 'project', app/projects.py).
    ('project', 'TEXT'),
]


# Columns added to attachments: a photo marked up in the notebook is a new
# attachment, made from the original (source_id, never changed), with the marks
# drawn on it kept (markup, JSON) so they can be changed later.
_ADDED_ATTACHMENT_COLUMNS = [
    ('source_id', 'TEXT'),
    ('markup', 'TEXT'),
]


# Columns added to todo_pending: a task moved on keeps its priority (app/content.py PRIORITIES).
_ADDED_TODO_PENDING_COLUMNS = [
    ('priority', "TEXT NOT NULL DEFAULT 'normal'"),
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


def _day_first_titles(conn) -> None:
    """
    Day and month pages named as before 0.18.0 (2026-10-30 Thursday, 2026-10 October) renamed day-first
    (30-10-2026 Thursday, October 2026). Only the names the notebook gave them: a page someone renamed keeps
    its name.
    """
    import calendar
    from datetime import date
    from app import dates
    rows = conn.execute(
        "SELECT n.id, n.type, n.title, a.value FROM notes n JOIN attributes a ON a.note_id = n.id "
        "WHERE (n.type = 'day' AND a.name = 'dateNote') OR (n.type = 'month' AND a.name = 'monthNote')").fetchall()
    for row in rows:
        try:
            if row['type'] == 'day':
                when = date.fromisoformat(row['value'])
                old, new = f'{row["value"]} {calendar.day_name[when.weekday()]}', dates.day_title(when)
            else:
                when = date.fromisoformat(row['value'] + '-01')
                old, new = f'{row["value"]} {calendar.month_name[when.month]}', dates.month_title(when)
        except ValueError:
            continue
        if row['title'] == old:
            conn.execute('UPDATE notes SET title = ? WHERE id = ?', (new, row['id']))


def initialize(db_path: Optional[str] = None) -> None:
    if db_path:
        set_path(db_path)
    directory = os.path.dirname(path())
    if directory:
        os.makedirs(directory, exist_ok=True)
    with connect() as conn:
        # The ordinary rollback journal, as the other tools use, not WAL: the
        # suite's backup reads the database from a read-only mount, and SQLite
        # cannot open a WAL database there. This also turns WAL off in a
        # database made by 0.1.0.
        conn.execute('PRAGMA journal_mode = DELETE')
        conn.executescript(SCHEMA)
        for table, added in (('notes', _ADDED_COLUMNS), ('attachments', _ADDED_ATTACHMENT_COLUMNS),
                             ('todo_pending', _ADDED_TODO_PENDING_COLUMNS)):
            columns = {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}
            for name, decl in added:
                if name not in columns:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
        _day_first_titles(conn)
