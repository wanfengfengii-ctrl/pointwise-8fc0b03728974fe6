import json
from dataclasses import dataclass

from lake.edition.column_codec import record_digest
from lake.intake.provenance import require_text
from lake.storage import dump_record


@dataclass(frozen=True)
class Issue:
    issue_id: str
    revision_id: str
    columns: tuple[str, ...]
    materials: tuple[bytes, ...]


def initialize_issued(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS edition_issues (
            issue_seq INTEGER PRIMARY KEY,
            issue_id TEXT NOT NULL UNIQUE,
            revision_id TEXT NOT NULL REFERENCES day_revisions(revision_id),
            columns TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS edition_materials (
            issue_id TEXT NOT NULL REFERENCES edition_issues(issue_id),
            ordinal INTEGER NOT NULL,
            raw BLOB NOT NULL,
            PRIMARY KEY(issue_id, ordinal)
        )
    ''')


def save_issue(db, revision_id, columns, materialize):
    """Save the directory and exact payloads in the publisher's transaction."""
    number = db.execute('SELECT COALESCE(MAX(issue_seq), 0) + 1 FROM edition_issues').fetchone()[0]
    issue_id = 'issue-' + record_digest([revision_id, number, columns])
    db.execute('''
        INSERT INTO edition_issues(issue_seq, issue_id, revision_id, columns)
        VALUES (?, ?, ?, ?)
    ''', (number, issue_id, revision_id, dump_record(columns)))
    materials = tuple(materialize(issue_id))
    db.executemany('INSERT INTO edition_materials(issue_id, ordinal, raw) VALUES (?, ?, ?)',
                   ((issue_id, ordinal, raw) for ordinal, raw in enumerate(materials, 1)))
    return Issue(issue_id, revision_id, columns, materials)


def load_issued_materials(db, issue_id):
    require_text(issue_id, 'issue_id')
    header = db.execute('''
        SELECT revision_id, columns FROM edition_issues WHERE issue_id = ?
    ''', (issue_id,)).fetchone()
    if header is None:
        raise LookupError(issue_id)
    revision_id, columns = header
    rows = db.execute('''
        SELECT raw FROM edition_materials WHERE issue_id = ? ORDER BY ordinal
    ''', (issue_id,))
    return Issue(issue_id, revision_id, tuple(json.loads(columns)),
                 tuple(raw for (raw,) in rows))
