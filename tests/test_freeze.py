from lake.intake.batches import ingest
from lake.intake.observations import ObservationRef
from lake.intake.store import find_observation
from lake.quality.amendments import amend, load_amendment
from lake.quality.freeze import freeze_day
from lake.quality.revisions import load_revision
from tests.fixtures import DAY, SITE, LakeTestCase, sample_records


class FreezeTests(LakeTestCase):
    def test_freeze_preserves_old_quality_and_equal_readings(self):
        refs, amendments, old = self.seed()
        correction = amend(self.source, refs[1], '通过', '复审员')
        new = freeze_day(self.source, SITE, DAY, (correction.amendment_id, *amendments))
        self.assertNotEqual(old.revision_id, new.revision_id)
        self.source.close()
        self.source = self.connect_source()
        archived = load_revision(self.source, old.revision_id)
        self.assertEqual(archived, old)
        self.assertEqual(tuple(row.observation.ref for row in archived.rows), refs)
        self.assertEqual([row.observation.reading for row in archived.rows], [7, None, 7])
        self.assertEqual([row.observation.provenance.line for row in archived.rows], [41, 42, 43])
        self.assertEqual([row.quality for row in archived.rows], ['通过', '复核', '剔除'])
        current = load_revision(self.source, new.revision_id)
        self.assertEqual([row.quality for row in current.rows], ['通过', '通过', '剔除'])
        self.assertEqual(current.rows[1].amendment, correction)

    def test_reopen_source(self):
        refs, amendments, original = self.seed()
        self.source.close()
        self.source = self.connect_source()
        self.assertEqual(load_revision(self.source, original.revision_id), original)
        self.assertEqual(load_amendment(self.source, amendments[1]).ref, refs[1])
        extra = ingest(self.source, SITE, DAY, '新到原批', sample_records()[:1])
        self.assertEqual(find_observation(self.source, extra[0]).reading, 7)
        self.source.close()
        self.source = self.connect_source()
        revision = freeze_day(self.source, SITE, DAY, amendments)
        self.assertEqual(tuple(row.observation.ref for row in revision.rows), (*refs, *extra))
        self.assertIsNone(revision.rows[-1].amendment)
        self.assertEqual(load_revision(self.source, original.revision_id), original)

    def test_batch_retry(self):
        records = sample_records()
        original = ingest(self.source, SITE, DAY, 'K2', records)
        self.source.close()
        self.source = self.connect_source()
        replay = ingest(self.source, SITE, DAY, 'K2', sample_records())
        self.assertEqual(replay, original)
        revision = freeze_day(self.source, SITE, DAY)
        self.assertEqual(tuple(row.observation.ref for row in revision.rows), original)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM source_batches').fetchone(), (1,))

    def test_batch_order(self):
        first = ingest(self.source, SITE, DAY, 'Z', sample_records()[:2])
        second = ingest(self.source, SITE, DAY, 'A', sample_records()[2:])
        ingest(self.source, SITE, '2026-11-18', 'Z', sample_records())
        revision = freeze_day(self.source, SITE, DAY)
        self.assertEqual(tuple(row.observation.ref for row in revision.rows), (*first, *second))
        self.assertEqual([row.observation.provenance.line for row in revision.rows], [41, 42, 43])

    def test_invalid_amendment(self):
        refs, amendments, original = self.seed()
        unknown = ObservationRef(SITE, DAY, 'missing', 1)
        with self.assertRaises(LookupError):
            amend(self.source, unknown, '通过', '复审员')
        with self.assertRaises(ValueError):
            amend(self.source, refs[1], '已清洗', '复审员')
        with self.assertRaises(ValueError):
            amend(self.source, refs[1], '通过', ' ')
        self.assertEqual(load_amendment(self.source, amendments[1]).decision.status, '复核')
        self.assertEqual(load_revision(self.source, original.revision_id), original)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM quality_amendments').fetchone(), (3,))

    def test_foreign_amendment(self):
        _, _, original = self.seed()
        (ref,) = ingest(self.source, '邻站', DAY, 'K2', sample_records()[:1])
        foreign = amend(self.source, ref, '通过', '邻站质控员')
        with self.assertRaises(ValueError):
            freeze_day(self.source, SITE, DAY, (foreign.amendment_id,))
        with self.assertRaises(LookupError):
            freeze_day(self.source, SITE, DAY, (foreign.amendment_id + 1,))
        self.assertEqual(load_revision(self.source, original.revision_id), original)
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM day_revisions').fetchone(), (1,))

    def test_invalid_batch_is_atomic(self):
        for bad_value in ('11', True, 11.0):
            with self.subTest(value=bad_value):
                records = sample_records()[:2]
                records[1]['reading'] = bad_value
                with self.assertRaises(ValueError):
                    ingest(self.source, SITE, DAY, 'bad', records)
        self.source.close()
        self.source = self.connect_source()
        with self.assertRaises(LookupError):
            find_observation(self.source, ObservationRef(SITE, DAY, 'bad', 1))
        self.assertEqual(self.source.execute('SELECT COUNT(*) FROM source_batches').fetchone(), (0,))
        self.assertEqual(freeze_day(self.source, SITE, DAY).rows, ())

    def test_batch_conflict_preserves_original(self):
        records = sample_records()
        refs = ingest(self.source, SITE, DAY, 'K2', records)
        with self.assertRaises(ValueError):
            ingest(self.source, SITE, DAY, 'K2', sample_records((7, 11, 7)))
        rows = freeze_day(self.source, SITE, DAY).rows
        self.assertEqual(tuple(row.observation.ref for row in rows), refs)
        self.assertEqual([row.observation.reading for row in rows], [7, None, 7])
        self.assertEqual([row.observation.provenance.line for row in rows], [41, 42, 43])
