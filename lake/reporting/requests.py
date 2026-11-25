from dataclasses import dataclass

from lake.edition.column_codec import select_columns
from lake.intake.provenance import require_text
from lake.storage import validate_local_id


@dataclass(frozen=True)
class ReportRequest:
    revision_id: str
    receipt_ids: tuple[int, ...]
    columns: tuple[str, ...]


def validate_request(revision_id, receipt_ids, columns):
    require_text(revision_id, 'revision_id')
    if not isinstance(receipt_ids, (list, tuple)):
        raise ValueError('receipt_ids must be a list or tuple')
    ids = {validate_local_id(receipt_id, 'receipt_id') for receipt_id in receipt_ids}
    return ReportRequest(revision_id, tuple(sorted(ids)), select_columns(columns))
