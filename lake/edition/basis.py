from lake.edition.column_codec import decode_volume, encode_material
from lake.intake.provenance import serialize_provenance


def build_row_register(revision, issue_id):
    rows = [{
        'reference': row.observation.ref.to_record(),
        'provenance': serialize_provenance(row.observation.provenance),
    } for row in revision.rows]
    body = {'site': revision.site, 'day': revision.day, 'rows': rows}
    return encode_material(revision.revision_id, issue_id, 'row_register', body)


def build_column_basis(revision_id, issue_id, register_digest, plan, encoded_volumes):
    descriptors = []
    for number, (page, encoded) in enumerate(zip(plan.pages, encoded_volumes, strict=True), 1):
        volume = decode_volume(encoded)
        if (volume.identity != (revision_id, issue_id, 'volume', plan.column, number)
                or volume.body['values'] != [value for _, value in page]):
            raise ValueError('encoded volume differs from its column plan')
        descriptors.append({'number': number, 'digest': volume.digest,
                            'members': [ordinal for ordinal, _ in page]})
    body = {'column': plan.column, 'register_digest': register_digest,
            'volumes': descriptors, 'null_rows': list(plan.null_rows)}
    return encode_material(revision_id, issue_id, 'column_basis', body)
