"""AEM route planning and post-display discovery endpoints.

This router reads a derived routing graph and the existing search indexes. It
never changes production indexes, MapLibre layer visibility, or PLSS state.
"""
import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pyproj import CRS, Transformer
from shapely.geometry import LineString, box
from shapely.ops import transform

from aem_route_graph import DRIVE, HIKE, find_path
from aem_route_parcels import parcel_corridor

router = APIRouter(prefix='/api/routes', tags=['AEM Routes'])
GRAPH = Path(os.environ.get('AEM_ROUTE_GRAPH', '/mnt/volume_sfo3_1794422503599/aem-routing/routes.sqlite'))
INDEXES = Path(os.environ.get('AEM_SEARCH_INDEXES', '/mnt/volume_sfo3_1794422503599/updater/data/search-v2'))
STATES = ('az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy')


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
    points = _validated_points(request.points)
    mode = {'driving': DRIVE, 'hiking': HIKE}.get(request.mode)
    if mode is None:
        raise HTTPException(400, 'Route mode must be driving or hiking')
    if not GRAPH.is_file():
        raise HTTPException(503, 'Routing graph is not available')
    coordinates = []
    distance = 0
    try:
        with sqlite3.connect(f'file:{GRAPH}?mode=ro', uri=True, timeout=5) as db:
            for start, finish in zip(points, points[1:]):
                part = find_path(db, start, finish, mode)
                coordinates.extend(part['geometry']['coordinates'][1:] if coordinates else
                                   part['geometry']['coordinates'])
                distance += part['distance_meters']
    except (sqlite3.Error, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    return {'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'distance_meters': distance, 'mode': request.mode,
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
