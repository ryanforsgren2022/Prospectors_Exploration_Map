"""Read-only classification counts from actual audited MBTiles; stdout JSON only.
Counts are tile-feature occurrences (features can repeat across tiles/zooms), not
deduplicated legal claims. Missing/null/blank/invalid classes remain separate.
"""
import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import zlib

from aem_claims_classification import filter_claim_tile

STATES = 'az ca co id mt nm nv or ut wa wy'.split()


def scan(record):
    path = Path(record['real_path'])
    result = {'path': str(path), 'status': 'BLOCKED', 'sourceLayers': record['source_layers'],
              'before': None, 'after': None, 'closed': None, 'unknown': None,
              'byClassification': None, 'afterByClassification': None, 'unknownReasons': None}
    try:
        path = path.resolve(strict=True)
        before = path.stat()
        if path.with_name(path.name + '-wal').exists():
            raise ValueError('WAL present: a stable finished snapshot is required')
        totals = Counter()
        classes, reasons = Counter(), Counter()
        samples = []
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('BEGIN')
            for z, x, tms_y, payload in db.execute(
                    'SELECT zoom_level,tile_column,tile_row,tile_data FROM tiles'):
                for layer in record['source_layers']:
                    if 'claim' not in layer.casefold():
                        continue
                    _, counts = filter_claim_tile(payload, layer, 'CSE_DISP')
                    if not counts['sourceLayerFound']:
                        continue
                    totals.update({key: counts[key] for key in ['before', 'after', 'closed', 'unknown']})
                    classes.update(counts['byClassification'])
                    reasons.update(counts['unknownReasons'])
                    for sample in counts['unknownFeatureIds']:
                        if len(samples) < 20:
                            samples.append({'z': z, 'x': x, 'y': (1 << z) - 1 - tms_y, **sample})
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('Archive changed during counting')
        if not totals['before']:
            raise ValueError('No claim features found; cannot establish archive classification counts')
        assert totals['before'] == totals['after'] + totals['closed'] + totals['unknown']
        result.update(dict(totals))
        result.update({'status': 'PASS', 'byClassification': dict(sorted(classes.items())),
                       'afterByClassification': {key: count for key, count in sorted(classes.items()) if key != 'closed'},
                       'unknownReasons': dict(sorted(reasons.items())), 'unknownSamples': samples})
    except (OSError, sqlite3.Error, ValueError, UnicodeError, EOFError, struct.error, zlib.error) as error:
        result['blocker'] = str(error)
    return result


def audit_counts(audit, registry=None):
    root = Path(audit['canonical_data_root'])
    states = {code: {'status': 'BLOCKED', 'archives': []} for code in STATES}
    seen = set()
    historical_duplicates = []
    for record in audit['archives']:
        path = Path(record['real_path'])
        if not path.is_relative_to(root) or not any('claim' in layer.casefold() for layer in record['source_layers']):
            continue
        identity = record.get('file_identity', record['real_path'])
        if identity in seen:
            continue
        seen.add(identity)
        code = path.relative_to(root).parts[0]
        if code not in states:
            continue
        canonical = ((registry or {}).get('states', {}).get(code, {}).get('datasets', {}).get('claims') or {}).get('path')
        if code == 'mt' and canonical and path.relative_to(root).as_posix() != canonical:
            historical_duplicates.append(record['real_path'])
            continue
        result = scan(record)
        result['coverage'] = 'BLM lands only' if code == 'id' else 'State archive; completeness requires source reconciliation'
        states[code]['archives'].append(result)
    for code, state in states.items():
        if not state['archives']:
            state['blocker'] = 'No source claims MBTiles identified for this state in the supplied audit'
        elif len(state['archives']) > 1:
            state['blocker'] = 'Competing archives reported separately; never summed as statewide totals'
        elif state['archives'][0]['status'] == 'PASS':
            state['status'] = 'PASS'
    return {'countUnit': 'tile-feature occurrences across stored tiles and zooms; not distinct legal claims',
            'classificationField': 'CSE_DISP', 'normalization': 'Unicode whitespace collapse + casefold',
            'rule': 'all named classifications except Closed',
            'unknownPolicy': 'count separately; omit from the classified non-closed layer',
            'states': states, 'excludedHistoricalDuplicates': historical_duplicates, 'sourceDataModified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--registry', type=Path, default=Path(__file__).with_name('western-datasets.json'))
    args = parser.parse_args()
    print(json.dumps(audit_counts(json.loads(args.audit.read_text()), json.loads(args.registry.read_text())), indent=2))
