import json
import sqlite3
from contextlib import contextmanager


def dump_record(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def validate_local_id(value, name):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError(f'{name} must be a positive SQLite identifier')
    return value


@contextmanager
def transaction(db):
    if db.in_transaction:
        raise ValueError('operation requires an idle connection')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


def _open(path, initializers):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        with transaction(db):
            for initialize in initializers:
                initialize(db)
    except BaseException:
        db.close()
        raise
    return db


def open_source(path):
    from lake.edition.issued import initialize_issued
    from lake.intake.store import initialize_intake
    from lake.quality.amendments import initialize_amendments
    from lake.quality.revisions import initialize_revisions

    return _open(path, (initialize_intake, initialize_amendments,
                        initialize_revisions, initialize_issued))


def open_remote(path):
    from lake.receiving.ledger import initialize_receipts
    from lake.reporting.store import initialize_reports

    return _open(path, (initialize_receipts, initialize_reports))
