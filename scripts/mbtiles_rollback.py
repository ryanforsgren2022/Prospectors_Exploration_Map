#!/usr/bin/env python3
"""Check rollback read-only by default; preserve every archive/alias on rollback."""
import argparse
import json
import sqlite3
from pathlib import Path
from mbtiles_migration import Blocked, rollback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approved-deployment', action='store_true')
    parser.add_argument('--dependencies-reviewed', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(rollback(args.receipt, args.apply, args.approved_deployment, args.dependencies_reviewed), indent=2))
        return 0
    except (Blocked, OSError, ValueError, KeyError, sqlite3.Error) as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
