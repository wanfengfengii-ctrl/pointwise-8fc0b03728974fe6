import copy
import json
import unittest
from contextlib import closing

from lake.edition.anchor import decode_anchor
from lake.edition.publish import grant_scope, issue_scoped, seal_scope
from lake.reporting.retrieve import retrieve
from lake.reporting.sign import reconcile_columns, reconcile_scoped
from lake.storage import open_remote, open_source
from scope_fixture import load_case, populate, trusted_inputs
from tests.fixtures import LakeTestCase

DEVICE = 'collector-2'
OUT_LOG = 'out.log'
INTERNAL_LOG = 'internal.log'
ABSENT_LOG = 'absent.log'


class ScopedHandoffTests(LakeTestCase):
    def setUp(self):
        super().setUp()
        self.case = load_case()
        self.revision = populate(self.source, self.case)
        self.revision_id = self.revision.revision_id

    def seal(self):
        return seal_scope(self.source, self.revision_id)

    def grant(self, log=OUT_LOG, columns=('reading',), device=DEVICE):
        return grant_scope(self.source, self.revision_id, device, log, columns)

    def issue(self, grant):
        return issue_scoped(self.source, grant)

    def sign(self, anchor, grant, raw):
        trusted_anchor, trusted_grant = trusted_inputs(anchor, grant)
        return reconcile_scoped(self.remote, trusted_anchor, trusted_grant, raw)

    def shipment(self, raw):
        return json.loads(raw)

    def mutate(self, raw):
        return copy.deepcopy(self.shipment(raw))

    def reject(self, anchor, grant, raw, *, close_source=False):
        if close_source:
            self.source.close()
            self.source = self.connect_source()
        before = self.report_ids()
        with self.assertRaises(ValueError):
            self.sign(anchor, grant, raw)
        self.assertEqual(self.report_ids(), before)

    def test_anchor_is_fixed_before_grants_and_stable_across_reopen(self):
        with self.assertRaises(LookupError):
            self.grant()
        anchor = self.seal()
        parsed_id, digest = decode_anchor(anchor)
        self.assertEqual(parsed_id, self.revision_id)
        self.assertEqual(self.seal(), anchor)
        self.source.close()
        self.source = self.connect_source()
        self.assertEqual(seal_scope(self.source, self.revision_id), anchor)
        first = self.grant()
        reopened = grant_scope(self.source, self.revision_id, DEVICE, OUT_LOG, ('reading',))
        self.assertEqual(reopened, first)

    def test_sealing_unknown_revision_looks_up_nothing(self):
        with self.assertRaises(LookupError):
            seal_scope(self.source, 'rev-unknown')

    def test_grant_rejects_invalid_arguments(self):
        self.seal()
        for device, log, columns in (
            (' ', OUT_LOG, ('reading',)),
            (DEVICE, '', ('reading',)),
            (DEVICE, OUT_LOG, ()),
            (DEVICE, OUT_LOG, ('reading', 'reading')),
            (DEVICE, OUT_LOG, ('unknown',)),
        ):
            with self.assertRaises(ValueError):
                grant_scope(self.source, self.revision_id, device, log, columns)

    def test_grant_carries_only_the_five_authorized_fields(self):
        anchor = self.seal()
        grant = self.grant()
        self.assertEqual(set(grant), {'revision_id', 'device', 'log', 'columns', 'selector'})
        self.assertEqual(grant['columns'], ['reading'])
        self.assertIsInstance(grant['selector'], str)
        self.assertEqual(len(grant['selector']), 64)
        _, digest = decode_anchor(anchor)
        from lake.edition.scope_grants import build_selector
        self.assertEqual(grant['selector'], build_selector(digest, DEVICE, OUT_LOG))
        serialized = json.dumps(grant)
        for forbidden in ('row_count', 'non_null', 'expected', '行数', '摘要'):
            self.assertNotIn(forbidden, serialized)

    def test_scoped_signing_keeps_matching_observations_in_frozen_order(self):
        anchor = self.seal()
        grant = self.grant()
        report = self.sign(anchor, grant, self.issue(grant))
        positions = [row['reference']['position'] for row in report.rows]
        readings = [row['values']['reading'] for row in report.rows]
        self.assertEqual(positions, [1, 3, 4])
        self.assertEqual(readings, [7, None, 7])
        self.assertEqual(report.row_count, 3)
        self.assertEqual(report.non_null, {'reading': 2})
        self.assertEqual(report.columns, ('reading',))
        self.assertEqual(report.scope, grant)
        # equal readings keep their own references and provenance
        first, fourth = report.rows[0], report.rows[2]
        self.assertEqual(first['values'], fourth['values'])
        self.assertNotEqual(first['reference'], fourth['reference'])
        self.assertEqual(first['provenance'], fourth['provenance'])
        # the internal.log observation never leaves the source
        self.assertTrue(all(row['provenance']['log'] == OUT_LOG for row in report.rows))
        self.assertTrue(all(set(row['values']) == {'reading'} for row in report.rows))

    def test_null_reading_still_lists_its_original_row(self):
        null_case = copy.deepcopy(self.case)
        for record in null_case['records']:
            if record['provenance']['log'] == OUT_LOG:
                record['reading'] = None
        with closing(open_source(':memory:')) as null_source, \
                closing(open_remote(':memory:')) as remote:
            revision = populate(null_source, null_case)
            anchor = seal_scope(null_source, revision.revision_id)
            grant = grant_scope(null_source, revision.revision_id, DEVICE, OUT_LOG,
                                ('reading',))
            raw = issue_scoped(null_source, grant)
            report = reconcile_scoped(remote, *trusted_inputs(anchor, grant), raw)
        self.assertEqual([row['reference']['position'] for row in report.rows], [1, 3, 4])
        self.assertEqual([row['values']['reading'] for row in report.rows], [None, None, None])
        self.assertEqual(report.row_count, 3)
        self.assertEqual(report.non_null, {'reading': 0})
        self.assertEqual(report.rows[1]['provenance']['line'], 43)

    def test_absent_combination_signs_zero_rows_with_complete_proof(self):
        anchor = self.seal()
        grant = self.grant(log=ABSENT_LOG)
        raw = self.issue(grant)
        self.assertEqual(self.shipment(raw)['rows'], [])
        report = self.sign(anchor, grant, raw)
        self.assertEqual(report.rows, ())
        self.assertEqual(report.row_count, 0)
        self.assertEqual(report.non_null, {'reading': 0})
        self.assertEqual(report.scope, grant)
        stripped = self.mutate(raw)
        del stripped['proof']
        self.reject(anchor, grant, json.dumps(stripped).encode('utf-8'))

    def test_missing_row_rejected_without_a_report(self):
        anchor = self.seal()
        grant = self.grant()
        shipment = self.mutate(self.issue(grant))
        shipment['rows'].pop(1)
        self.reject(anchor, grant, json.dumps(shipment).encode('utf-8'))

    def test_same_value_substitution_is_detected(self):
        anchor = self.seal()
        grant = self.grant()
        shipment = self.mutate(self.issue(grant))
        internal = next(row for row in self.revision.rows
                        if row.observation.provenance.log == INTERNAL_LOG)
        ref = internal.observation.ref
        shipment['rows'][2] = {
            'reference': ref.to_record(),
            'provenance': {
                'device': internal.observation.provenance.device,
                'log': internal.observation.provenance.log,
                'line': internal.observation.provenance.line,
                'unit': internal.observation.provenance.unit,
            },
            'values': {'reading': 7},
        }
        self.reject(anchor, grant, json.dumps(shipment).encode('utf-8'))

    def test_reordered_rows_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        shipment = self.mutate(self.issue(grant))
        shipment['rows'][0], shipment['rows'][2] = shipment['rows'][2], shipment['rows'][0]
        self.reject(anchor, grant, json.dumps(shipment).encode('utf-8'))

    def test_changed_value_and_broken_proof_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        changed = self.mutate(self.issue(grant))
        changed['rows'][0]['values']['reading'] = 8
        self.reject(anchor, grant, json.dumps(changed).encode('utf-8'))
        broken = self.mutate(self.issue(grant))
        broken['proof'] = '0' * 64
        self.reject(anchor, grant, json.dumps(broken).encode('utf-8'))

    def test_duplicate_and_extra_column_rows_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        duplicated = self.mutate(self.issue(grant))
        duplicated['rows'].append(duplicated['rows'][0])
        self.reject(anchor, grant, json.dumps(duplicated).encode('utf-8'))
        widened = self.mutate(self.issue(grant))
        widened['rows'][0]['values']['temperature'] = 818271
        self.reject(anchor, grant, json.dumps(widened).encode('utf-8'))

    def test_cross_revision_anchor_and_grant_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        raw = self.issue(grant)
        other = populate(self.source, self.case)
        other_anchor = seal_scope(self.source, other.revision_id)
        other_grant = grant_scope(self.source, other.revision_id, DEVICE, OUT_LOG, ('reading',))
        other_raw = issue_scoped(self.source, other_grant)
        self.reject(other_anchor, grant, raw)
        self.reject(anchor, other_grant, raw)
        self.reject(anchor, grant, other_raw)

    def test_malformed_shipments_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        self.issue(grant)
        for payload in (b'', b'{not json', 'plain text', 123, None,
                        json.dumps({'version': 1}).encode('utf-8')):
            self.reject(anchor, grant, payload)

    def test_tampered_grant_fields_are_rejected(self):
        anchor = self.seal()
        grant = self.grant()
        raw = self.issue(grant)
        for tampered in (
            {**grant, 'selector': '0' * 64},
            {**grant, 'log': INTERNAL_LOG},
            {**grant, 'columns': ['reading', 'temperature']},
            {**grant, 'revision_id': self.revision_id + 'x'},
            {'revision_id': grant['revision_id']},
            {**grant, 'extra': 1},
        ):
            self.reject(anchor, tampered, raw)

    def test_multi_column_grant_signs_each_authorized_column(self):
        anchor = self.seal()
        grant = self.grant(columns=('reading', 'quality', 'temperature'))
        report = self.sign(anchor, grant, self.issue(grant))
        self.assertEqual(report.columns, ('reading', 'quality', 'temperature'))
        values = [tuple(row['values'][column]
                        for column in ('reading', 'quality', 'temperature'))
                  for row in report.rows]
        self.assertEqual(values,
                         [(7, '通过', 818271), (None, '复核', None), (7, '剔除', 818274)])
        self.assertEqual(report.non_null,
                         {'reading': 2, 'quality': 3, 'temperature': 2})

    def test_shipment_leaks_no_hidden_rows_columns_or_counts(self):
        self.seal()
        grant = self.grant()
        text = self.issue(grant).decode('utf-8')
        self.assertNotIn(INTERNAL_LOG, text)
        self.assertNotIn('temperature', text)
        self.assertNotIn('row_count', text)
        self.assertNotIn('non_null', text)
        envelope = json.loads(text)
        self.assertEqual(set(envelope), {'version', 'revision_id', 'rows', 'proof'})

    def test_report_is_retrievable_after_remote_reopen(self):
        anchor = self.seal()
        grant = self.grant()
        report = self.sign(anchor, grant, self.issue(grant))
        self.remote.close()
        with closing(self.connect_remote()) as remote:
            self.assertEqual(retrieve(remote, report.report_id), report)
            with self.assertRaises(LookupError):
                retrieve(remote, report.report_id + 100)

    def test_v1_full_handoff_still_works_alongside_scoped_reports(self):
        from lake.edition.publish import issue
        from lake.receiving.accept import receive
        self.seal()
        shipment = issue(self.source, self.revision_id, ('reading', 'quality'))
        self.source.close()
        receipts = tuple(receive(self.remote, raw) for raw in shipment.materials)
        legacy = reconcile_columns(self.remote, self.revision_id, receipts,
                                   ('reading', 'quality'))
        self.assertIsNone(legacy.scope)
        self.assertEqual(legacy.row_count, 4)
        self.assertEqual(legacy.non_null, {'reading': 3, 'quality': 4})
        # scoped and V1 reports coexist in one directory and keep their identities
        self.source = self.connect_source()
        anchor = seal_scope(self.source, self.revision_id)
        grant = grant_scope(self.source, self.revision_id, DEVICE, OUT_LOG, ('reading',))
        scoped = self.sign(anchor, grant, issue_scoped(self.source, grant))
        self.assertNotEqual(scoped.report_id, legacy.report_id)
        self.assertEqual(retrieve(self.remote, legacy.report_id), legacy)
        self.assertEqual(retrieve(self.remote, scoped.report_id), scoped)


if __name__ == '__main__':
    unittest.main()
