import hashlib

from lake.edition.anchor import decode_anchor, load_anchor
from lake.edition.column_codec import select_columns
from lake.intake.provenance import require_text
from lake.quality.revisions import load_revision
from lake.reporting.scoped_proof import build_proof
from lake.storage import dump_record, transaction


def build_selector(anchor_digest, device, log):
    """Bind a device/log combination to the exact sealed revision digest."""
    payload = dump_record([anchor_digest, device, log])
    return hashlib.sha256(payload.encode('ascii')).hexdigest()


def validate_columns(columns):
    return list(select_columns(columns))


def validate_grant(grant):
    if not isinstance(grant, dict) or grant.keys() != {
        'revision_id', 'device', 'log', 'columns', 'selector'
    }:
        raise ValueError('invalid scope grant fields')
    revision_id = grant['revision_id']
    require_text(revision_id, 'revision_id')
    require_text(grant['device'], 'device')
    require_text(grant['log'], 'log')
    columns = validate_columns(grant['columns'])
    require_text(grant['selector'], 'selector')
    if len(grant['selector']) != 64 or any(
        character not in '0123456789abcdef' for character in grant['selector']
    ):
        raise ValueError('invalid scope selector')
    return {
        'revision_id': revision_id,
        'device': grant['device'],
        'log': grant['log'],
        'columns': columns,
        'selector': grant['selector'],
    }


def grant_scope(db, revision_id, device, log, columns):
    """Create one approved device/log/column authorization for a sealed revision."""
    require_text(revision_id, 'revision_id')
    require_text(device, 'device')
    require_text(log, 'log')
    selected = validate_columns(columns)
    with transaction(db):
        sealed_id, anchor_digest = decode_anchor(load_anchor(db, revision_id))
        if sealed_id != revision_id:
            raise LookupError(revision_id)
        selector = build_selector(anchor_digest, device, log)
        return {
            'revision_id': revision_id,
            'device': device,
            'log': log,
            'columns': selected,
            'selector': selector,
        }


def _row_value(frozen_row, column):
    if column == 'quality':
        return frozen_row.quality
    return getattr(frozen_row.observation, column)


def _scoped_rows(revision, grant):
    rows = []
    for frozen_row in revision.rows:
        provenance = frozen_row.observation.provenance
        if provenance.device != grant['device'] or provenance.log != grant['log']:
            continue
        rows.append({
            'reference': frozen_row.observation.ref.to_record(),
            'provenance': {
                'device': provenance.device,
                'log': provenance.log,
                'line': provenance.line,
                'unit': provenance.unit,
            },
            'values': {column: _row_value(frozen_row, column)
                       for column in grant['columns']},
        })
    return rows


def issue_scoped(db, grant):
    """Emit transportable UTF-8 JSON bytes containing only the authorized rows and columns."""
    authorized = validate_grant(grant)
    with transaction(db):
        sealed_id, anchor_digest = decode_anchor(
            load_anchor(db, authorized['revision_id'])
        )
        if sealed_id != authorized['revision_id']:
            raise LookupError(authorized['revision_id'])
        if build_selector(anchor_digest, authorized['device'], authorized['log']) \
                != authorized['selector']:
            raise ValueError('grant selector does not match the sealed revision anchor')
        revision = load_revision(db, authorized['revision_id'])
        rows = _scoped_rows(revision, authorized)
        proof = build_proof(anchor_digest, authorized, rows)
        shipment = {
            'version': 1,
            'revision_id': authorized['revision_id'],
            'rows': rows,
            'proof': proof,
        }
        return dump_record(shipment).encode('utf-8')
