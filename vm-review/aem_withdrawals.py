"""Canonical read-only withdrawal tiles for every installed state."""
from contextlib import closing
from pathlib import Path
import sqlite3
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parent / 'data'
STATES = frozenset('az ca co id mt nm nv or ut wa wy'.split())
LAYERS = ('withdrawals_authorized', 'withdrawals_pending')
router = APIRouter()

def tile_response(path, z, x, y):
    if not 4 <= z <= 16 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(404, 'Outside withdrawals tile coverage')
    if not path.is_file():
        raise HTTPException(404, 'Withdrawals dataset is not installed')
    try:
        with closing(sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True, timeout=5)) as db:
            row = db.execute('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?', (z, x, 2**z - 1 - y)).fetchone()
    except sqlite3.Error as error:
        raise HTTPException(503, 'Withdrawals archive unavailable') from error
    headers = {'Cache-Control': 'public, max-age=600'}
    if row is None:
        return Response(status_code=204, headers=headers)
    data = row[0]
    if data[:2] == b'\x1f\x8b':
        headers['Content-Encoding'] = 'gzip'
    return Response(data, media_type='application/vnd.mapbox-vector-tile', headers=headers)

def state_tile_response(state, z, x, y):
    if state not in STATES:
        raise HTTPException(404, 'Unknown withdrawals state')
    return tile_response(ROOT / state / 'withdrawals' / 'tiles' / (state + '-withdrawals.mbtiles'), z, x, y)

# Old clients keep working through the same reader, without upstream generation.
@router.get('/az/withdrawals/{kind}/{z}/{x}/{y}.pbf', include_in_schema=False)
def legacy_arizona_withdrawals(kind: str, z: int, x: int, y: int):
    if kind not in ('authorized', 'pending'):
        raise HTTPException(404)
    return state_tile_response('az', z, x, y)

@router.get('/{state}/withdrawals/{z}/{x}/{y}.pbf')
def withdrawals_tile(state: str, z: int, x: int, y: int):
    return state_tile_response(state, z, x, y)

