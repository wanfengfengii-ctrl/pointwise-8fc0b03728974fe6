from lake.quality.revisions import save_revision
from lake.quality.snapshot import build_snapshot
from lake.storage import transaction


def freeze_day(db, site, day, amendment_ids=()):
    with transaction(db):
        rows = build_snapshot(db, site, day, amendment_ids)
        return save_revision(db, site, day, rows)
