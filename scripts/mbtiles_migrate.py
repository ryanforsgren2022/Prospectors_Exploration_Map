#!/usr/bin/env python3
"""Check the plan read-only by default. --apply requires prior explicit approval."""
import argparse
import json
import sqlite3
from pathlib import Path
from mbtiles_migration import Blocked, apply, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1]/'docs/mbtiles-path-manifest.json')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approved-deployment', action='store_true')
    parser.add_argument('--dependencies-reviewed', action='store_true')
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        root = args.root or Path(manifest['configuredRoot'])
        if args.apply:
            if not args.receipt:
                raise Blocked('--receipt outside production data is required for rollback')
            result = apply(manifest, root, args.receipt, args.approved_deployment, args.dependencies_reviewed)
            result = {'status': result['status'], 'receipt': str(args.receipt), 'filesDeleted': 0}
        else:
            resolved, hashes = preflight(manifest, root)
            result = {'status': 'check-passed', 'resolvedRoot': str(resolved), 'sha256': hashes,
                      'operations': len(hashes), 'productionModified': False}
        print(json.dumps(result, indent=2))
        return 0
    except (Blocked, OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
