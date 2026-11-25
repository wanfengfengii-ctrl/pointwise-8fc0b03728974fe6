import json

from lake.edition.anchor import decode_anchor, parse_anchor_record
from lake.edition.column_codec import COLUMN_KINDS
from lake.edition.scope_grants import build_selector, validate_grant
from lake.quality.decisions import DECISION_ORDER
from lake.reporting.rollup import count_non_null
from lake.reporting.scoped_proof import check_proof
from lake.reporting.store import commit_scoped_report
from lake.storage import transaction


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _invalid_constant(name):
    raise ValueError(f'invalid JSON constant {name}')


def parse_shipment(raw):
    if isinstance(raw, str):
        raise ValueError('a shipment must be UTF-8 bytes')
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError('a shipment must be UTF-8 bytes')
    try:
        shipment = json.loads(bytes(raw).decode('utf-8'),
                              object_pairs_hook=_reject_duplicate_keys,
                              parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid shipment payload') from exc
    if (not isinstance(shipment, dict)
            or shipment.keys() != {'version', 'revision_id', 'rows', 'proof'}
            or type(shipment['version']) is not int or shipment['version'] != 1
            or not isinstance(shipment['rows'], list)):
        raise ValueError('invalid shipment envelope')
    return shipment


def _validate_value(column, value):
    kind = COLUMN_KINDS[column]
    if value is None:
        return
    if kind == 'integer':
        if type(value) is not int:
            raise ValueError(f'{column} value must be an integer or null')
    elif value not in DECISION_ORDER:
        raise ValueError(f'{column} value must be a registered decision or null')


def validate_scoped_rows(grant, rows):
    """Check order, uniqueness, provenance scope and granted columns of each row."""
    columns = tuple(grant['columns'])
    seen = set()
    ordering_key = None
    validated = []
    for row in rows:
        ref, provenance, values = parse_anchor_record(row)
        if (provenance.device, provenance.log) != (grant['device'], grant['log']):
            raise ValueError('shipment row provenance is outside the granted scope')
        if set(values.keys()) != set(columns) or len(values) != len(columns):
            raise ValueError('shipment row does not carry exactly the granted columns')
        for column in columns:
            _validate_value(column, values[column])
        if ref in seen:
            raise ValueError('shipment repeats a matching observation')
        seen.add(ref)
        key = (ref.batch, ref.position)
        if ordering_key is not None and key <= ordering_key:
            raise ValueError('shipment rows are not in frozen original order')
        ordering_key = key
        validated.append({
            'reference': ref.to_record(),
            'provenance': {
                'device': provenance.device,
                'log': provenance.log,
                'line': provenance.line,
                'unit': provenance.unit,
            },
            'values': {column: values[column] for column in columns},
        })
    return tuple(validated)


def reconcile_scoped(db, anchor, grant, raw):
    """Verify a scoped shipment against independently received anchor and grant.

    All checks run before any write; any failure raises ValueError and leaves the
    report directory untouched.
    """
    revision_id, anchor_digest = decode_anchor(anchor)
    authorized = validate_grant(grant)
    shipment = parse_shipment(raw)
    if shipment['revision_id'] != revision_id:
        raise ValueError('shipment belongs to a different revision than the anchor')
    if authorized['revision_id'] != revision_id:
        raise ValueError('grant belongs to a different revision than the anchor')
    if build_selector(anchor_digest, authorized['device'], authorized['log']) \
            != authorized['selector']:
        raise ValueError('grant selector does not match the sealed revision anchor')

    raw_rows = shipment['rows']
    # The proof covers the exact parsed rows, so deletion, substitution, reordering,
    # value changes or cross-revision material all fail this single signature.
    check_proof(anchor_digest, authorized, raw_rows, shipment['proof'])
    rows = validate_scoped_rows(authorized, raw_rows)

    counts = count_non_null(rows, authorized['columns'])
    with transaction(db):
        return commit_scoped_report(db, revision_id, authorized, rows, counts)
