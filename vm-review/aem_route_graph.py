"""Build and query a connected road/trail graph without changing search indexes.

Input is an official OSM extract with node IDs and complete way geometry. The
existing search index remains the reference for names and feature discovery.
"""
import argparse
import heapq
import math
import sqlite3
from pathlib import Path

DRIVE = 1
HIKE = 2
ROAD_TYPES = {
    'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link',
    'secondary', 'secondary_link', 'tertiary', 'tertiary_link', 'unclassified',
    'residential', 'living_street', 'service', 'track', 'road',
}
TRAIL_TYPES = {'path', 'footway', 'pedestrian', 'steps', 'bridleway', 'cycleway'}
NO_ACCESS = {'no', 'private'}


def distance_m(a, b):
    latitude = math.radians(b[1] - a[1])
    longitude = math.radians(b[0] - a[0])
    arc = (math.sin(latitude / 2) ** 2 +
           math.cos(math.radians(a[1])) * math.cos(math.radians(b[1])) *
           math.sin(longitude / 2) ** 2)
    return 12742017.6 * math.atan2(math.sqrt(arc), math.sqrt(1 - arc))


def allowed_modes(tags):
    highway = tags.get('highway')
    if highway not in ROAD_TYPES | TRAIL_TYPES or tags.get('access') in NO_ACCESS:
        return 0
    driving = highway in ROAD_TYPES and tags.get('motor_vehicle') not in NO_ACCESS and \
        tags.get('motorcar') not in NO_ACCESS and tags.get('vehicle') not in NO_ACCESS
    hiking = highway not in {'motorway', 'motorway_link', 'trunk', 'trunk_link'} and \
        tags.get('foot') not in NO_ACCESS
    return (DRIVE if driving else 0) | (HIKE if hiking else 0)


def initialize(db):
    db.executescript('''
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY, lng REAL NOT NULL, lat REAL NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS node_bounds USING rtree(id, min_lng, max_lng, min_lat, max_lat);
    CREATE TABLE IF NOT EXISTS edges(src INTEGER NOT NULL, dst INTEGER NOT NULL,
        modes INTEGER NOT NULL, meters REAL NOT NULL, way_id INTEGER NOT NULL,
        name TEXT NOT NULL, PRIMARY KEY(src,dst,way_id)) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
    ''')


def import_extract(db, path):
    import osmium
    initialize(db)

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.nodes = []
            self.edges = []
            self.seen = 0

        def flush(self):
            if not self.edges:
                return
            with db:
                db.executemany('INSERT OR IGNORE INTO nodes VALUES(?,?,?)', self.nodes)
                db.executemany('INSERT OR IGNORE INTO node_bounds VALUES(?,?,?,?,?)',
                               ((node_id, lng, lng, lat, lat) for node_id, lng, lat in self.nodes))
                db.executemany('INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?)', self.edges)
            self.nodes.clear()
            self.edges.clear()

        def way(self, way):
            tags = dict(way.tags)
            modes = allowed_modes(tags)
            if not modes:
                return
            nodes = list(way.nodes)
            if any(not node.location.valid() for node in nodes):
                return
            points = [(node.ref, node.lon, node.lat) for node in nodes]
            if len(points) < 2:
                return
            self.nodes.extend(points)
            name = str(tags.get('name') or tags.get('ref') or '')[:160]
            one_way = tags.get('oneway') in {'yes', '1', 'true'} or tags.get('junction') == 'roundabout'
            reverse = tags.get('oneway') == '-1'
            for a, b in zip(points, points[1:]):
                meters = distance_m(a[1:], b[1:])
                if not 0 < meters < 20000:
                    continue
                forward_modes = modes if not reverse else modes & ~DRIVE
                backward_modes = modes if not one_way else modes & ~DRIVE
                if forward_modes:
                    self.edges.append((a[0], b[0], forward_modes, meters, way.id, name))
                if backward_modes:
                    self.edges.append((b[0], a[0], backward_modes, meters, way.id, name))
            self.seen += 1
            if len(self.edges) >= 20000:
                self.flush()

    handler = Handler()
    # A disk-backed node-location index keeps large state extracts within VM RAM.
    handler.apply_file(str(path), locations=True, idx='sparse_file_array')
    handler.flush()
    return handler.seen


def nearest_node(db, point, mode, max_meters=200, arrival=False):
    lng, lat = point
    degree = max_meters / 80000
    rows = db.execute('''
        SELECT n.id,n.lng,n.lat FROM node_bounds b JOIN nodes n ON n.id=b.id
        WHERE b.min_lng BETWEEN ? AND ? AND b.min_lat BETWEEN ? AND ?
        ORDER BY (n.lng-?)*(n.lng-?) + (n.lat-?)*(n.lat-?) LIMIT 20000
    ''', (lng - degree, lng + degree, lat - degree, lat + degree,
          lng, lng, lat, lat))
    choices = sorted(((distance_m(point, (row[1], row[2])), row) for row in rows), key=lambda item: item[0])
    for meters, row in choices:
        if meters > max_meters:
            break
        column = 'dst' if arrival else 'src'
        if db.execute(f'SELECT 1 FROM edges WHERE {column}=? AND (modes & ?) != 0 LIMIT 1',
                      (row[0], mode)).fetchone():
            return row
    return None


def find_path(db, start, finish, mode, max_visits=1500000):
    if mode not in (DRIVE, HIKE):
        raise ValueError('Invalid route mode')
    snap_limit = 150 if mode == DRIVE else 200
    source = nearest_node(db, start, mode, snap_limit)
    target = nearest_node(db, finish, mode, snap_limit, arrival=True)
    if not source or not target:
        raise ValueError('No connected road or trail near a route point')
    if source[0] == target[0]:
        raise ValueError('Route points resolve to the same road or trail node')
    goal = target[0]
    best = {source[0]: 0.0}
    prior = {}
    queue = [(distance_m(source[1:], target[1:]), 0.0, source[0])]
    visits = 0
    while queue and visits < max_visits:
        _, cost, node = heapq.heappop(queue)
        if cost > best.get(node, math.inf):
            continue
        if node == goal:
            break
        visits += 1
        for dst, lng, lat, meters in db.execute('''
            SELECT e.dst,n.lng,n.lat,e.meters FROM edges e
            JOIN nodes n ON n.id=e.dst
            WHERE e.src=? AND (e.modes & ?) != 0
        ''', (node, mode)):
            next_cost = cost + meters
            if next_cost >= best.get(dst, math.inf):
                continue
            best[dst] = next_cost
            prior[dst] = node
            heapq.heappush(queue, (next_cost + distance_m((lng, lat), target[1:]), next_cost, dst))
    if goal not in best:
        if visits >= max_visits:
            raise ValueError('Route is too long for the current routing search limit')
        raise ValueError('No connected route found in the available network')
    ids = [goal]
    while ids[-1] != source[0]:
        ids.append(prior[ids[-1]])
    ids.reverse()
    coordinates = []
    for node in ids:
        lng, lat = db.execute('SELECT lng,lat FROM nodes WHERE id=?', (node,)).fetchone()
        coordinates.append([lng, lat])
    return {'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'distance_meters': best[goal], 'snapped_start_meters': distance_m(start, source[1:]),
            'snapped_end_meters': distance_m(finish, target[1:])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('extracts', type=Path, nargs='+')
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.database) as db:
        for path in args.extracts:
            print(path, import_extract(db, path), 'routable ways', flush=True)


if __name__ == '__main__':
    main()
