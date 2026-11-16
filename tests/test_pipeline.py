import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from generate_demo import generate, write_batch
from pipeline import connect, export, ingest, validate


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.con = connect(self.root / 'warehouse.sqlite')
        self.row = {'trip_id': 'one', 'pickup_at': '2026-01-01T12:00:00Z',
                    'dropoff_at': '2026-01-01T12:30:00Z', 'pickup_zone': 2,
                    'dropoff_zone': 3, 'distance_miles': 4.5, 'fare_usd': 20.0,
                    'updated_at': '2026-01-01T12:30:00Z', 'received_at': '2026-01-01T13:00:00Z'}

    def tearDown(self):
        self.con.close()
        self.temp.cleanup()

    def batch(self, name, records):
        return write_batch(self.root, name, records, '2026-01-10T00:00:00Z')

    def count(self):
        return self.con.execute('SELECT COUNT(*) FROM trips').fetchone()[0]

    def test_replaying_batch_changes_nothing(self):
        path = self.batch('one', [self.row])
        ingest(self.con, path)
        first = export(self.con, self.root / 'out.json')
        self.assertEqual(ingest(self.con, path)['status'], 'skipped_unchanged')
        self.assertEqual(first, export(self.con, self.root / 'out.json'))

    def test_duplicate_across_batches_keeps_one_fact(self):
        ingest(self.con, self.batch('one', [self.row]))
        result = ingest(self.con, self.batch('two', [self.row]))
        self.assertEqual(self.count(), 1)
        self.assertEqual(result['duplicate_rows'], 1)

    def test_new_version_corrects_prior_event_day(self):
        ingest(self.con, self.batch('one', [self.row]))
        corrected = dict(self.row, fare_usd=30, updated_at='2026-01-03T12:30:00Z', received_at='2026-01-03T13:00:00Z')
        result = ingest(self.con, self.batch('two', [corrected]))
        data = export(self.con, self.root / 'out.json')
        self.assertEqual(result['corrected_rows'], 1)
        self.assertEqual(data['daily'][0]['fare_usd'], 30)
        self.assertEqual(data['daily'][0]['date'], '2026-01-01')
        self.assertEqual(data['summary']['late_trips'], 1)

    def test_stale_version_does_not_undo_correction(self):
        newer = dict(self.row, fare_usd=30, updated_at='2026-01-03T12:30:00Z', received_at='2026-01-03T13:00:00Z')
        ingest(self.con, self.batch('new', [newer]))
        ingest(self.con, self.batch('old', [self.row]))
        self.assertEqual(self.con.execute('SELECT fare_usd FROM trips').fetchone()[0], 30)

    def test_same_version_conflict_is_quarantined(self):
        ingest(self.con, self.batch('one', [self.row]))
        result = ingest(self.con, self.batch('two', [dict(self.row, fare_usd=400)]))
        self.assertEqual(result['rejected_rows'], 1)
        self.assertEqual(self.con.execute('SELECT reason FROM quarantine').fetchone()[0], 'conflicting_version')
        self.assertEqual(self.con.execute('SELECT fare_usd FROM trips').fetchone()[0], 20)

    def test_bad_rows_are_visible_and_do_not_block_valid_rows(self):
        bad = dict(self.row)
        del bad['pickup_zone']
        result = ingest(self.con, self.batch('one', [self.row, bad, dict(self.row, fare_usd=-1)]))
        self.assertEqual(self.count(), 1)
        self.assertEqual(result['rejected_rows'], 2)
        self.assertEqual(result['raw_rows'], result['accepted_rows'] + result['rejected_rows'] + result['duplicate_rows'])

    def test_checksum_mismatch_commits_nothing(self):
        path = self.batch('one', [self.row])
        (self.root / 'one.jsonl').write_text('changed bytes\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            ingest(self.con, path)
        self.assertEqual(self.count(), 0)

    def test_unsupported_schema_commits_nothing(self):
        path = self.batch('one', [self.row])
        metadata = json.loads(path.read_text())
        metadata['schema_version'] = 2
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'schema_version'):
            ingest(self.con, path)
        self.assertEqual(self.count(), 0)

    def test_worker_failure_rolls_back_entire_batch(self):
        path = self.batch('one', [self.row, dict(self.row, trip_id='two')])
        with self.assertRaises(RuntimeError):
            ingest(self.con, path, fail_after=1)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM batches').fetchone()[0], 0)
        self.assertEqual(ingest(self.con, path)['accepted_rows'], 2)

    def test_failed_atomic_replace_preserves_dashboard(self):
        ingest(self.con, self.batch('one', [self.row]))
        output = self.root / 'dashboard.json'
        output.write_text('previous-good-dashboard')
        with patch('pipeline.os.replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                export(self.con, output)
        self.assertEqual(output.read_text(), 'previous-good-dashboard')

    def test_contract_rejects_bool_nonfinite_and_unknown_zone(self):
        for field, value in [('fare_usd', True), ('fare_usd', float('nan')), ('fare_usd', float('inf')), ('pickup_zone', 999)]:
            self.assertIsNotNone(validate(dict(self.row, **{field: value})))

    def test_full_fixture_and_reverse_arrival_order_agree(self):
        generate(self.root)
        for path in sorted(self.root.glob('*.manifest.json'), reverse=True):
            ingest(self.con, path)
        output = export(self.con, self.root / 'out.json')
        self.assertEqual(output['summary']['trips'], 7200)
        self.assertEqual(output['summary']['rejected_rows'], 80)
        self.assertTrue(all(check['passed'] for check in output['quality_checks']))
        self.assertEqual(output['summary']['fare_usd'], 170755.66)


if __name__ == '__main__':
    unittest.main()
