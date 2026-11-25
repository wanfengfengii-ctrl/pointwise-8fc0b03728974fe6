import json
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.edition.publish import (
    grant_scope, issue, issue_scoped, seal_scope,
)
from lake.intake.batches import ingest
from lake.quality.amendments import amend
from lake.quality.freeze import freeze_day
from lake.receiving.accept import receive
from lake.receiving.coverage import PendingMaterials
from lake.receiving.verify import verify_material
from lake.reporting.retrieve import retrieve
from lake.reporting.sign import reconcile_columns, reconcile_scoped
from lake.storage import open_remote, open_source
from scope_fixture import load_case, populate, trusted_inputs


def _triples(report):
    return [[row['reference']['position'], row['values']['reading'],
             row['values']['quality'], row['provenance']['line']] for row in report.rows]


def demonstrate_scoped_handoff(root):
    """Restricted delivery: fixed anchor, per device/log column grants, offline checks."""
    case = load_case()
    source_path = root / 'scoped-source.sqlite'
    remote_path = root / 'scoped-remote.sqlite'
    with closing(open_source(source_path)) as source:
        revision = populate(source, case)
        # 先固定可复取的日版锚，再办理任何授权
        anchor = seal_scope(source, revision.revision_id)
        assert seal_scope(source, revision.revision_id) == anchor
        grant = grant_scope(source, revision.revision_id,
                            'collector-2', 'out.log', ('reading',))
        absent_grant = grant_scope(source, revision.revision_id,
                                   'collector-2', 'absent.log', ('reading',))
        shipment_bytes = issue_scoped(source, grant)
        zero_bytes = issue_scoped(source, absent_grant)
        # 独立渠道：锚与授权单独交给异地仓（不含应到行、行数或摘要）
        trusted_anchor, trusted_grant = trusted_inputs(anchor, grant)
        zero_anchor, zero_trusted = trusted_inputs(anchor, absent_grant)
        # 运输件可被截改：构造删行、换件、乱序、改值、串版与去证明样本
        original = json.loads(shipment_bytes)
        deleted = deepcopy(original)
        deleted['rows'].pop(1)
        substituted = deepcopy(original)
        internal = next(row for row in revision.rows
                        if row.observation.provenance.log == 'internal.log')
        substituted['rows'][2] = {
            'reference': internal.observation.ref.to_record(),
            'provenance': {
                'device': internal.observation.provenance.device,
                'log': internal.observation.provenance.log,
                'line': internal.observation.provenance.line,
                'unit': internal.observation.provenance.unit,
            },
            'values': {'reading': 7},
        }
        reordered = deepcopy(original)
        reordered['rows'][0], reordered['rows'][2] = reordered['rows'][2], reordered['rows'][0]
        revalued = deepcopy(original)
        revalued['rows'][0]['values']['reading'] = 8
        zero_without_proof = deepcopy(json.loads(zero_bytes))
        del zero_without_proof['proof']
        # 另一日版：追加一条意见后重新冻结，版身份与锚均不同
        refs = tuple(row.observation.ref for row in revision.rows)
        extra = amend(source, refs[0], '复核', '复审员')
        other = freeze_day(source, case['site'], case['day'],
                           tuple(row.amendment.amendment_id for row in revision.rows
                                 if row.amendment is not None) + (extra.amendment_id,))
        other_anchor = seal_scope(source, other.revision_id)
        other_grant = grant_scope(source, other.revision_id,
                                  'collector-2', 'out.log', ('reading',))
        other_bytes = issue_scoped(source, other_grant)
        assert other.revision_id != revision.revision_id

    tampered = {
        '漏行（删第3次）': json.dumps(deleted).encode('utf-8'),
        '同值换件（以内检替外送）': json.dumps(substituted).encode('utf-8'),
        '乱序（交换外送行）': json.dumps(reordered).encode('utf-8'),
        '改值（7改8）': json.dumps(revalued).encode('utf-8'),
        '串版（另一日版原件）': other_bytes,
        '零行去证明': json.dumps(zero_without_proof).encode('utf-8'),
    }
    with closing(open_remote(remote_path)) as remote:
        for label, payload in tampered.items():
            try:
                if label == '串版（另一日版原件）':
                    reconcile_scoped(remote, other_anchor, other_grant, shipment_bytes)
                elif label == '零行去证明':
                    reconcile_scoped(remote, zero_anchor, zero_trusted, payload)
                else:
                    reconcile_scoped(remote, trusted_anchor, trusted_grant, payload)
            except ValueError as exc:
                print(f'拒签 {label}: {exc}')
            else:
                raise AssertionError('tampered shipment was accepted: ' + label)
        assert remote.execute('SELECT COUNT(*) FROM signed_reports').fetchone() == (0,)

        # 真件验明：匹配测次各到一次，冻结原序、出处、获准列相符
        signed = reconcile_scoped(remote, trusted_anchor, trusted_grant, shipment_bytes)
        expected_positions = [1, 3, 4]
        expected_readings = [7, None, 7]
        assert [row['reference']['position'] for row in signed.rows] == expected_positions
        assert [row['values']['reading'] for row in signed.rows] == expected_readings
        assert signed.row_count == 3 and signed.non_null == {'reading': 2}
        assert signed.scope == grant
        # 无匹配组合凭完整证据签零行
        zero_report = reconcile_scoped(remote, zero_anchor, zero_trusted, zero_bytes)
        assert zero_report.row_count == 0 and zero_report.non_null == {'reading': 0}
        report_id = signed.report_id
        zero_id = zero_report.report_id

    # 断源重开异地仓，按报告号复领授权、明细与每列非空数
    with closing(open_remote(remote_path)) as reopened:
        retrieved = retrieve(reopened, report_id)
        zero_again = retrieve(reopened, zero_id)
    assert retrieved == signed and zero_again == zero_report
    summary = {
        'revision_id': revision.revision_id,
        'grant': grant,
        'positions': expected_positions,
        'readings': expected_readings,
        'row_count': signed.row_count,
        'non_null': signed.non_null,
        'zero_row_scope': zero_report.scope['log'],
        'report_id': report_id,
        'retrieved_after_reopen': asdict(retrieved),
    }
    print('SCOPED_HANDOFF ' + json.dumps(summary, ensure_ascii=False, sort_keys=True))


