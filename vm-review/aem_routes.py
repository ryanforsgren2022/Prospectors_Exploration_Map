"""AEM route planning and post-display discovery endpoints.

This router reads a derived routing graph and the existing search indexes. It
never changes production indexes, MapLibre layer visibility, or PLSS state.
"""
import os
import sqlite3
from threading import BoundedSemaphore
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pyproj import CRS, Transformer
from shapely.geometry import LineString, box
from shapely.ops import transform

from aem_route_graph import DRIVE, HIKE, find_path
from aem_route_parcels import parcel_corridor
from aem_route_config import STATES, INDEX_ROOT

router = APIRouter(prefix='/api/routes', tags=['AEM Routes'])
GRAPH = Path(os.environ.get('AEM_ROUTE_GRAPH', '/mnt/volume_sfo3_1794422503599/aem-routing/routes.sqlite'))
INDEXES = Path(os.environ.get('AEM_SEARCH_INDEXES', str(INDEX_ROOT)))
PLAN_SLOT = BoundedSemaphore(1)
PARCEL_SLOT = BoundedSemaphore(1)


def _limited(slot, operation, request):
    if not slot.acquire(blocking=False):
        raise HTTPException(429, 'Route service is busy; retry shortly',
                            headers={'Retry-After': '5'})
    try:
        return operation(request)
    finally:
        slot.release()


@router.get('/health')
def routes_health():
    imported = set()
    if GRAPH.is_file():
        try:
            with sqlite3.connect(f'file:{GRAPH}?mode=ro', uri=True, timeout=2) as db:
                imported = {row[0] for row in db.execute('SELECT state FROM route_sources')}
        except sqlite3.Error:
            pass
    return {'ready': imported == set(STATES), 'states': sorted(imported),
            'missing_states': sorted(set(STATES) - imported)}


class PlanRequest(BaseModel):
    points: list[list[float]] = Field(min_length=2, max_length=12)
    mode: str


class DiscoverRequest(BaseModel):
    kind: str
    path: list[list[float]] = Field(min_length=2, max_length=100000)
    radius_miles: float = Field(gt=0, le=100)


def _validated_points(points):
    if any(len(point) != 2 or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90
           for point in points):
        raise HTTPException(400, 'Invalid route coordinates')
    return points


@router.post('/plan')
def plan_route(request: PlanRequest):
    return _limited(PLAN_SLOT, _plan_route, request)


def _plan_route(request: PlanRequest):
    points = _validated_points(request.points)
    mode = {'driving': DRIVE, 'hiking': HIKE}.get(request.mode)
    if mode is None:
        raise HTTPException(400, 'Route mode must be driving or hiking')
    if not GRAPH.is_file():
        raise HTTPException(503, 'Routing graph is not available')
    coordinates = []
    distance = 0
    snapped_points = []
    try:
        with sqlite3.connect(f'file:{GRAPH}?mode=ro', uri=True, timeout=5) as db:
            try:
                imported = {row[0] for row in db.execute('SELECT state FROM route_sources')}
            except sqlite3.Error as error:
                raise HTTPException(503, 'Routing graph has not passed the all-state build') from error
            if imported != set(STATES):
                raise HTTPException(503, 'Routing graph is incomplete')
            for start, finish in zip(points, points[1:]):
                part = find_path(db, start, finish, mode)
                coordinates.extend(part['geometry']['coordinates'][1:] if coordinates else
                                   part['geometry']['coordinates'])
                distance += part['distance_meters']
                if not snapped_points:
                    snapped_points.append(part['snapped_start_meters'])
                snapped_points.append(part['snapped_end_meters'])
    except (sqlite3.Error, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return {'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'distance_meters': distance, 'mode': request.mode,
            'snapped_points_meters': snapped_points,
            'access_notice': 'Verify road and trail access, closures, and conditions before travel.'}


def _nearby_index(kind, coordinates, radius_miles):
    route = LineString(coordinates)
    middle = route.interpolate(0.5, normalized=True)
    metric = CRS.from_proj4(f'+proj=aeqd +lat_0={middle.y} +lon_0={middle.x} +datum=WGS84 +units=m')
    forward = Transformer.from_crs('EPSG:4326', metric, always_xy=True).transform
    reverse = Transformer.from_crs(metric, 'EPSG:4326', always_xy=True).transform
    corridor = transform(forward, route).buffer(radius_miles * 1609.344)
    west, south, east, north = transform(reverse, corridor).bounds
    features = []
    coverage = {}
    for state in STATES:
        path = INDEXES / state / f'{kind}.sqlite'
        if not path.is_file():
            coverage[state] = 'missing index'
            continue
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5) as db:
            rows = db.execute('''SELECT identity,label,county,west,south,east,north,lng,lat
                FROM records WHERE west <= ? AND east >= ? AND south <= ? AND north >= ?
                LIMIT 5001''', (east, west, north, south)).fetchall()
        if len(rows) > 5000:
            coverage[state] = 'truncated'
            rows = rows[:5000]
        else:
            coverage[state] = 'index checked'
        for identity, label, county, fw, fs, fe, fn, lng, lat in rows:
            if None in (fw, fs, fe, fn):
                continue
            if not transform(forward, box(fw, fs, fe, fn)).intersects(corridor):
                continue
            features.append({'state': state, 'identity': identity, 'label': label,
                             'county': county, 'lng': lng, 'lat': lat})
    return {'features': features, 'complete': all(v == 'index checked' for v in coverage.values()),
            'coverage': coverage, 'proximity_type': 'bounding-box candidate'}


@router.post('/discover')
def discover_route(request: DiscoverRequest):
    if request.kind == 'Private parcels within 0.5 mile':
        return _limited(PARCEL_SLOT, _discover_route, request)
    return _discover_route(request)


def _discover_route(request: DiscoverRequest):
    coordinates = _validated_points(request.path)
    if request.kind == 'Private parcels within 0.5 mile':
        if request.radius_miles != 0.5:
            raise HTTPException(400, 'Private parcel corridor is fixed at 0.5 mile')
        try:
            return parcel_corridor(coordinates, 0.5)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    if request.kind in ('claims', 'historic-mines'):
        return _nearby_index(request.kind, coordinates, request.radius_miles)
    raise HTTPException(400, 'Unsupported discovery category')
