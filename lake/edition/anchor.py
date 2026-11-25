import hashlib
import json

from lake.intake.observations import parse_reference
from lake.intake.provenance import parse_provenance, require_text
from lake.quality.revisions import load_revision
from lake.storage import dump_record, transaction

ANCHOR_FORMAT_VERSION = 1


def initialize_anchors(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS scope_anchors (
            revision_id TEXT PRIMARY KEY REFERENCES day_revisions(revision_id),
            digest TEXT NOT NULL,
            anchor BLOB NOT NULL
        )
    ''')


def _revision_fingerprint_rows(revision):
    rows = []
    for frozen in revision.rows:
        observation = frozen.observation
        amendment = frozen.amendment
        decision = None
        if amendment is not None:
            decision = {
                'amendment_id': amendment.amendment_id,
                'status': amendment.decision.status,
                'author': amendment.decision.author,
            }
        rows.append({
            'reference': observation.ref.to_record(),
            'reading': observation.reading,
            'temperature': observation.temperature,
            'provenance': {
                'device': observation.provenance.device,
                'log': observation.provenance.log,
                'line': observation.provenance.line,
                'unit': observation.provenance.unit,
            },
            'decision': decision,
        })
    return rows


def revision_fingerprint(revision):
    """Hash every frozen fact of a revision, so any hidden change breaks the anchor."""
    payload = {
        'site': revision.site,
        'day': revision.day,
        'rows': _revision_fingerprint_rows(revision),
    }
    return hashlib.sha256(dump_record(payload).encode('ascii')).hexdigest()


def encode_anchor(revision_id, digest):
    anchor = {
        'format': ANCHOR_FORMAT_VERSION,
        'revision_id': revision_id,
        'digest': digest,
    }
    return dump_record(anchor).encode('utf-8')


def seal_scope(db, revision_id):
    """Fix and persist a retrievable day-revision anchor before any grant is made."""
    require_text(revision_id, 'revision_id')
    with transaction(db):
        stored = db.execute(
            'SELECT anchor FROM scope_anchors WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if stored is not None:
            return bytes(stored[0])
        revision = load_revision(db, revision_id)
        digest = revision_fingerprint(revision)
        anchor = encode_anchor(revision.revision_id, digest)
        db.execute('''
            INSERT INTO scope_anchors(revision_id, digest, anchor)
            VALUES (?, ?, ?)
        ''', (revision.revision_id, digest, anchor))
        return bytes(anchor)


def load_anchor(db, revision_id):
    require_text(revision_id, 'revision_id')
    row = db.execute(
        'SELECT anchor FROM scope_anchors WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise LookupError(revision_id)
    return bytes(row[0])


def decode_anchor(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError('an anchor must be bytes')
    try:
        anchor = json.loads(bytes(raw).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid anchor payload') from exc
    if (not isinstance(anchor, dict)
            or anchor.keys() != {'format', 'revision_id', 'digest'}
            or type(anchor['format']) is not int
            or anchor['format'] != ANCHOR_FORMAT_VERSION):
        raise ValueError('invalid anchor envelope')
    require_text(anchor['revision_id'], 'revision_id')
    digest = anchor['digest']
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in '0123456789abcdef' for character in digest)):
        raise ValueError('invalid anchor digest')
    return anchor['revision_id'], digest


def parse_anchor_record(row):
    """Validate frozen-row reference/provenance shapes carried in scoped proof rows."""
    if not isinstance(row, dict) or row.keys() != {'reference', 'provenance', 'values'}:
        raise ValueError('invalid shipment row')
    ref = parse_reference(row['reference'])
    provenance = parse_provenance(row['provenance'])
    if not isinstance(row['values'], dict) or not row['values']:
        raise ValueError('invalid shipment values')
    return ref, provenance, row['values']
