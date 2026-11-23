import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vm-review'))
from aem_route_graph import DRIVE, HIKE, allowed_modes, find_path, initialize


class RouteGraphTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        initialize(self.db)
        nodes = [(1, -112.0, 33.0), (2, -111.999, 33.0), (3, -111.998, 33.0)]
        self.db.executemany('INSERT INTO nodes VALUES(?,?,?)', nodes)
        self.db.executemany('INSERT INTO node_bounds VALUES(?,?,?,?,?)',
                            [(node, lng, lng, lat, lat) for node, lng, lat in nodes])
        self.db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?)', [
            (1, 2, DRIVE | HIKE, 93, 10, 'Road'),
            (2, 1, DRIVE | HIKE, 93, 10, 'Road'),
            (2, 3, HIKE, 93, 11, 'Trail'),
            (3, 2, HIKE, 93, 11, 'Trail'),
        ])

    def tearDown(self):
        self.db.close()

    def test_hiking_connects_road_and_trail(self):
        route = find_path(self.db, (-112.0, 33.0), (-111.998, 33.0), HIKE)
        self.assertEqual(len(route['geometry']['coordinates']), 3)
        self.assertEqual(route['distance_meters'], 186)

    def test_driving_does_not_use_trail(self):
        route = find_path(self.db, (-112.0, 33.0), (-111.998, 33.0), DRIVE)
        self.assertEqual(route['geometry']['coordinates'][-1], [-111.999, 33.0])
        self.assertGreater(route['snapped_end_meters'], 90)

    def test_private_access_is_excluded(self):
        self.assertEqual(allowed_modes({'highway': 'track', 'access': 'private'}), 0)
        self.assertEqual(allowed_modes({'highway': 'path', 'foot': 'yes'}), HIKE)

    def test_same_snapped_node_is_not_reported_as_a_route(self):
        with self.assertRaisesRegex(ValueError, 'same road or trail node'):
            find_path(self.db, (-112.0, 33.0), (-112.0, 33.0), DRIVE)


if __name__ == '__main__':
    unittest.main()
