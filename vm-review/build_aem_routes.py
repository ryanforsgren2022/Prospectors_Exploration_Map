"""Resumable, sequential routing graph build from verified OSM extracts.

This creates a new derived graph. Existing search indexes and parcel archives
are opened read-only by the runtime and are never rebuilt by this command.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path

from aem_route_graph import import_extract, initialize
from aem_route_config import STATE_NAMES

MIN_FREE_BYTES = 8 * 1024 ** 3


def download(item, staging):
    url = urllib.parse.urlsplit(item['url'])
    if url.scheme != 'https' or url.netloc != 'download.geofabrik.de' or \
            Path(url.path).name != item['filename']:
        raise RuntimeError('Routing extract URL is not an approved Geofabrik release')
    destination = staging / item['filename']
    expected_size = int(item['bytes'])
    expected_md5 = item['md5'].lower()
    if destination.exists():
        if destination.stat().st_size == expected_size and digest(destination) == expected_md5:
            return destination
        raise RuntimeError(f'Existing extract has wrong identity: {destination}')
    temporary = destination.with_suffix(destination.suffix + '.part')
    if temporary.exists():
        temporary.unlink()
    if shutil.disk_usage(staging).free < expected_size + MIN_FREE_BYTES:
        raise RuntimeError('Insufficient space for routing extract and reserve')
    request = urllib.request.Request(item['url'], headers={'User-Agent': 'AEM-route-graph/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as output:
            while chunk := response.read(8 * 1024 ** 2):
                output.write(chunk)
        if temporary.stat().st_size != expected_size or digest(temporary) != expected_md5:
            raise RuntimeError(f'Extract checksum failed: {item["state"]}')
        temporary.rename(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    value = hashlib.md5(usedforsecurity=False)
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 ** 2), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--staging', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.manifest.read_text())
    if report.get('status') != 'verified':
        raise RuntimeError('Routing source manifest is not verified')
    items = {item['state']: item for item in report['extracts']}
    if set(items) != set(STATE_NAMES.values()):
        raise RuntimeError('Manifest must cover every supported state exactly once')
    args.graph.parent.mkdir(parents=True, exist_ok=True)
    args.staging.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.graph) as db:
        initialize(db)
        db.execute('''CREATE TABLE IF NOT EXISTS route_sources(
            state TEXT PRIMARY KEY, md5 TEXT NOT NULL, imported_at INTEGER NOT NULL,
            routable_ways INTEGER NOT NULL)''')
        for code, state in STATE_NAMES.items():
            item = items[state]
            existing = db.execute('SELECT md5 FROM route_sources WHERE state=?', (code,)).fetchone()
            if existing:
                if existing[0] != item['md5']:
                    raise RuntimeError(f'{state}: graph source differs from manifest; build a new graph')
                print(state, 'already imported', flush=True)
                continue
            extract = download(item, args.staging)
            print(state, 'verified extract', extract.stat().st_size, flush=True)
            count = import_extract(db, extract)
            with db:
                db.execute('INSERT INTO route_sources VALUES(?,?,?,?)',
                           (code, item['md5'], int(time.time()), count))
            print(state, count, 'routable ways imported', flush=True)
            extract.unlink()
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    print('ALL ROUTING SOURCES IMPORTED', flush=True)


if __name__ == '__main__':
    main()
