#!/usr/bin/env python3
"""Read-only VM verification for the prepared Western dataset backend."""
import argparse
from contextlib import closing
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import types


def load_service(directory):
    sys.path.insert(0, str(directory))
    try:
        import fastapi  # noqa: F401
    except ImportError:
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None):
                self.status_code, self.detail = status_code, detail

        class Response:
            def __init__(self, content=b'', status_code=200, headers=None, media_type=None):
                self.body = content.encode() if isinstance(content, str) else content
                self.status_code, self.headers = status_code, headers or {}

        sys.modules['fastapi'] = types.SimpleNamespace(
            HTTPException=HTTPException, Response=Response, Request=object
        )
        sys.modules['starlette.responses'] = types.SimpleNamespace(StreamingResponse=Response)
    spec = importlib.util.spec_from_file_location(
        'aem_vm_discovery_v2_verify', directory / 'aem_vm_discovery_v2.py'
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discovered_entry(state, group):
    datasets = state['datasets']
    if group.startswith('withdrawals'):
        return datasets['withdrawals'][group.removeprefix('withdrawals').lower()]
    return datasets[group]


def tile_layers(payload, fields):
    data = gzip.decompress(payload) if payload[:2] == b'\x1f\x8b' else payload
    names = set()
    for number, wire, layer, _ in fields(data):
        if number != 3 or wire != 2:
            continue
        name = next((value.decode('utf-8') for key, kind, value, _ in fields(layer)
                     if key == 1 and kind == 2), None)
        if name:
            names.add(name)
    return names


def representative_xyz(path, minimum, maximum, source_layer, fields):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        rows = db.execute(
            'SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles '
            'WHERE zoom_level BETWEEN ? AND ? AND length(tile_data)>0 LIMIT 5000',
            (minimum, maximum)
        )
        for z, x, tms_y, payload in rows:
            if source_layer in tile_layers(payload, fields):
                return z, x, (1 << z) - 1 - tms_y
    raise ValueError(f'No {source_layer!r} tile found in first 5000 nonempty registered-range tiles')


def verify(root, registry_path):
    root = root.resolve(strict=True)
    registry = json.loads(registry_path.read_text())
    service = load_service(registry_path.parent)
    from aem_claims_classification import fields as protobuf_fields
    service.DATA = root
    service.REGISTRY = registry_path.resolve()
    service.CACHE_DATA = None
    states, paths = service.discover_vm_data()
    expected = sum(len(state['datasets']) for state in registry['states'].values())
    results = []
    for code, state in registry['states'].items():
        if code not in states:
            raise ValueError(f'{code}: state missing from discovery')
        for group, spec in state['datasets'].items():
            entry = discovered_entry(states[code], group)
            if entry['sourceLayer'] != spec['sourceLayer']:
                raise ValueError(f'{code}/{group}: source-layer mismatch')
            archive = paths.get((code, group))
            if not archive:
                raise ValueError(f'{code}/{group}: archive not registered')
            z, x, y = representative_xyz(
                archive['path'], spec['minzoom'], spec['maxzoom'],
                spec['sourceLayer'], protobuf_fields
            )
            response = service.registered_mbtiles_tile(code, group, z, x, y)
            if response.status_code not in (200, 204):
                raise ValueError(f'{code}/{group}: representative request returned {response.status_code}')
            results.append({
                'state': code, 'group': group, 'sourceLayer': spec['sourceLayer'],
                'archive': str(archive['path']), 'tile': [z, x, y],
                'statusCode': response.status_code
            })
    if len(results) != expected or len(paths) != expected:
        raise ValueError(f'Expected {expected} registrations; discovered {len(paths)}')

    # Explicit conflict/scope assertions from the remediation decision.
    for group in ('plssGovernmentLots', 'plssQuarterQuarterSections'):
        selected = paths[('wa', group)]['path']
        reviewed = root / registry['states']['wa']['datasets'][group]['path']
        if not selected.samefile(reviewed):
            raise ValueError(f'wa/{group}: selected archive is not the statewide reviewed source')
    if 'claims' in states['id']['datasets'] or 'claimsBlmLands' not in states['id']['datasets']:
        raise ValueError('Idaho BLM-only claims scope was not preserved')
    if not paths[('az', 'plssTownships')]['path'].samefile(
            root / registry['states']['az']['datasets']['plssTownships']['path']):
        raise ValueError('Arizona dedicated township archive was not selected')
    if paths[('mt', 'claims')]['path'].name == 'montana-claims-active.mbtiles':
        raise ValueError('Montana historical duplicate is still registered')

    return {
        'status': 'PASS', 'resolvedDataRoot': str(root),
        'states': len(states), 'registrations': len(results),
        'representativeRequests': len(results), 'results': results,
        'writesPerformed': False
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path,
                        default=Path('/root/arizona-naip-build/live-mvt/data'))
    parser.add_argument('--registry', type=Path,
                        default=Path(__file__).with_name('western-datasets.json'))
    args = parser.parse_args()
    try:
        result = verify(args.data_root, args.registry.resolve(strict=True))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, sqlite3.Error) as error:
        print(json.dumps({'status': 'BLOCKED', 'error': str(error), 'writesPerformed': False}, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
