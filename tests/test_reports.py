import sqlite3

from lake.edition.publish import issue
from lake.reporting.retrieve import retrieve
from lake.reporting.sign import reconcile_columns
from tests.fixtures import SELECTED, LakeTestCase, expected_rows


class ReportTests(LakeTestCase):
    def _signed(self):
        _, _, revision = self.seed()
        shipment = issue(self.source, revision.revision_id, SELECTED)
        self.source.close()
        receipts = self.deliver(shipment.materials)
        return receipts, reconcile_columns(self.remote, revision.revision_id, receipts, SELECTED)

    def test_write_failure_keeps_prior_report(self):
        receipts, first = self._signed()
        before = self.report_ids()
        self.remote.execute('''
            CREATE TRIGGER refuse_report AFTER INSERT ON signed_reports BEGIN
                SELECT RAISE(ABORT, 'report write refused');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'report write refused'):
            reconcile_columns(self.remote, first.revision_id, receipts, ('quality',))
        self.remote.close()
        self.remote = self.connect_remote()
        self.assertEqual(self.report_ids(), before)
        self.assertEqual(before, (first.report_id,))
        with self.assertRaises(LookupError):
            retrieve(self.remote, first.report_id + 1)
        restored = retrieve(self.remote, first.report_id)
        self.assertEqual(restored, first)
        self.assertEqual(restored.rows, expected_rows())
        self.assertEqual(restored.non_null, {'reading': 2, 'quality': 3})

    def test_retrieve_unknown_and_repeated_original(self):
        _, first = self._signed()
        self.remote.close()
        self.remote = self.connect_remote()
        self.assertEqual(retrieve(self.remote, first.report_id), first)
        with self.assertRaises(LookupError):
            retrieve(self.remote, first.report_id + 100)
        repeated = retrieve(self.remote, first.report_id)
        self.assertEqual(repeated, first)
        self.assertEqual(repeated.rows, expected_rows())
        self.assertEqual(self.report_ids(), (first.report_id,))
