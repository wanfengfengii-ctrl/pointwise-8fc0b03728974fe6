import hashlib
import json
from dataclasses import dataclass

from lake.intake.observations import Observation, parse_reference
from lake.intake.provenance import parse_provenance, require_text, serialize_provenance
from lake.quality.amendments import Amendment
from lake.quality.decisions import QualityDecision
from lake.quality.snapshot import FrozenRow
from lake.storage import dump_record


@dataclass(frozen=True)
class DayRevision:
    revision_id: str
    site: str
    day: str
    rows: tuple[FrozenRow, ...]


def initialize_revisions(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS day_revisions (
            revision_seq INTEGER PRIMARY KEY,
            revision_id TEXT NOT NULL UNIQUE,
            site TEXT NOT NULL,
            day TEXT NOT NULL,
            rows TEXT NOT NULL
        )
    ''')


def _encode_row(row):
    observation = row.observation
    decision = None
    if row.amendment is not None:
        decision = {
            'amendment_id': row.amendment.amendment_id,
            'status': row.amendment.decision.status,
            'author': row.amendment.decision.author,
        }
    return {
        'reference': observation.ref.to_record(),
        'reading': observation.reading,
        'temperature': observation.temperature,
        'provenance': serialize_provenance(observation.provenance),
        'decision': decision,
    }


def _decode_row(data):
    ref = parse_reference(data['reference'])
    observation = Observation(ref, data['reading'], data['temperature'],
                              parse_provenance(data['provenance']))
    decision = data['decision']
    amendment = None
    if decision is not None:
        amendment = Amendment(decision['amendment_id'], ref,
                              QualityDecision(decision['status'], decision['author']))
    return FrozenRow(observation, amendment)


def save_revision(db, site, day, rows):
    """Persist a snapshot in the transaction that determined its members."""
    number = db.execute('SELECT COALESCE(MAX(revision_seq), 0) + 1 FROM day_revisions').fetchone()[0]
    encoded = dump_record([_encode_row(row) for row in rows])
    digest = hashlib.sha256(dump_record([number, site, day, encoded]).encode('ascii')).hexdigest()
    revision_id = f'rev-{digest}'
    db.execute('''
        INSERT INTO day_revisions(revision_seq, revision_id, site, day, rows)
        VALUES (?, ?, ?, ?, ?)
    ''', (number, revision_id, site, day, encoded))
    return DayRevision(revision_id, site, day, rows)


def load_revision(db, revision_id):
    require_text(revision_id, 'revision_id')
    row = db.execute('''
        SELECT site, day, rows FROM day_revisions WHERE revision_id = ?
    ''', (revision_id,)).fetchone()
    if row is None:
        raise LookupError(revision_id)
    site, day, encoded = row
    return DayRevision(revision_id, site, day,
                       tuple(_decode_row(item) for item in json.loads(encoded)))
