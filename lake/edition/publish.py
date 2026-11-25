from lake.edition.basis import build_column_basis, build_row_register
from lake.edition.column_codec import decode_material, encode_volume, record_digest, select_columns
from lake.edition.issued import save_issue
from lake.edition.planning import plan_columns
from lake.quality.revisions import load_revision
from lake.storage import transaction


def _materialize(revision, issue_id, plans):
    register = build_row_register(revision, issue_id)
    register_digest = record_digest(decode_material(register).body)
    yield register
    for plan in plans:
        volumes = tuple(encode_volume(revision.revision_id, issue_id, plan.column, number,
                                      [value for _, value in page])
                        for number, page in enumerate(plan.pages, 1))
        yield from volumes
        yield build_column_basis(revision.revision_id, issue_id, register_digest, plan, volumes)


def issue(db, revision_id, columns):
    selected = select_columns(columns)
    with transaction(db):
        revision = load_revision(db, revision_id)
        plans = plan_columns(revision, selected)
        return save_issue(db, revision_id, selected,
                          lambda issue_id: _materialize(revision, issue_id, plans))
