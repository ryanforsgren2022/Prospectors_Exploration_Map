"""Compare the two audited Montana archives read-only: IDENTICAL, DIFFERENT or BLOCKED."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

NAMES = ('montana-claims-active.mbtiles', 'mt-claims.mbtiles')


def inspect(path):
    result = {'path': str(path), 'errors': []}
    try:
        path = path.resolve(strict=True)
        result['resolvedPath'] = str(path)
        before = path.stat()
        result['fileIdentity'] = f'{before.st_dev}:{before.st_ino}'
        wal = path.with_name(path.name + '-wal')
        if wal.exists() and wal.stat().st_size:
            raise ValueError('Nonempty WAL present; finished immutable snapshot required')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(block)
        result['sha256'] = digest.hexdigest()
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('BEGIN')
            result['integrity'] = [row[0] for row in db.execute('PRAGMA integrity_check')]
            result['metadata'] = dict(db.execute('SELECT name,value FROM metadata ORDER BY name'))
            vector = json.loads(result['metadata'].get('json', '{}')).get('vector_layers', [])
            result['sourceLayers'] = [v['id'] for v in vector]
            result['tileCounts'] = [list(row) for row in db.execute(
                'SELECT zoom_level,count(*),sum(length(tile_data)>0) FROM tiles GROUP BY zoom_level ORDER BY zoom_level')]
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Archive changed during verification')
        if result['integrity'] != ['ok'] or result['sourceLayers'] != ['claims'] or not result['tileCounts']:
            raise ValueError('Archive failed integrity, source-layer or nonempty tile validation')
    except (OSError, sqlite3.Error, ValueError, KeyError) as error:
        result['errors'].append(str(error))
    return result


def compare(root):
    configured_root = str(root)
    root_error = None
    try:
        root = Path(root).resolve(strict=True)
    except OSError as error:
        root_error = str(error)
        root = Path(root)
    records = [inspect(root / 'mt/claims' / name) for name in NAMES]
    report = {'status': 'BLOCKED', 'configuredDataRoot': configured_root,
              'resolvedDataRoot': None if root_error else str(root),
              'rootResolutionError': root_error, 'archives': records}
    if not root_error and all(not record['errors'] for record in records):
        a, b = records
        report['sameSha256'] = a['sha256'] == b['sha256']
        report['sameMetadata'] = a['metadata'] == b['metadata']
        report['sameTileCounts'] = a['tileCounts'] == b['tileCounts']
        report['sameSourceLayers'] = a['sourceLayers'] == b['sourceLayers']
        report['status'] = 'IDENTICAL' if all(report[k] for k in (
            'sameSha256', 'sameMetadata', 'sameTileCounts', 'sameSourceLayers')) else 'DIFFERENT'
    # Metadata is compared in full; print only its hash to keep the report readable.
    for record in records:
        metadata = record.pop('metadata', None)
        if metadata is not None:
            record['metadataSha256'] = hashlib.sha256(
                json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    report['canonicalArchiveSelected'] = False
    report['dataModified'] = False
    return report



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/root/arizona-naip-build/live-mvt/data')
    args = parser.parse_args()
    result = compare(args.root)
    print(json.dumps(result, indent=2))
    raise SystemExit({'IDENTICAL': 0, 'DIFFERENT': 1, 'BLOCKED': 2}[result['status']])
