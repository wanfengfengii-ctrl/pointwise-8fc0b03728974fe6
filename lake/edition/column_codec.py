import hashlib
import json
from dataclasses import dataclass

from lake.intake.provenance import require_text
from lake.quality.decisions import DECISION_ORDER
from lake.storage import dump_record, validate_local_id


COLUMN_KINDS = {'reading': 'integer', 'quality': 'decision', 'temperature': 'integer'}
MATERIAL_KINDS = ('volume', 'row_register', 'column_basis')


@dataclass(frozen=True)
class Material:
    kind: str
    revision_id: str
    issue_id: str
    body: dict
    digest: str

    @property
    def column(self):
        return self.body.get('column', '')

    @property
    def number(self):
        return self.body.get('number', 0)

    @property
    def identity(self):
        return (self.revision_id, self.issue_id, self.kind, self.column, self.number)


def validate_column(column):
    if not isinstance(column, str) or column not in COLUMN_KINDS:
        raise ValueError(f'unknown column {column!r}')
    return column


def select_columns(columns):
    if not isinstance(columns, (list, tuple)) or not columns:
        raise ValueError('columns must be a nonempty list or tuple')
    selected = tuple(validate_column(column) for column in columns)
    if len(set(selected)) != len(selected):
        raise ValueError('selected columns must be distinct')
    return selected


def record_digest(value):
    return hashlib.sha256(dump_record(value).encode('ascii')).hexdigest()


def validate_digest(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in '0123456789abcdef' for character in value)):
        raise ValueError('invalid SHA-256 digest')
    return value


def _object(fields):
    result = {}
    for key, value in fields:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _invalid_constant(name):
    raise ValueError(f'invalid JSON constant {name}')


def _envelope(revision_id, issue_id, kind, body):
    require_text(revision_id, 'revision_id')
    require_text(issue_id, 'issue_id')
    if kind not in MATERIAL_KINDS or not isinstance(body, dict):
        raise ValueError('invalid material kind or body')
    return {'version': 1, 'revision_id': revision_id, 'issue_id': issue_id,
            'kind': kind, 'body': body}


def encode_material(revision_id, issue_id, kind, body):
    envelope = _envelope(revision_id, issue_id, kind, body)
    return dump_record({**envelope, 'digest': record_digest(envelope)}).encode('ascii')


def decode_material(raw):
    if not isinstance(raw, bytes):
        raise ValueError('a material must be UTF-8 bytes')
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                      parse_constant=_invalid_constant)
    if (not isinstance(data, dict)
            or data.keys() != {'version', 'revision_id', 'issue_id', 'kind', 'body', 'digest'}
            or type(data['version']) is not int or data['version'] != 1):
        raise ValueError('invalid V1 material envelope')
    envelope = _envelope(data['revision_id'], data['issue_id'], data['kind'], data['body'])
    if validate_digest(data['digest']) != record_digest(envelope):
        raise ValueError('material checksum mismatch')
    return Material(data['kind'], data['revision_id'], data['issue_id'],
                    data['body'], data['digest'])


def validate_volume_body(body):
    if body.keys() != {'column', 'number', 'values'}:
        raise ValueError('invalid volume fields')
    column = validate_column(body['column'])
    validate_local_id(body['number'], 'volume number')
    values = body['values']
    if not isinstance(values, list) or not values:
        raise ValueError('volume must contain non-null values')
    if COLUMN_KINDS[column] == 'integer':
        if any(type(value) is not int for value in values):
            raise ValueError('integer volume contains an invalid value')
    elif any(value not in DECISION_ORDER for value in values):
        raise ValueError('quality volume contains an invalid decision')


def encode_volume(revision_id, issue_id, column, number, values):
    body = {'column': column, 'number': number, 'values': list(values)}
    validate_volume_body(body)
    return encode_material(revision_id, issue_id, 'volume', body)


def decode_volume(raw):
    volume = decode_material(raw)
    if volume.kind != 'volume':
        raise ValueError('expected a column volume')
    validate_volume_body(volume.body)
    return volume
