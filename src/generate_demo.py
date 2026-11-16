"""Deterministic fixture with late events, duplicate delivery and corrections."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]


def stamp(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def write_batch(folder, batch_id, records, received_at):
    folder.mkdir(parents=True, exist_ok=True)
    raw = ''.join(json.dumps(r, sort_keys=True) + '\n' for r in records).encode()
    raw_path = folder / (batch_id + '.jsonl')
    if raw_path.exists() and raw_path.read_bytes() != raw:
        raise ValueError('Refusing to overwrite immutable raw file: ' + str(raw_path))
    raw_path.write_bytes(raw)
    manifest = {'batch_id': batch_id, 'schema_version': 1, 'file': raw_path.name,
                'sha256': hashlib.sha256(raw).hexdigest(), 'row_count': len(records), 'received_at': received_at,
                'source': 'deterministic synthetic fixture; seed 4026'}
    manifest_path = folder / (batch_id + '.manifest.json')
    text = json.dumps(manifest, indent=2) + '\n'
    if manifest_path.exists() and manifest_path.read_text() != text:
        raise ValueError('Refusing to overwrite immutable manifest')
    manifest_path.write_text(text)
    return manifest_path


def generate(folder):
    rng = random.Random(4026)
    base = datetime(2026, 1, 1)
    early, delayed, corrections = [], [], []
    for i in range(7200):
        pickup = base + timedelta(days=i % 14, hours=rng.choices(range(24), weights=[1]*7+[3]*10+[5]*6+[2])[0], minutes=rng.randrange(60))
        zone = rng.choices(range(1, 9), weights=[10, 25, 10, 12, 10, 8, 15, 10])[0]
        distance = round(rng.uniform(7, 22) if zone in (1, 6) else rng.uniform(.5, 7), 2)
        dropoff = pickup + timedelta(minutes=int(distance * rng.uniform(2.5, 4.5)) + 5)
        received = dropoff + timedelta(hours=rng.uniform(.1, 2))
        row = dict(trip_id='T%06d' % i, pickup_at=stamp(pickup), dropoff_at=stamp(dropoff),
                   pickup_zone=zone, dropoff_zone=rng.randrange(1, 9), distance_miles=distance,
                   fare_usd=round(3 + distance * 3.1 + rng.uniform(0, 6), 2),
                   updated_at=stamp(dropoff), received_at=stamp(received))
        if i % 19 == 0:
            row['received_at'] = stamp(dropoff + timedelta(hours=36 + i % 48))
            delayed.append(row)
        else:
            early.append(row)
        if i % 71 == 0:
            corrected = dict(row)
            corrected['fare_usd'] = round(row['fare_usd'] + 2.5, 2)
            corrected['updated_at'] = stamp(dropoff + timedelta(hours=96))
            corrected['received_at'] = stamp(dropoff + timedelta(hours=97))
            corrections.append(corrected)
    duplicates = [dict(early[i]) for i in range(0, len(early), 23)]
    bad = []
    for i in range(80):
        row = dict(early[i])
        row['trip_id'] = 'BAD%05d' % i
        if i % 4 == 0:
            row['fare_usd'] = -5
        elif i % 4 == 1:
            row['pickup_zone'] = 999
        elif i % 4 == 2:
            del row['distance_miles']
        else:
            row['dropoff_at'] = row['pickup_at']
        bad.append(row)
    write_batch(folder, '01-primary', early + duplicates + bad, '2026-01-15T12:00:00Z')
    write_batch(folder, '02-late-arrivals', delayed, '2026-01-18T12:00:00Z')
    write_batch(folder, '03-corrections', corrections, '2026-01-19T12:00:00Z')
    return {'canonical_trips': 7200, 'corrections': len(corrections), 'duplicates': len(duplicates), 'bad': len(bad)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw-dir', type=Path, default=ROOT / 'data/raw')
    args = parser.parse_args()
    print(json.dumps(generate(args.raw_dir), sort_keys=True))
