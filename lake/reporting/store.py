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


def commit_report(db, request, rows, non_null):
    """Insert one complete result within reconciliation's transaction."""
    report_id = db.execute('''
        INSERT INTO signed_reports(revision_id, columns, receipt_ids, rows, non_null)
        VALUES (?, ?, ?, ?, ?)
    ''', (request.revision_id, dump_record(request.columns), dump_record(request.receipt_ids),
          dump_record(rows), dump_record(non_null))).lastrowid
    return SignedReport(report_id, request.revision_id, request.columns, rows, non_null)


def load_report(db, report_id):
    validate_local_id(report_id, 'report_id')
    stored = db.execute('''
        SELECT revision_id, columns, rows, non_null FROM signed_reports WHERE report_id = ?
    ''', (report_id,)).fetchone()
    if stored is None:
        raise LookupError(report_id)
    revision_id, columns, rows, non_null = stored
    return SignedReport(report_id, revision_id, tuple(json.loads(columns)),
                        tuple(json.loads(rows)), json.loads(non_null))
