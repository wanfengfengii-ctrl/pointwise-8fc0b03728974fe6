from lake.intake.provenance import require_text
from lake.receiving.verify import MaterialConflict, verify_material
from lake.storage import validate_local_id


def initialize_receipts(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id INTEGER PRIMARY KEY,
            revision_id TEXT NOT NULL,
            issue_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            column_name TEXT NOT NULL,
            volume_number INTEGER NOT NULL,
            digest TEXT NOT NULL,
            raw BLOB NOT NULL,
            UNIQUE(revision_id, issue_id, kind, column_name, volume_number)
        )
    ''')


def store_receipt(db, material, raw):
    existing = db.execute('''
        SELECT receipt_id, digest FROM receipts
        WHERE revision_id = ? AND issue_id = ? AND kind = ?
            AND column_name = ? AND volume_number = ?
    ''', material.identity).fetchone()
    if existing is not None:
        receipt_id, digest = existing
        if digest != material.digest:
            raise MaterialConflict('material identity already has different content')
        return receipt_id
    return db.execute('''
        INSERT INTO receipts(revision_id, issue_id, kind, column_name, volume_number, digest, raw)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (*material.identity, material.digest, raw)).lastrowid


def load_receipts(db, receipt_ids):
    materials = []
    for receipt_id in receipt_ids:
        validate_local_id(receipt_id, 'receipt_id')
        stored = db.execute('SELECT raw FROM receipts WHERE receipt_id = ?', (receipt_id,)).fetchone()
        if stored is None:
            raise LookupError(receipt_id)
        materials.append(verify_material(stored[0]))
    return tuple(materials)


def list_issue_receipts(db, revision_id, issue_id):
    require_text(revision_id, 'revision_id')
    require_text(issue_id, 'issue_id')
    rows = db.execute('''
        SELECT receipt_id FROM receipts WHERE revision_id = ? AND issue_id = ? ORDER BY receipt_id
    ''', (revision_id, issue_id))
    return tuple(receipt_id for (receipt_id,) in rows)
