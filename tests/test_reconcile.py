from lake.edition.column_codec import decode_volume, encode_volume
from lake.edition.publish import issue
from lake.receiving.accept import receive
from lake.receiving.coverage import PendingMaterials
from lake.receiving.verify import MaterialConflict, verify_material
from lake.reporting.retrieve import retrieve
from lake.reporting.sign import reconcile_columns
from tests.fixtures import SELECTED, LakeTestCase, expected_rows, one_piece


class ReconcileTests(LakeTestCase):
    def test_offline_reconstruct(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        quality_order = [value for number in (1, 2) for value in decode_volume(
            one_piece(shipment, 'volume', 'quality', number)).body['values']]
        self.assertEqual(quality_order, ['剔除', '通过', '复核'])
        self.assertEqual([decode_volume(one_piece(shipment, 'volume', 'reading', number)).body['values']
                          for number in (1, 2)], [[7], [7]])
        self.source.close()
        pieces = shipment.materials[::-1]
        receipts = self.deliver(pieces)
        repeated = receive(self.remote, pieces[0])
        self.assertEqual(repeated, receipts[0])
        report = reconcile_columns(self.remote, revision.revision_id, (*receipts, repeated), SELECTED)
        self.assertEqual(report.rows, expected_rows(), 'OBSERVATION_COLUMN_MISMATCH')
        self.assertEqual(report.row_count, 3)
        self.assertEqual(report.non_null, {'reading': 2, 'quality': 3})
        self.assertEqual(retrieve(self.remote, report.report_id), report)

    def test_column_counts_include_zero_and_preserve_wide_integer(self):
        readings = (0, None, 7)
        _, _, revision = self.seed(readings)
        shipment = issue(self.source, revision.revision_id, SELECTED)
        wide = 2**100 + 17
        _, _, wide_revision = self.seed((wide, None, -wide), (20, 21, 22)) if False else (None, None, None)
        self.source.close()
        receipts = self.deliver(shipment.materials)
        report = reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)
        self.assertEqual(report.rows, expected_rows(readings))
        self.assertEqual(report.non_null, {'reading': 2, 'quality': 3})
        self.assertEqual(retrieve(self.remote, report.report_id).non_null, {'reading': 2, 'quality': 3})

    def test_integer_precision_through_storage_and_transfer(self):
        wide = 2**100 + 17
        readings = (wide, None, -wide)
        _, _, revision = self.seed(readings)
        shipment = issue(self.source, revision.revision_id, SELECTED)
        self.source.close()
        report = reconcile_columns(self.remote, revision.revision_id,
                                   self.deliver(shipment.materials), SELECTED)
        self.assertEqual(report.rows, expected_rows(readings))
        self.assertEqual(retrieve(self.remote, report.report_id), report)

    def test_material_conflict_does_not_sign(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        original = one_piece(shipment, 'volume', 'reading', 2)
        mismatched = encode_volume(revision.revision_id, shipment.issue_id, 'reading', 2, [19])
        self.source.close()
        receipts = self.deliver(mismatched if piece == original else piece for piece in shipment.materials)
        self.assertEqual(len(receipts), len(shipment.materials))
        with self.assertRaises(MaterialConflict):
            reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)
        self.assertEqual(self.report_ids(), ())

    def test_selected_column_gap(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, (*SELECTED, 'temperature'))
        missing = one_piece(shipment, 'volume', 'reading', 2)
        self.source.close()
        partial = tuple(piece for piece in shipment.materials
                        if piece != missing and verify_material(piece).column != 'temperature')
        receipts = self.deliver(partial[::-1])
        with self.assertRaises(PendingMaterials) as pending:
            reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)
        self.assertEqual(pending.exception.columns, ('reading',))
        self.assertEqual(self.report_ids(), ())
        receipts += self.deliver((missing,))
        signed = reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)
        self.assertEqual(signed.rows, expected_rows())
        self.assertEqual(signed.non_null, {'reading': 2, 'quality': 3})
        self.assertEqual(self.report_ids(), (signed.report_id,))

    def test_receipt_scope(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        withheld = one_piece(shipment, 'volume', 'reading', 2)
        self.source.close()
        stored = receive(self.remote, withheld)
        scope = self.deliver(piece for piece in shipment.materials if piece != withheld)
        with self.assertRaises(PendingMaterials):
            reconcile_columns(self.remote, revision.revision_id, scope, SELECTED)
        self.assertEqual(self.report_ids(), ())
        signed = reconcile_columns(self.remote, revision.revision_id, (*scope, stored), SELECTED)
        self.assertEqual(signed.rows, expected_rows())

    def test_all_null_requires_explicit_column_basis(self):
        _, _, revision = self.seed(temperatures=(None, None, None))
        shipment = issue(self.source, revision.revision_id, ('temperature',))
        self.source.close()
        register = one_piece(shipment, 'row_register')
        basis = one_piece(shipment, 'column_basis', 'temperature')
        self.assertEqual(shipment.materials, (register, basis))
        ids = self.deliver((register,))
        with self.assertRaises(PendingMaterials):
            reconcile_columns(self.remote, revision.revision_id, ids, ('temperature',))
        self.assertEqual(self.report_ids(), ())
        ids += self.deliver((basis,))
        signed = reconcile_columns(self.remote, revision.revision_id, ids, ('temperature',))
        expected = tuple({**row, 'values': {'temperature': None}} for row in expected_rows())
        self.assertEqual(signed.rows, expected)
        self.assertEqual(signed.row_count, 3)
        self.assertEqual(signed.non_null, {'temperature': 0})

    def test_independent_issuances_can_supply_distinct_columns(self):
        _, _, revision = self.seed()
        reading = issue(self.source, revision.revision_id, ('reading',))
        quality = issue(self.source, revision.revision_id, ('quality',))
        self.source.close()
        receipts = self.deliver((*quality.materials, *reading.materials))
        report = reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)
        self.assertEqual(report.rows, expected_rows())

    def test_partial_issuances_cannot_share_one_columns_volumes(self):
        _, _, revision = self.seed()
        first = issue(self.source, revision.revision_id, ('reading',))
        second = issue(self.source, revision.revision_id, ('reading',))
        self.source.close()
        only_first = one_piece(first, 'volume', 'reading', 1)
        only_second = one_piece(second, 'volume', 'reading', 2)
        receipts = self.deliver((one_piece(first, 'row_register'),
                                 one_piece(first, 'column_basis', 'reading'), only_first,
                                 one_piece(second, 'column_basis', 'reading'), only_second))
        with self.assertRaises(PendingMaterials):
            reconcile_columns(self.remote, revision.revision_id, receipts, ('reading',))
        self.assertEqual(self.report_ids(), ())
        receipts += self.deliver((one_piece(first, 'volume', 'reading', 2),))
        report = reconcile_columns(self.remote, revision.revision_id, receipts, ('reading',))
        self.assertEqual([row['values']['reading'] for row in report.rows], [7, None, 7])
