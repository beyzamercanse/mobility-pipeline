"""Optional real reference download. Does not ingest official TLC trip Parquet."""
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

URL = 'https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv'
ROOT = Path(__file__).resolve().parents[1]


def main():
    with urlopen(URL, timeout=60) as response:
        raw = response.read()
    decoded = raw.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(decoded))
    if reader.fieldnames != ['LocationID', 'Borough', 'Zone', 'service_zone']:
        raise ValueError('Unexpected official zone lookup schema')
    records = list(reader)
    folder = ROOT / 'data/reference'
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    path = folder / ('taxi_zones_' + digest[:12] + '.csv')
    if not path.exists():
        path.write_bytes(raw)
    metadata = {'source_url': URL, 'sha256': digest, 'rows': len(records), 'file': path.name,
                'note': 'Official lookup only. Not joined to synthetic demo IDs.'}
    (folder / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
