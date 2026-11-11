"""Claim layer names are recognized uniformly for every supported state."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from test_live_plss_discovery import discovery

class ClaimsDiscoveryTest(unittest.TestCase):
    def test_claim_aliases_are_discoverable_for_every_state(self):
        for layer in ('claims', 'claims_not_closed', 'mining_claims'):
            with self.subTest(layer=layer), tempfile.TemporaryDirectory() as tmp:
                discovery.DATA = Path(tmp)
                discovery.CACHE_DATA = None
                for state in ('az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy'):
                    folder = Path(tmp) / state
                    folder.mkdir()
                    (folder / 'state.json').write_text(json.dumps({'bounds': [-120, 30, -100, 50]}))
                    path = folder / 'claims.mbtiles'
                    with closing(sqlite3.connect(path)) as db:
                        db.execute('create table metadata (name text, value text)')
                        db.executemany('insert into metadata values (?, ?)', [('format', 'pbf'), ('minzoom', '6'), ('maxzoom', '16'), ('json', json.dumps({'vector_layers': [{'id': layer}]}))])
                        db.commit()
                    os.utime(path, (time.time() - 30, time.time() - 30))
                states, paths = discovery.discover_vm_data()
                self.assertEqual(len(states), 11)
                for state, info in states.items():
                    self.assertEqual(info['datasets']['claims']['sourceLayer'], layer, state)
                    self.assertEqual(info['datasets']['claims']['semantics'], 'notClosed', state)
                    self.assertEqual(info['datasets']['claims']['classificationFilter']['unknownPolicy'], 'report-separately', state)
                    self.assertIn((state, 'claims'), paths)

if __name__ == '__main__':
    unittest.main()

class ClaimsTileFilterTest(unittest.TestCase):
    def test_live_route_filters_all_statuses(self):
        import gzip
        from test_claims_classification import fixture, MISSING
        class Result:
            def __init__(self, content=b'', **kwargs):
                self.content = content
                self.headers = kwargs.get('headers', {})
        class App:
            def __init__(self): self.routes = {}
            def get(self, path):
                def register(fn): self.routes[path] = fn; return fn
                return register
        with tempfile.TemporaryDirectory() as tmp:
            dbfile = Path(tmp) / 'claims.mbtiles'
            payload, _ = fixture(['Active', 'Filed', 'Closed', MISSING], layer_name='mining_claims')
            with closing(sqlite3.connect(dbfile)) as db:
                db.execute('create table tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
                db.execute('insert into tiles values (0,0,0,?)', (gzip.compress(payload),)); db.commit()
            archive = {'path': dbfile, 'format': '.mbtiles', 'minzoom': 0, 'maxzoom': 0, 'sourceLayer': 'mining_claims'}
            previous_discover, previous_response = discovery.discover_vm_data, discovery.Response
            try:
                discovery.discover_vm_data = lambda: ({}, {('ca', 'claims'): archive})
                discovery.Response = Result
                app = App(); discovery.install_aem_vm_discovery_v2(app)
                response = app.routes['/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf']('ca', 'claims', 0, 0, 0)
                self.assertEqual(response.headers['X-AEM-Claims-Before'], '4')
                self.assertEqual(response.headers['X-AEM-Claims-After'], '2')
                self.assertEqual(response.headers['X-AEM-Claims-Closed'], '1')
                self.assertEqual(response.headers['X-AEM-Claims-Unknown'], '1')
            finally:
                discovery.discover_vm_data, discovery.Response = previous_discover, previous_response
