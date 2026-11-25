from dataclasses import dataclass

from lake.intake.observations import ObservationRef
from lake.intake.store import find_observation
from lake.quality.decisions import QualityDecision, validate_decision
from lake.storage import transaction, validate_local_id


@dataclass(frozen=True)
class Amendment:
    amendment_id: int
    ref: ObservationRef
    decision: QualityDecision


def initialize_amendments(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS quality_amendments (
            amendment_id INTEGER PRIMARY KEY,
            site TEXT NOT NULL,
            day TEXT NOT NULL,
            batch TEXT NOT NULL,
            position INTEGER NOT NULL,
            status TEXT NOT NULL,
            author TEXT NOT NULL
        )
    ''')


def amend(db, ref, status, author):
    if not isinstance(ref, ObservationRef):
        raise ValueError('an observation reference is required')
    decision = validate_decision(status, author)
    with transaction(db):
        find_observation(db, ref)
        amendment_id = db.execute('''
            INSERT INTO quality_amendments(site, day, batch, position, status, author)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ref.site, ref.day, ref.batch, ref.position,
              decision.status, decision.author)).lastrowid
    return Amendment(amendment_id, ref, decision)


def load_amendment(db, amendment_id):
    validate_local_id(amendment_id, 'amendment_id')
    row = db.execute('''
        SELECT site, day, batch, position, status, author
        FROM quality_amendments WHERE amendment_id = ?
    ''', (amendment_id,)).fetchone()
    if row is None:
        raise LookupError(amendment_id)
    return Amendment(amendment_id, ObservationRef(*row[:4]), QualityDecision(*row[4:]))
