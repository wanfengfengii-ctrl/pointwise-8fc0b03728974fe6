import json
import sqlite3

from lake.edition.column_codec import decode_volume, encode_volume
from lake.edition.issued import load_issued_materials
from lake.edition.publish import issue
from lake.quality.amendments import amend
from lake.quality.freeze import freeze_day
from lake.receiving.accept import receive
from lake.receiving.coverage import PendingMaterials
from lake.receiving.ledger import list_issue_receipts
from lake.receiving.verify import MaterialConflict, check_volume_binding, verify_material
from lake.reporting.sign import reconcile_columns
from tests.fixtures import DAY, SELECTED, SITE, LakeTestCase, one_piece


class ExchangeTests(LakeTestCase):
    def test_reverse_receipts_are_idempotent(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        order = shipment.materials[::-1]
        receipts = self.deliver(order)
        self.assertEqual(len(set(receipts)), len(order))
        self.assertEqual(receive(self.remote, order[0]), receipts[0])
        self.remote.close()
        self.remote = self.connect_remote()
        self.assertEqual(list_issue_receipts(self.remote, revision.revision_id, shipment.issue_id), receipts)
        self.assertEqual(receive(self.remote, order[-1]), receipts[-1])

    def test_issue_rollback(self):
        _, _, revision = self.seed()
        previous = issue(self.source, revision.revision_id, ('reading',))
        self.source.execute('''
            CREATE TRIGGER refuse_second_piece AFTER INSERT ON edition_materials
            WHEN NEW.ordinal = 2 BEGIN
                SELECT RAISE(ABORT, 'edition material write refused');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'edition material write refused'):
            issue(self.source, revision.revision_id, SELECTED)
        self.source.close()
        self.source = self.connect_source()
        ids = self.source.execute('SELECT issue_id FROM edition_issues').fetchall()
        self.assertEqual(ids, [(previous.issue_id,)])
        stored_pieces = self.source.execute('SELECT COUNT(*) FROM edition_materials').fetchone()[0]
        self.assertEqual(stored_pieces, len(previous.materials))
        self.assertEqual(load_issued_materials(self.source, previous.issue_id), previous)

    def test_issue_replay(self):
        refs, opinions, revision = self.seed()
        old = issue(self.source, revision.revision_id, SELECTED)
        new_opinion = amend(self.source, refs[1], '通过', '复审员')
        newer = freeze_day(self.source, SITE, DAY, (*opinions, new_opinion.amendment_id))
        new = issue(self.source, newer.revision_id, SELECTED)
        self.source.close()
        self.source = self.connect_source()
        self.assertEqual(load_issued_materials(self.source, old.issue_id), old)
        self.assertNotEqual(new.issue_id, old.issue_id)
        self.assertNotEqual(new.materials, old.materials)
        with self.assertRaises(LookupError):
            load_issued_materials(self.source, 'missing')

    def test_bind_members_and_source_null(self):
        refs, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        self.deliver(shipment.materials[::-1])
        register = verify_material(one_piece(shipment, 'row_register')).body
        basis = verify_material(one_piece(shipment, 'column_basis', 'reading'))
        members = []
        for expected_number, descriptor in enumerate(basis.body['volumes'], 1):
            self.assertEqual(descriptor['number'], expected_number)
            volume = decode_volume(one_piece(shipment, 'volume', 'reading', expected_number))
            for ordinal, value in check_volume_binding(volume, basis, descriptor):
                members.append((register['rows'][ordinal - 1]['reference'], value))
        self.assertEqual(members, [(refs[0].to_record(), 7), (refs[2].to_record(), 7)])
        self.assertEqual(basis.body['null_rows'], [2])
        self.assertEqual(register['rows'][1]['reference'], refs[1].to_record())

    def test_receipt_conflict_rejects_bad_and_same_identity_materials(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, ('reading',))
        original = one_piece(shipment, 'volume', 'reading', 1)
        receipt = receive(self.remote, original)
        bad = json.loads(original)
        bad['body']['values'] = [19]
        with self.assertRaisesRegex(ValueError, 'checksum'):
            receive(self.remote, json.dumps(bad).encode('utf-8'))
        other = encode_volume(revision.revision_id, shipment.issue_id, 'reading', 1, [19])
        with self.assertRaises(MaterialConflict):
            receive(self.remote, other)
        self.assertEqual(receive(self.remote, original), receipt)
        self.assertEqual(list_issue_receipts(self.remote, revision.revision_id, shipment.issue_id), (receipt,))

    def test_old_revision_volume_cannot_complete_new_revision(self):
        refs, opinions, first = self.seed()
        old = issue(self.source, first.revision_id, SELECTED)
        updated = amend(self.source, refs[1], '通过', '复审员')
        second = freeze_day(self.source, SITE, DAY, (*opinions, updated.amendment_id))
        new = issue(self.source, second.revision_id, SELECTED)
        self.source.close()
        missing = one_piece(new, 'volume', 'reading', 2)
        substitute = one_piece(old, 'volume', 'reading', 2)
        self.assertEqual(decode_volume(missing).body, decode_volume(substitute).body)
        receipt_ids = self.deliver([piece for piece in new.materials if piece != missing] + [substitute])
        self.assertEqual(list_issue_receipts(self.remote, first.revision_id, old.issue_id), (receipt_ids[-1],))
        with self.assertRaises(PendingMaterials) as pending:
            reconcile_columns(self.remote, second.revision_id, receipt_ids, SELECTED)
        self.assertEqual(pending.exception.columns, ('reading',))
        self.assertEqual(self.report_ids(), ())
        receipt_ids += self.deliver((missing,))
        signed = reconcile_columns(self.remote, second.revision_id, receipt_ids, SELECTED)
        self.assertEqual([row['values']['reading'] for row in signed.rows], [7, None, 7])
        self.assertEqual([row['values']['quality'] for row in signed.rows], ['通过', '通过', '剔除'])
        self.assertEqual(self.report_ids(), (signed.report_id,))
