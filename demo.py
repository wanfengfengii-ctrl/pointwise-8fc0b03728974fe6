import json
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.edition.publish import issue
from lake.intake.batches import ingest
from lake.quality.amendments import amend
from lake.quality.freeze import freeze_day
from lake.receiving.accept import receive
from lake.receiving.coverage import PendingMaterials
from lake.receiving.verify import verify_material
from lake.reporting.retrieve import retrieve
from lake.reporting.sign import reconcile_columns
from lake.storage import open_remote, open_source


def _triples(report):
    return [[row['reference']['position'], row['values']['reading'],
             row['values']['quality'], row['provenance']['line']] for row in report.rows]


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


if __name__ == '__main__':
    main()
