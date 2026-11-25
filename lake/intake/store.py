import json

from lake.intake.observations import Observation, ObservationRef
from lake.intake.provenance import parse_provenance, serialize_provenance
from lake.storage import dump_record


def initialize_intake(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_batches (
            batch_seq INTEGER PRIMARY KEY,
            site TEXT NOT NULL,
            day TEXT NOT NULL,
            batch TEXT NOT NULL,
            UNIQUE(site, day, batch)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS source_observations (
            batch_seq INTEGER NOT NULL REFERENCES source_batches(batch_seq),
            position INTEGER NOT NULL,
            fact TEXT NOT NULL,
            PRIMARY KEY(batch_seq, position)
        )
    ''')


def _fact(observation):
    return dump_record({
        'reading': observation.reading,
        'temperature': observation.temperature,
        'provenance': serialize_provenance(observation.provenance),
    })


def _observation(site, day, batch, position, fact):
    data = json.loads(fact)
    return Observation(ObservationRef(site, day, batch, position),
                       data['reading'], data['temperature'],
                       parse_provenance(data['provenance']))


def store_batch(db, observations):
    """Save a validated batch within the caller's write transaction."""
    first = observations[0].ref
    key = (first.site, first.day, first.batch)
    facts = [(observation.ref.position, _fact(observation)) for observation in observations]
    existing = db.execute('''
        SELECT batch_seq FROM source_batches WHERE site = ? AND day = ? AND batch = ?
    ''', key).fetchone()
    if existing is not None:
        stored = db.execute('''
            SELECT position, fact FROM source_observations
            WHERE batch_seq = ? ORDER BY position
        ''', existing).fetchall()
        if stored != facts:
            raise ValueError('source batch identity already has different observations')
    else:
        batch_seq = db.execute('''
            INSERT INTO source_batches(site, day, batch) VALUES (?, ?, ?)
        ''', key).lastrowid
        db.executemany('''
            INSERT INTO source_observations(batch_seq, position, fact) VALUES (?, ?, ?)
        ''', ((batch_seq, position, fact) for position, fact in facts))
    return tuple(observation.ref for observation in observations)


def find_observation(db, ref):
    row = db.execute('''
        SELECT o.fact FROM source_batches AS b JOIN source_observations AS o USING(batch_seq)
        WHERE b.site = ? AND b.day = ? AND b.batch = ? AND o.position = ?
    ''', (ref.site, ref.day, ref.batch, ref.position)).fetchone()
    if row is None:
        raise LookupError(ref)
    return _observation(ref.site, ref.day, ref.batch, ref.position, row[0])


def read_day_observations(db, site, day):
    rows = db.execute('''
        SELECT b.batch, o.position, o.fact
        FROM source_batches AS b JOIN source_observations AS o USING(batch_seq)
        WHERE b.site = ? AND b.day = ? ORDER BY b.batch_seq, o.position
    ''', (site, day))
    return tuple(_observation(site, day, *row) for row in rows)
