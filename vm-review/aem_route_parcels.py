"""Read-only, exact corridor checks against the published parcel tiles.

The search indexes contain bounding boxes only. Tile geometry is checked after
the route has been displayed, and incomplete archive coverage is reported.
"""
import gzip
import json
import math
import sqlite3
import sys
from contextlib import contextmanager

import mapbox_vector_tile
from pyproj import CRS, Transformer
from shapely.geometry import LineString, box, shape
from shapely.ops import transform
from aem_route_config import STATES, parcel_archive

ZOOM = 16
MILE = 1609.344
MAX_TILES = 10000


def _tile_xy(lng, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 1 << ZOOM
    x = int((lng + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _corridor_tiles(coordinates, radius_miles):
    """Cover a route's tile-space path without scanning its whole bounding box."""
    n = 1 << ZOOM

    def fractional(lng, lat):
        lat = max(-85.05112878, min(85.05112878, lat))
        return ((lng + 180) / 360 * n,
                (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    tiles = set()
    for start, end in zip(coordinates, coordinates[1:]):
        ax, ay = fractional(*start)
        bx, by = fractional(*end)
        steps = max(1, math.ceil(max(abs(bx - ax), abs(by - ay)) * 2))
        for step in range(steps + 1):
            ratio = step / steps
            x = math.floor(ax + (bx - ax) * ratio)
            y = math.floor(ay + (by - ay) * ratio)
            latitude = start[1] + (end[1] - start[1]) * ratio
            tile_meters = 40075016.686 * math.cos(math.radians(latitude)) / n
            padding = math.ceil(radius_miles * MILE / tile_meters) + 1
            for dx in range(-padding, padding + 1):
                for dy in range(-padding, padding + 1):
                    tx, ty = x + dx, y + dy
                    if 0 <= tx < n and 0 <= ty < n:
                        tiles.add((tx, ty))
            if len(tiles) > MAX_TILES:
                raise ValueError('Route corridor exceeds one parcel query; split the trip')
    return tiles


def _to_geojson_geometry(tile_geometry, x, y, extent):
    n = 1 << ZOOM

    def project(px, py, z=None):
        lng = (x + px / extent) / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + py / extent) / n))))
        return lng, lat

    return transform(project, shape(tile_geometry))


def _read_bounds(path):
    if path.suffix == '.mbtiles':
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            value = db.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()
        if value:
            return tuple(map(float, value[0].split(',')))
    else:
        try:
            from pmtiles.reader import Reader, MmapSource
        except ImportError:
            sys.path.append('/usr/local/lib/python3.12/dist-packages')
            from pmtiles.reader import Reader, MmapSource
        with path.open('rb') as stream:
            reader = Reader(MmapSource(stream))
            value = reader.metadata().get('bounds')
            header = reader.header()
        if value:
            return tuple(map(float, value.split(','))) if isinstance(value, str) else tuple(value)
        return tuple(header[key] / 1e7 for key in
                     ('min_lon_e7', 'min_lat_e7', 'max_lon_e7', 'max_lat_e7'))
    return None


@contextmanager
def _tile_reader(path):
    if path.suffix == '.mbtiles':
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            def get(x, y):
                row = db.execute(
                    'SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
                    (ZOOM, x, (1 << ZOOM) - 1 - y),
                ).fetchone()
                return row[0] if row else None
            yield get
        return
    try:
        from pmtiles.reader import Reader, MmapSource
    except ImportError:
        sys.path.append('/usr/local/lib/python3.12/dist-packages')
        from pmtiles.reader import Reader, MmapSource
    with path.open('rb') as stream:
        reader = Reader(MmapSource(stream))
        yield lambda x, y: reader.get(ZOOM, x, y)


def _tile_bounds(x, y):
    n = 1 << ZOOM
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return box(west, south, east, north)


def _archive(state):
    return parcel_archive(state)


def _archive_coverage(state):
    manifest = _archive(state).with_suffix('.manifest.json')
    if not manifest.exists():
        return 'unknown'
    details = json.loads(manifest.read_text())
    return 'complete' if details.get('status') == 'verified' and not details.get('missing_tile_records') else 'incomplete'


def parcel_corridor(coordinates, radius_miles=0.5):
    """Return intersecting parcels and an explicit coverage status.

    No PLSS source or visible layer state is read or changed here.
    """
    if not 2 <= len(coordinates) <= 100000 or radius_miles != 0.5:
        raise ValueError('Parcel checks require a route and the fixed 0.5 mile radius')
    if any(len(point) < 2 or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90
           for point in coordinates):
        raise ValueError('Invalid route coordinates')
    route = LineString(coordinates)
    mid = route.interpolate(0.5, normalized=True)
    metric = CRS.from_proj4(f'+proj=aeqd +lat_0={mid.y} +lon_0={mid.x} +datum=WGS84 +units=m')
    forward = Transformer.from_crs('EPSG:4326', metric, always_xy=True).transform
    reverse = Transformer.from_crs(metric, 'EPSG:4326', always_xy=True).transform
    route_metric = transform(forward, route)
    corridor = route_metric.buffer(radius_miles * MILE)
    west, south, east, north = transform(reverse, corridor).bounds
    west, east = max(-180, west), min(180, east)
    south, north = max(-85, south), min(85, north)
    tiles = _corridor_tiles(coordinates, radius_miles)
    found = {}
    coverage = {}
    for state in STATES:
        archive = _archive(state)
        if not archive.is_file():
            coverage[state] = 'missing archive'
            continue
        bounds = _read_bounds(archive)
        if bounds and (bounds[2] < west or bounds[0] > east or bounds[3] < south or bounds[1] > north):
            continue
        coverage[state] = _archive_coverage(state)
        with _tile_reader(archive) as read_tile:
            for x, y in sorted(tiles):
                if not transform(forward, _tile_bounds(x, y)).intersects(corridor):
                    continue
                blob = read_tile(x, y)
                if not blob:
                    continue
                raw = gzip.decompress(blob) if blob[:2] == b'\x1f\x8b' else blob
                layer = mapbox_vector_tile.decode(raw, default_options={'y_coord_down': True}).get('parcels')
                if not layer:
                    continue
                extent = layer.get('extent', 4096)
                for feature in layer['features']:
                    geometry = _to_geojson_geometry(feature['geometry'], x, y, extent)
                    if geometry.is_empty:
                        continue
                    parcel_metric = transform(forward, geometry)
                    if not parcel_metric.intersects(corridor):
                        continue
                    props = feature.get('properties', {})
                    identity = str(props.get('source_uid') or props.get('parcel_id') or
                                   props.get('OBJECTID') or props.get('APN') or feature.get('id') or '')
                    key = (state, identity) if identity else (state, x, y, len(found))
                    relation = 'crossed' if parcel_metric.intersects(route_metric) else 'within_0_5_mile'
                    previous = found.get(key)
                    if previous and relation == 'crossed':
                        previous['relation'] = 'crossed'
                    found.setdefault(key, {
                        'state': state,
                        'identity': identity or None,
                        'label': str(props.get('APN') or props.get('PARCEL_APN') or
                                     props.get('parcel_id') or props.get('ACCOUNTNO') or 'Parcel'),
                        'relation': relation,
                    })
    return {
        'features': list(found.values()),
        'complete': bool(coverage) and all(value == 'complete' for value in coverage.values()),
        'coverage': coverage,
        'radius_miles': radius_miles,
    }
