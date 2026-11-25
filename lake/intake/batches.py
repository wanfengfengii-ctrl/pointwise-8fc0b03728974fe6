from lake.intake.store import store_batch
from lake.intake.validation import validate_batch
from lake.storage import transaction


def ingest(db, site, day, batch, records):
    observations = validate_batch(site, day, batch, records)
    with transaction(db):
        return store_batch(db, observations)
