from dataclasses import dataclass, field

from lake.edition.column_codec import Material, record_digest
from lake.receiving.ledger import load_receipts
from lake.receiving.verify import MaterialConflict, check_volume_binding


class PendingMaterials(Exception):
    def __init__(self, columns):
        self.columns = tuple(columns)
        super().__init__('materials pending for ' + ', '.join(self.columns))


@dataclass(frozen=True)
class ColumnCoverage:
    column: str
    values: dict[int, int | str | None]


@dataclass
class _IssueColumn:
    basis: Material | None = None
    volumes: dict[int, Material] = field(default_factory=dict)


@dataclass(frozen=True)
class _Evidence:
    null_rows: frozenset[int]
    value_rows: frozenset[int]
    values: dict[int, int | str | None]
    complete: bool


def _partition(db, revision_id, receipt_ids, columns):
    registers = {}
    groups = {column: {} for column in columns}
    for material in load_receipts(db, receipt_ids):
        if material.revision_id != revision_id:
            continue
        if material.kind == 'row_register':
            registers[record_digest(material.body)] = material.body
        elif material.column in groups:
            group = groups[material.column].setdefault(material.issue_id, _IssueColumn())
            if material.kind == 'column_basis':
                group.basis = material
            else:
                group.volumes[material.number] = material
    register_digests = set(registers)
    for issues in groups.values():
        register_digests.update(group.basis.body['register_digest']
                                for group in issues.values() if group.basis is not None)
    if len(register_digests) > 1:
        raise MaterialConflict('materials name different row registers for this revision')
    return next(iter(registers.values()), None), groups


def _prove_issue(group, row_count):
    basis = group.basis
    descriptors = {}
    values = {ordinal: None for ordinal in basis.body['null_rows']}
    if len(values) != len(basis.body['null_rows']):
        raise MaterialConflict('column basis repeats a null row')
    null_rows = frozenset(values)
    value_rows = set()
    for descriptor in basis.body['volumes']:
        number = descriptor['number']
        if number in descriptors:
            raise MaterialConflict('column basis repeats a volume')
        descriptors[number] = descriptor
        for ordinal in descriptor['members']:
            if ordinal in null_rows or ordinal in value_rows:
                raise MaterialConflict('column basis gives a row multiple states or positions')
            value_rows.add(ordinal)

    if row_count is not None and null_rows.union(value_rows) != set(range(1, row_count + 1)):
        raise MaterialConflict('column basis does not partition the frozen row register')
    for number, volume in group.volumes.items():
        if number not in descriptors:
            raise MaterialConflict('received volume is outside its column basis')
        values.update(check_volume_binding(volume, basis, descriptors[number]))
    complete = row_count is not None and group.volumes.keys() == descriptors.keys()
    return _Evidence(null_rows, frozenset(value_rows), values, complete)


def _resolve_column(column, issues, row_count):
    claims = None
    observed = {}
    complete = None
    for group in issues.values():
        if group.basis is None:
            continue
        evidence = _prove_issue(group, row_count)
        claim = evidence.null_rows, evidence.value_rows
        if claims is not None and claim != claims:
            raise MaterialConflict(f'issuances disagree on source nulls for {column}')
        claims = claim
        for ordinal, value in evidence.values.items():
            if ordinal in observed and observed[ordinal] != value:
                raise MaterialConflict(f'issuances disagree on a value for {column}')
            observed[ordinal] = value
        if evidence.complete:
            complete = ColumnCoverage(column, evidence.values)
    return complete


def resolve_coverage(db, revision_id, receipt_ids, columns):
    register, groups = _partition(db, revision_id, receipt_ids, columns)
    row_count = None if register is None else len(register['rows'])
    coverage = []
    pending = []
    for column in columns:
        result = _resolve_column(column, groups[column], row_count)
        if result is None:
            pending.append(column)
        else:
            coverage.append(result)
    if pending:
        raise PendingMaterials(pending)
    return tuple(register['rows']), tuple(coverage)
