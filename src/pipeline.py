"""Portable, transactional taxi-shaped batch pipeline. Python 3.9+; stdlib only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'trip_id', 'pickup_at', 'dropoff_at', 'pickup_zone', 'dropoff_zone', 'distance_miles', 'fare_usd', 'updated_at', 'received_at'}
ZONES = {1: 'JFK Airport', 2: 'Midtown', 3: 'Upper East Side', 4: 'Financial District', 5: 'Williamsburg', 6: 'LaGuardia Airport', 7: 'Chelsea', 8: 'Harlem'}
# Demo zone codes are intentionally NOT official TLC LocationIDs.
DDL = '''
CREATE TABLE IF NOT EXISTS batches (
 batch_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, raw_rows INTEGER NOT NULL,
 accepted_rows INTEGER NOT NULL, rejected_rows INTEGER NOT NULL,
 duplicate_rows INTEGER NOT NULL, corrected_rows INTEGER NOT NULL,
 late_rows INTEGER NOT NULL, received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
 trip_id TEXT PRIMARY KEY, pickup_at TEXT NOT NULL, dropoff_at TEXT NOT NULL,
 pickup_zone INTEGER NOT NULL, dropoff_zone INTEGER NOT NULL,
 distance_miles REAL NOT NULL, fare_usd REAL NOT NULL,
 updated_at TEXT NOT NULL, received_at TEXT NOT NULL,
 arrival_lag_hours REAL NOT NULL, source_batch TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quarantine (
 batch_id TEXT NOT NULL, row_number INTEGER NOT NULL, reason TEXT NOT NULL,
 raw_json TEXT NOT NULL, PRIMARY KEY(batch_id, row_number)
);
'''


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be text')
    dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    if dt.strftime('%Y-%m-%dT%H:%M:%SZ') != value:
        raise ValueError('timestamp must be canonical UTC')
    return dt


def validate(row):
    """Return reason or None; reject values, retain raw record for triage."""
    try:
        if not isinstance(row, dict) or set(row) != FIELDS:
            return 'schema_fields'
        if not isinstance(row['trip_id'], str) or not row['trip_id']:
            return 'trip_id'
        pickup, dropoff, update, received = [timestamp(row[k]) for k in ['pickup_at', 'dropoff_at', 'updated_at', 'received_at']]
        if not pickup < dropoff or (dropoff - pickup).total_seconds() > 6 * 3600:
            return 'trip_duration'
        if update < dropoff or received < update:
            return 'timestamp_order'
        for field in ['pickup_zone', 'dropoff_zone']:
            if type(row[field]) is not int or row[field] not in ZONES:
                return 'unknown_zone'
        for field, upper in [('distance_miles', 150), ('fare_usd', 1000)]:
            value = row[field]
            if type(value) not in (int, float) or not 0 < value <= upper:
                return 'invalid_' + field
    except (ValueError, TypeError, KeyError):
        return 'invalid_timestamp'
    return None


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con


def ingest(con, manifest_path, fail_after=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported batch schema_version; no rows committed')
    batch_id = manifest['batch_id']
    name = manifest['file']
    if Path(name).name != name:
        raise ValueError('Raw filename must be a local basename')
    raw = (manifest_path.parent / name).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    if checksum != manifest['sha256']:
        raise ValueError('Raw checksum mismatch; no rows committed')
    prior = con.execute('SELECT sha256 FROM batches WHERE batch_id=?', (batch_id,)).fetchone()
    if prior:
        if prior['sha256'] != checksum:
            raise ValueError('Immutable batch_id reused with different bytes')
        return {'batch_id': batch_id, 'status': 'skipped_unchanged'}
    lines = raw.decode('utf-8').splitlines()
    if len(lines) != manifest['row_count']:
        raise ValueError('Manifest row_count mismatch')
    counts = dict(raw_rows=len(lines), accepted_rows=0, rejected_rows=0, duplicate_rows=0, corrected_rows=0, late_rows=0)
    # The batch record, facts and quarantine are one transaction; crash rolls all back.
    with con:
        for number, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
                reason = validate(row)
            except json.JSONDecodeError:
                reason = 'invalid_json'
                row = None
            if reason:
                con.execute('INSERT INTO quarantine VALUES (?,?,?,?)', (batch_id, number, reason, line))
                counts['rejected_rows'] += 1
            else:
                existing = con.execute('SELECT * FROM trips WHERE trip_id=?', (row['trip_id'],)).fetchone()
                if existing and row['updated_at'] == existing['updated_at']:
                    # Conflicting same-version events must never silently overwrite facts.
                    if any(row[k] != existing[k] for k in FIELDS - {'received_at'}):
                        con.execute('INSERT INTO quarantine VALUES (?,?,?,?)', (batch_id, number, 'conflicting_version', line))
                        counts['rejected_rows'] += 1
                        continue
                if existing and row['updated_at'] <= existing['updated_at']:
                    counts['duplicate_rows'] += 1
                else:
                    lag = (timestamp(row['received_at']) - timestamp(row['dropoff_at'])).total_seconds() / 3600
                    values = [row[k] for k in ['trip_id', 'pickup_at', 'dropoff_at', 'pickup_zone', 'dropoff_zone', 'distance_miles', 'fare_usd', 'updated_at', 'received_at']]
                    con.execute('''INSERT INTO trips VALUES (?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(trip_id) DO UPDATE SET pickup_at=excluded.pickup_at,
                     dropoff_at=excluded.dropoff_at, pickup_zone=excluded.pickup_zone,
                     dropoff_zone=excluded.dropoff_zone, distance_miles=excluded.distance_miles,
                     fare_usd=excluded.fare_usd, updated_at=excluded.updated_at,
                     received_at=excluded.received_at, arrival_lag_hours=excluded.arrival_lag_hours,
                     source_batch=excluded.source_batch''', values + [lag, batch_id])
                    counts['accepted_rows'] += 1
                    counts['corrected_rows'] += int(existing is not None)
                    counts['late_rows'] += int(lag > 24)
            if fail_after and number == fail_after:
                raise RuntimeError('Injected worker failure')
        con.execute('INSERT INTO batches VALUES (?,?,?,?,?,?,?,?,?)', [batch_id, checksum] + [counts[k] for k in ['raw_rows', 'accepted_rows', 'rejected_rows', 'duplicate_rows', 'corrected_rows', 'late_rows']] + [manifest['received_at']])
    return dict(batch_id=batch_id, status='committed', **counts)


def rows(con, query):
    return [dict(r) for r in con.execute(query)]


def export(con, path):
    con.executescript((ROOT / 'sql/marts.sql').read_text())
    summary = dict(con.execute('SELECT * FROM mart_summary').fetchone())
    lags = [r[0] for r in con.execute('SELECT arrival_lag_hours FROM trips ORDER BY arrival_lag_hours')]
    summary['arrival_lag_p95_hours'] = round(lags[max(0, __import__('math').ceil(len(lags) * .95) - 1)], 3) if lags else None
    zones = rows(con, 'SELECT * FROM mart_zone ORDER BY fare_usd DESC')
    for zone in zones:
        zone['zone'] = ZONES[zone['pickup_zone']]
    checks = [
        {'name': 'Unique trip keys', 'passed': con.execute('SELECT COUNT(*)=COUNT(DISTINCT trip_id) FROM trips').fetchone()[0] == 1},
        {'name': 'Input rows accounted for', 'passed': con.execute('SELECT COALESCE(SUM(raw_rows),0)=COALESCE(SUM(accepted_rows+rejected_rows+duplicate_rows),0) FROM batches').fetchone()[0] == 1},
        {'name': 'Valid fare and distance', 'passed': con.execute('SELECT COUNT(*) FROM trips WHERE fare_usd<=0 OR distance_miles<=0').fetchone()[0] == 0},
        {'name': 'Zone mart reconciles', 'passed': abs(sum(z['fare_usd'] for z in zones) - (summary['fare_usd'] or 0)) < .05},
    ]
    data = {
        'project': 'Mobility Data Reliability',
        'data_kind': 'synthetic',
        'disclosure': 'Deterministic synthetic NYC taxi-shaped data. Not real TLC trip records. Demo zone IDs are local codes, not TLC LocationIDs.',
        'currency': 'USD', 'schema_version': 1,
        'period': {'start': summary['period_start'], 'end': summary['period_end']},
        'summary': summary,
        'daily': rows(con, 'SELECT * FROM mart_daily ORDER BY date'),
        'zones': zones,
        'hourly': rows(con, 'SELECT * FROM mart_hourly ORDER BY hour'),
        'batches': rows(con, 'SELECT * FROM batches ORDER BY received_at, batch_id'),
        'quarantine': rows(con, 'SELECT reason, COUNT(*) AS rows FROM quarantine GROUP BY reason ORDER BY rows DESC'),
        'quality_checks': checks,
        'decision': 'Investigate rejected records before replay; keep valid trips available. Reprocess affected event dates after late arrivals and corrections. These are demo operating policies, not fleet recommendations.',
        'metric_notes': {'fare_usd': 'Sum of positive fare only, excluding tips, tolls and tax; not company revenue.', 'late_trip_rate': 'Current canonical trips whose received_at is over 24 hours after dropoff_at.', 'quarantine_rate': 'Rejected input rows / raw input rows; duplicate rows remain in the denominator.', 'arrival_lag_p95_hours': 'Nearest-rank p95 over canonical trips; synthetic event time, not measured runtime latency.'}
    }
    if not all(check['passed'] for check in checks):
        raise ValueError('Publication blocked: data quality checks failed')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, suffix='.tmp') as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write('\n')
        temporary = handle.name
    os.replace(temporary, path)
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    parser.add_argument('--db', type=Path, default=ROOT / 'data/warehouse.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'dashboard/data.json')
    parser.add_argument('--batch', help='Optional manifest basename, to replay a specific batch')
    args = parser.parse_args()
    con = connect(args.db)
    manifests = [args.raw_dir / args.batch] if args.batch else sorted(args.raw_dir.glob('*.manifest.json'))
    if not manifests:
        raise SystemExit('No manifests found. Run python3 src/generate_demo.py first.')
    for manifest in manifests:
        print(json.dumps(ingest(con, manifest), sort_keys=True))
    data = export(con, args.output)
    if not all(c['passed'] for c in data['quality_checks']):
        raise SystemExit('Publication checks failed')
    print(json.dumps(data['summary'], sort_keys=True))
    con.close()


if __name__ == '__main__':
    main()
