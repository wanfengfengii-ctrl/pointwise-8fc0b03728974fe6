import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.intake.batches import ingest
from lake.quality.amendments import amend
from lake.quality.freeze import freeze_day
from lake.receiving.accept import receive
from lake.receiving.verify import verify_material
from lake.storage import open_remote, open_source


SITE = '海岬窑线'
DAY = '2026-11-17'
SELECTED = ('reading', 'quality')


def sample_records(readings=(7, None, 7), temperatures=(20, 21, 22)):
    path = Path(__file__).resolve().parents[1] / 'samples' / 'kiln.json'
    sample = json.loads(path.read_text(encoding='utf-8'))
    for record, reading, temperature in zip(sample['records'], readings, temperatures, strict=True):
        record['reading'] = reading
        record['temperature'] = temperature
    return sample['records']


def expected_rows(readings=(7, None, 7)):
    return tuple({
        'reference': {'site': SITE, 'day': DAY, 'batch': 'K2', 'position': position},
        'provenance': {'device': 'collector-2', 'log': 'stack-day.log', 'line': line, 'unit': 'mg/m³'},
        'values': {'reading': reading, 'quality': quality},
    } for position, line, reading, quality in zip(
        (1, 2, 3), (41, 42, 43), readings, ('通过', '复核', '剔除'), strict=True))


def one_piece(shipment, kind, column='', number=0):
    candidates = []
    for raw in shipment.materials:
        material = verify_material(raw)
        if (material.kind, material.column, material.number) == (kind, column, number):
            candidates.append(raw)
    (raw,) = candidates
    return raw


class LakeTestCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='haijiao-test-')
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.source_path = root / 'source.sqlite'
        self.remote_path = root / 'remote.sqlite'
        self.source = self.connect_source()
        self.remote = self.connect_remote()

    def connect_source(self):
        db = open_source(self.source_path)
        self.addCleanup(db.close)
        return db

    def connect_remote(self):
        db = open_remote(self.remote_path)
        self.addCleanup(db.close)
        return db

    def seed(self, readings=(7, None, 7), temperatures=(20, 21, 22)):
        refs = ingest(self.source, SITE, DAY, 'K2', sample_records(readings, temperatures))
        amendments = tuple(amend(self.source, ref, status, '白班质控员').amendment_id
                           for ref, status in zip(refs, ('通过', '复核', '剔除'), strict=True))
        return refs, amendments, freeze_day(self.source, SITE, DAY, amendments)

    def deliver(self, pieces):
        return tuple(receive(self.remote, raw) for raw in pieces)

    def report_ids(self):
        return tuple(number for (number,) in self.remote.execute(
            'SELECT report_id FROM signed_reports ORDER BY report_id'))
