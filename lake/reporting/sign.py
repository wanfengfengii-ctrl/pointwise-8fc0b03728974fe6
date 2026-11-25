from lake.receiving.coverage import resolve_coverage
from lake.receiving.reconstruct import reconstruct_rows
from lake.reporting.requests import validate_request
from lake.reporting.rollup import count_non_null
from lake.reporting.scoped_reconcile import reconcile_scoped
from lake.reporting.store import commit_report
from lake.storage import transaction


def reconcile_columns(db, revision_id, receipt_ids, columns):
    request = validate_request(revision_id, receipt_ids, columns)
    with transaction(db):
        register, covered = resolve_coverage(db, request.revision_id,
                                             request.receipt_ids, request.columns)
        rows = reconstruct_rows(register, covered)
        counts = count_non_null(rows, request.columns)
        return commit_report(db, request, rows, counts)
