import json
from dataclasses import dataclass

from lake.storage import dump_record, validate_local_id


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    revision_id: str
    columns: tuple[str, ...]
    rows: tuple[dict, ...]
    non_null: dict[str, int]
    scope: dict | None = None

    @property
    def row_count(self):
        return len(self.rows)


def initialize_reports(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS signed_reports (
            report_id INTEGER PRIMARY KEY,
            revision_id TEXT NOT NULL,
            columns TEXT NOT NULL,
            receipt_ids TEXT NOT NULL,
            rows TEXT NOT NULL,
            non_null TEXT NOT NULL
        )
    ''')
    existing = {row[1] for row in db.execute('PRAGMA table_info(signed_reports)')}
    if 'scope_json' not in existing:
        db.execute('ALTER TABLE signed_reports ADD COLUMN scope_json TEXT')


def _insert_report(db, revision_id, columns, receipt_ids, rows, non_null, scope):
    return db.execute('''
        INSERT INTO signed_reports(revision_id, columns, receipt_ids, rows, non_null, scope_json)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (revision_id, dump_record(columns), dump_record(receipt_ids),
          dump_record(rows), dump_record(non_null),
          None if scope is None else dump_record(scope))).lastrowid


def commit_report(db, request, rows, non_null):
    """Insert one complete result within reconciliation's transaction."""
    report_id = _insert_report(db, request.revision_id, request.columns,
                               request.receipt_ids, rows, non_null, None)
    return SignedReport(report_id, request.revision_id, request.columns, rows, non_null)


def commit_scoped_report(db, revision_id, grant, rows, non_null):
    """Insert one scoped result, storing the authorization alongside the detail."""
    report_id = _insert_report(db, revision_id, tuple(grant['columns']), (),
                               rows, non_null, grant)
    return SignedReport(report_id, revision_id, tuple(grant['columns']),
                        rows, non_null, scope=dict(grant))


def load_report(db, report_id):
    validate_local_id(report_id, 'report_id')
    stored = db.execute('''
        SELECT revision_id, columns, rows, non_null, scope_json
        FROM signed_reports WHERE report_id = ?
    ''', (report_id,)).fetchone()
    if stored is None:
        raise LookupError(report_id)
    revision_id, columns, rows, non_null, scope_json = stored
    scope = None if scope_json is None else json.loads(scope_json)
    return SignedReport(report_id, revision_id, tuple(json.loads(columns)),
                        tuple(json.loads(rows)), json.loads(non_null), scope)
