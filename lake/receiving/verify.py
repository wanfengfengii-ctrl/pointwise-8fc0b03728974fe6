from lake.edition.column_codec import (
    decode_material, validate_column, validate_digest, validate_volume_body,
)
from lake.intake.observations import parse_reference, validate_day
from lake.intake.provenance import parse_provenance
from lake.storage import validate_local_id


class MaterialConflict(ValueError):
    """Individually valid material contradicts other material in its scope."""


def _validate_register(body):
    if body.keys() != {'site', 'day', 'rows'} or not isinstance(body['rows'], list):
        raise ValueError('invalid row register fields')
    station_day = body['site'], body['day']
    validate_day(*station_day)
    seen = set()
    for row in body['rows']:
        if not isinstance(row, dict) or row.keys() != {'reference', 'provenance'}:
            raise ValueError('invalid row register entry')
        ref = parse_reference(row['reference'])
        parse_provenance(row['provenance'])
        if (ref.site, ref.day) != station_day or ref in seen:
            raise ValueError('foreign or repeated observation in row register')
        seen.add(ref)


def _validate_ordinals(values):
    if not isinstance(values, list):
        raise ValueError('row ordinals must be an array')
    for value in values:
        validate_local_id(value, 'row ordinal')


def _validate_basis(body):
    if body.keys() != {'column', 'register_digest', 'volumes', 'null_rows'}:
        raise ValueError('invalid column basis fields')
    validate_column(body['column'])
    validate_digest(body['register_digest'])
    _validate_ordinals(body['null_rows'])
    if not isinstance(body['volumes'], list):
        raise ValueError('volume descriptors must be an array')
    for descriptor in body['volumes']:
        if (not isinstance(descriptor, dict)
                or descriptor.keys() != {'number', 'digest', 'members'}):
            raise ValueError('invalid volume descriptor')
        validate_local_id(descriptor['number'], 'volume number')
        validate_digest(descriptor['digest'])
        _validate_ordinals(descriptor['members'])
        if not descriptor['members']:
            raise ValueError('volume descriptor must name at least one member')


def verify_material(raw):
    material = decode_material(raw)
    if material.kind == 'volume':
        validate_volume_body(material.body)
    elif material.kind == 'row_register':
        _validate_register(material.body)
    else:
        _validate_basis(material.body)
    return material


def check_volume_binding(volume, basis, descriptor):
    expected = (basis.revision_id, basis.issue_id, 'volume', basis.column, descriptor['number'])
    if volume.identity != expected or volume.digest != descriptor['digest']:
        raise MaterialConflict(f'volume {descriptor["number"]} disagrees with its column basis')
    values = volume.body['values']
    if len(values) != len(descriptor['members']):
        raise MaterialConflict('volume cardinality disagrees with its declared members')
    return tuple(zip(descriptor['members'], values, strict=True))
