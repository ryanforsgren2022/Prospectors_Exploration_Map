"""Remove VM PLSS/withdrawal files unused by the active data registry.

Run on the VM from the live-mvt directory. Default mode only prints an audit.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from aem_vm_discovery_v2 import DATA, ROAD_STATES, discover_vm_data

PRODUCER = Path('/root/arizona-naip-build/prospectors-west')
BUILD_ROOTS = tuple(PRODUCER / name for name in (
    'plss-state-full-v1', 'withdrawals-state-full-v1', 'withdrawals-west-v1'
))
DATA_SUFFIXES = frozenset({
    '.mbtiles', '.pmtiles', '.geojsonl', '.geojson', '.esrijson',
    '.gdbtable', '.gdbtablx', '.gdbindexes', '.gdb', '.sqlite',
    '.db', '.zip', '.gz', '.spx', '.shp', '.shx', '.dbf', '.prj',
    '.fgb', '.gpkg', '.pbf', '.parquet', '.csv', '.tsv', '.log',
})

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()

_, registry = discover_vm_data()
protected = {entry['path'].absolute() for entry in registry.values()}
live_roots = tuple(DATA / state / group for state in ROAD_STATES for group in ('plss', 'withdrawals'))
candidates = []
for root in (*live_roots, *BUILD_ROOTS):
    if not root.is_dir() or root.is_symlink():
        continue
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink() or path.absolute() in protected:
            continue
        if root in BUILD_ROOTS and path.suffix.lower() not in DATA_SUFFIXES:
            continue
        # The package directory also contains unrelated Nevada datasets.
        if root in live_roots and 'packages' in path.relative_to(root).parts:
            continue
        candidates.append(path)

counts = Counter()
bytes_by_root = Counter()
for path in candidates:
    size = path.stat().st_size
    counts[path.suffix.lower()] += 1
    category = 'producer' if any(path.is_relative_to(root) for root in BUILD_ROOTS) else 'live-unused'
    bytes_by_root[category] += size
print('registered paths protected:', len(protected))
print('candidate files:', len(candidates))
print('candidate bytes:', sum(bytes_by_root.values()))
print('bytes by category:', dict(bytes_by_root))
print('top suffixes:', counts.most_common(15))
for path in sorted(candidates, key=lambda item: item.stat().st_size, reverse=True)[:25]:
    print(path.stat().st_size, path)

if args.apply:
    # Check the live registry again immediately before unlinking any file.
    _, current = discover_vm_data()
    current_paths = {entry['path'].absolute() for entry in current.values()}
    if current_paths != protected:
        raise SystemExit('Live registry changed during audit; no files deleted')
    report = Path('/root/LIVE_SITE_CASHE/plss-withdrawals-cleanup-manifest.json')
    if report.exists():
        raise SystemExit(f'Cleanup manifest already exists: {report}')
    report.write_text(json.dumps({
        'protected': sorted(map(str, protected)),
        'deleted': [{'path': str(path), 'bytes': path.stat().st_size} for path in candidates],
    }, indent=2) + '\n')
    for path in candidates:
        if path.absolute() in protected or path.is_symlink() or not path.is_file():
            raise SystemExit(f'Candidate changed; stopped before removing {path}')
        path.unlink()
    print('deleted files:', len(candidates))
