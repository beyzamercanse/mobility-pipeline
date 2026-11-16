from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from generate_demo import generate, write_batch
from pipeline import connect, export, ingest


class RestatementTests(unittest.TestCase):
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

    def day(self, data, date='2026-01-01'):
        return next(r for r in data['restatements'] if r['date'] == date)

    def test_late_arrival_restates_the_original_day(self):
        ingest(self.con, self.batch('a', [self.row]))
        late = dict(self.row, trip_id='late', received_at='2026-01-03T09:00:00Z')
        ingest(self.con, self.batch('b', [late]))
        day = self.day(export(self.con, self.root / 'out.json'))
        self.assertEqual((day['first_trips'], day['final_trips'], day['trip_change']), (1, 2, 1))
        self.assertEqual((day['revisions'], day['last_changed_by']), (1, 'b'))

    def test_correction_changes_fare_but_not_trip_count(self):
        ingest(self.con, self.batch('a', [self.row]))
        fixed = dict(self.row, fare_usd=22.5, updated_at='2026-01-02T08:00:00Z', received_at='2026-01-02T08:05:00Z')
        ingest(self.con, self.batch('b', [fixed]))
        data = export(self.con, self.root / 'out.json')
        day = self.day(data)
        self.assertEqual(day['trip_change'], 0)
        self.assertAlmostEqual(day['fare_change_usd'], 2.5)
        self.assertEqual(data['restatements_by_batch'], [{'batch_id': 'b', 'trip_change': 0, 'fare_change_usd': 2.5, 'days_changed': 1}])

    def test_pure_duplicate_batch_is_not_a_restatement(self):
        ingest(self.con, self.batch('a', [self.row]))
        ingest(self.con, self.batch('b', [self.row]))
        day = self.day(export(self.con, self.root / 'out.json'))
        self.assertEqual((day['revisions'], day['last_changed_by']), (0, None))

    def test_failed_batch_leaves_no_snapshot(self):
        ingest(self.con, self.batch('a', [self.row]))
        path = self.batch('b', [dict(self.row, trip_id='x'), dict(self.row, trip_id='y')])
        with self.assertRaises(RuntimeError):
            ingest(self.con, path, fail_after=1)
        seqs = {r[0] for r in self.con.execute('SELECT DISTINCT batch_id FROM daily_snapshots')}
        self.assertEqual(seqs, {'a'})

    def test_skipped_replay_adds_no_snapshot(self):
        path = self.batch('a', [self.row])
        ingest(self.con, path)
        ingest(self.con, path)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM daily_snapshots').fetchone()[0], 1)

    def test_fixture_restatements_reconcile_with_batches(self):
        generate(self.root)
        for path in sorted(self.root.glob('*.manifest.json')):
            ingest(self.con, path)
        data = export(self.con, self.root / 'out.json')
        late = next(b for b in data['batches'] if b['batch_id'] == '02-late-arrivals')
        by_batch = {b['batch_id']: b for b in data['restatements_by_batch']}
        # Every late row is a new trip on an already-published day.
        self.assertEqual(by_batch['02-late-arrivals']['trip_change'], late['accepted_rows'])
        self.assertEqual(by_batch['03-corrections']['trip_change'], 0)
        self.assertEqual(data['summary']['restated_trips'], late['accepted_rows'])
        self.assertTrue(all(c['passed'] for c in data['quality_checks']))


if __name__ == '__main__':
    unittest.main()
