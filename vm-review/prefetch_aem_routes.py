"""Prefetch verified routing extracts while the graph importer is busy.

This only writes to the isolated routing staging directory. The importer
rechecks each extract's size and checksum before it uses it.
"""
import argparse
import json
import os
from pathlib import Path

from aem_route_config import STATE_NAMES
from build_aem_routes import download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--staging', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.manifest.read_text())
    if report.get('status') != 'verified':
        raise RuntimeError('Routing source manifest is not verified')
    items = {item['state']: item for item in report['extracts']}
    if set(items) != set(STATE_NAMES.values()):
        raise RuntimeError('Manifest must cover every supported state exactly once')
    holding = args.staging / 'prefetch'
    holding.mkdir(parents=True, exist_ok=True)
    for code, state in STATE_NAMES.items():
        if code in {'az', 'ca'}:
            continue
        item = items[state]
        destination = args.staging / item['filename']
        if destination.exists():
            print(state, 'already staged', flush=True)
            continue
        cached = download(item, holding)
        # Linking is atomic and cannot overwrite a file placed by the importer.
        # A simultaneous importer download remains valid but may be redundant.
        try:
            os.link(cached, destination)
            print(state, 'verified and staged', cached.stat().st_size, flush=True)
        except FileExistsError:
            print(state, 'already staged by importer', flush=True)
        cached.unlink()
    print('PREFETCH COMPLETE', flush=True)


if __name__ == '__main__':
    main()