def main():
    sample_path = Path(__file__).resolve().parent / 'samples' / 'kiln.json'
    sample = json.loads(sample_path.read_text(encoding='utf-8'))
    selected = ('reading', 'quality')
    with TemporaryDirectory(prefix='haijiao-lake-') as directory:
        root = Path(directory)
        with closing(open_source(root / 'source.sqlite')) as source:
            refs = ingest(source, sample['site'], sample['day'], sample['batch'], sample['records'])
            amendments = [amend(source, ref, status, sample['author']).amendment_id
                          for ref, status in zip(refs, sample['quality'], strict=True)]
            revision = freeze_day(source, sample['site'], sample['day'], amendments)
            shipment = issue(source, revision.revision_id, (*selected, 'temperature'))
            paths = [root / f'piece-{number:02d}.json'
                     for number in range(1, len(shipment.materials) + 1)]
            for path, raw in zip(paths, shipment.materials, strict=True):
                path.write_bytes(raw)

        remote_path = root / 'remote.sqlite'
        with closing(open_remote(remote_path)) as remote:
            receipt_ids = []
            delayed = None
            repeat = None
            for path in reversed(paths):
                raw = path.read_bytes()
                material = verify_material(raw)
                if material.column == 'temperature':
                    continue
                if (material.kind, material.column, material.number) == ('volume', 'reading', 2):
                    delayed = path
                    continue
                receipt_id = receive(remote, raw)
                receipt_ids.append(receipt_id)
                if material.kind == 'volume':
                    repeat = raw, receipt_id
            assert repeat is not None and receive(remote, repeat[0]) == repeat[1]
            assert delayed is not None
            try:
                reconcile_columns(remote, revision.revision_id, receipt_ids, selected)
            except PendingMaterials as pending:
                assert pending.columns == ('reading',)
                assert remote.execute('SELECT COUNT(*) FROM signed_reports').fetchone() == (0,)
                print('待件', ','.join(pending.columns))
            else:
                raise AssertionError('partial reading column was signed')
            receipt_ids.append(receive(remote, delayed.read_bytes()))
            report = reconcile_columns(remote, revision.revision_id, receipt_ids, selected)
            expected = [[1, 7, '通过', 41], [2, None, '复核', 42], [3, 7, '剔除', 43]]
            expected_counts = {'reading': 2, 'quality': 3}
            actual = _triples(report)
            assert actual == expected, ('OBSERVATION_COLUMN_MISMATCH', actual)
            assert report.non_null == expected_counts

        with closing(open_remote(remote_path)) as reopened:
            retrieved = retrieve(reopened, report.report_id)
            assert retrieved == report
            print(json.dumps(asdict(retrieved), ensure_ascii=False, sort_keys=True))
            evidence = {
                'case_id': 'v4',
                'input': {'source': sample, 'columns': selected, 'receipt_ids': receipt_ids},
                'expected': expected,
                'actual': actual,
                'downstream_expected': {'rows': expected, 'non_null': expected_counts},
                'downstream_actual': {'rows': _triples(retrieved), 'non_null': retrieved.non_null},
                'code_paths': ['lake/edition/planning.py', 'lake/edition/basis.py',
                               'lake/receiving/coverage.py', 'lake/receiving/reconstruct.py',
                               'lake/reporting/sign.py', 'lake/reporting/retrieve.py'],
                'oracle': '按设备日志 41、42、43 手算原序测次和质控，分别数两个整数和三条意见。',
            }
            print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))

        demonstrate_scoped_handoff(root)


if __name__ == '__main__':
    main()
