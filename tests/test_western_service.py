"""Exercise the copied discovery/route functions with real SQLite fixtures.
When FastAPI is unavailable, a response/decorator shim tests handler behavior,
not ASGI routing or HTTP transport. Nothing connects to or modifies production.
"""
import gzip
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'vm-review'))
try:
    import fastapi
except ImportError:
    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
    class Response:
        def __init__(self, content=b'', status_code=200, headers=None, media_type=None):
            self.body = content.encode() if isinstance(content, str) else content
            self.status_code = status_code
            self.headers = headers or {}
    sys.modules['fastapi'] = types.SimpleNamespace(HTTPException=HTTPException, Response=Response, Request=object)
    sys.modules['starlette.responses'] = types.SimpleNamespace(StreamingResponse=Response)
    print('FastAPI unavailable: testing direct handlers with a response shim; no HTTP transport claim.')

spec = importlib.util.spec_from_file_location('discovery', BASE / 'vm-review/aem_vm_discovery_v2.py')
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def field(key, payload):
    return varint(key) + varint(len(payload)) + payload


def vector_tile(names):
    # Point feature, ID 1, MoveTo(1,1), version 2, extent 4096.
    feature = b'\x08\x01\x12\x02\x00\x00\x18\x01\x22\x03\x09\x02\x02'
    return b''.join(field(26, field(10, name.encode()) + field(18, feature) + field(26, b'CSE_DISP') + field(34, field(10, b'Active')) + b'\x28\x80\x20\x78\x02') for name in names)


class App:
    def __init__(self):
        self.routes = {}
    def get(self, route):
        def install(function):
            self.routes[route] = function
            return function
        return install


class WesternServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((BASE / 'vm-review/western-datasets.json').read_text())
        audit = json.loads((BASE / 'vm-review/mbtiles-audit.json').read_text())
        records = {r['real_path']: r for r in audit['archives']}
        cls.temporary = Path(tempfile.mkdtemp(prefix='western-service-fixtures-'))
        cls.data = cls.temporary / 'physical-data'
        cls.data.mkdir()
        cls.alias = cls.temporary / 'data-alias'
        cls.alias.symlink_to(cls.data, target_is_directory=True)
        service.DATA = cls.alias.resolve()
        service.REGISTRY = BASE / 'vm-review/western-datasets.json'
        service.CACHE_DATA = None
        paths = {}
        for state in cls.registry['states'].values():
            for entry in state['datasets'].values():
                paths.setdefault(entry['path'], []).append(entry)
        for relative, entries in paths.items():
            path = cls.data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            record = records[str(Path(audit['canonical_data_root']) / relative)]
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE metadata(name TEXT, value TEXT)')
                db.executemany('INSERT INTO metadata VALUES(?,?)', record['metadata'].items())
                db.execute('CREATE TABLE tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)')
                for zoom in {e['minzoom'] for e in entries}:
                    db.execute('INSERT INTO tiles VALUES(?,?,?,?)', (zoom, 0, (1 << zoom) - 1,
                        gzip.compress(vector_tile(record['source_layers']))))
                db.commit()
            # Sparse padding checks the actual audit byte-size drift guard without copying VM data.
            with path.open('ab') as stream:
                stream.truncate(record['bytes'])
            os.utime(path, (1000000000, 1000000000))
        cls.app = App()
        service.install_aem_vm_discovery_v2(cls.app)

    def test_classification_counts_and_removed_features(self):
        try:
            from tests.test_claims_classification import fixture, MISSING
        except ImportError:
            from test_claims_classification import fixture, MISSING
        from audit_claim_classifications import scan
        path = self.data / self.registry['states']['az']['datasets']['claims']['path']
        with closing(sqlite3.connect(path)) as db:
            original = db.execute('SELECT tile_data FROM tiles').fetchone()[0]
            payload, _ = fixture(['Active', 'Filed', ' CLOSED ', None, MISSING, 'Under Review'], layer_name='claims_not_closed')
            db.execute('UPDATE tiles SET tile_data=?', (gzip.compress(payload),))
            db.commit()
        with path.open('ab') as stream:
            stream.truncate(self.registry['states']['az']['datasets']['claims']['auditBytes'])
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None
        response = self.app.routes['/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf']('az', 'claims', 6, 0, 0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-AEM-Claims-Before'], '6')
        self.assertEqual(response.headers['X-AEM-Claims-After'], '3')
        self.assertEqual(response.headers['X-AEM-Claims-Closed'], '1')
        self.assertEqual(response.headers['X-AEM-Claims-Unknown'], '2')
        self.assertEqual(json.loads(response.headers['X-AEM-Claims-By-Classification']),
                         {'active': 1, 'filed': 1, 'closed': 1, 'under review': 1})
        counts = scan({'real_path': str(path), 'source_layers': ['claims_not_closed']})
        self.assertEqual(counts['status'], 'PASS')
        self.assertEqual((counts['before'], counts['after'], counts['closed'], counts['unknown']), (6, 3, 1, 2))
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE tiles SET tile_data=?', (original,))
            db.commit()
        with path.open('ab') as stream:
            stream.truncate(self.registry['states']['az']['datasets']['claims']['auditBytes'])
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None

    def test_canonical_alias_requires_a_reviewed_match(self):
        wa_entry = self.registry['states']['wa']['datasets']['plssGovernmentLots']
        self.assertNotIn('canonicalPath', wa_entry)
        self.assertEqual(wa_entry['canonicalPathBlocked'],
                         'wa/plss/tiles/wa-plss-government-lots.mbtiles')
        entry = self.registry['states']['id']['datasets']['claimsBlmLands']
        current = self.data / entry['path']
        canonical = self.data / entry['canonicalPath']
        self.assertNotEqual(current, canonical)
        canonical.parent.mkdir(parents=True, exist_ok=True)

        # An unrelated archive occupying the standardized destination must not
        # displace the reviewed statewide Washington source.
        wrong = self.data / self.registry['states']['id']['datasets']['boundary']['path']
        os.link(wrong, canonical)
        service.CACHE_DATA = None
        self.assertEqual(service.discover_vm_data()[1][('id', 'claimsBlmLands')]['path'], current)
        canonical.unlink()

        # The migration plan creates verified hard-link aliases. Once present,
        # discovery may use the canonical spelling without changing route IDs.
        os.link(current, canonical)
        service.CACHE_DATA = None
        self.assertEqual(service.discover_vm_data()[1][('id', 'claimsBlmLands')]['path'], canonical)
        canonical.unlink()
        service.CACHE_DATA = None

    def test_legacy_utah_claim_route_uses_registered_filter(self):
        try:
            from tests.test_claims_classification import fixture, MISSING
        except ImportError:
            from test_claims_classification import fixture, MISSING
        sys.modules['aem_vm_discovery_v2'] = service
        utah_spec = importlib.util.spec_from_file_location('utah_layers', BASE / 'vm-review/aem_utah_layers.py')
        utah = importlib.util.module_from_spec(utah_spec)
        utah_spec.loader.exec_module(utah)
        async def inline(function, *args):
            return function(*args)
        utah.asyncio = types.SimpleNamespace(to_thread=inline)
        app = App()
        utah.install(app)
        path = self.data / self.registry['states']['ut']['datasets']['claims']['path']
        with closing(sqlite3.connect(path)) as db:
            original = db.execute('SELECT tile_data FROM tiles').fetchone()[0]
            payload, _ = fixture(['Filed', ' closed ', None, MISSING], layer_name='claims')
            db.execute('UPDATE tiles SET tile_data=?', (gzip.compress(payload),))
            db.commit()
        with path.open('ab') as stream:
            stream.truncate(self.registry['states']['ut']['datasets']['claims']['auditBytes'])
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None
        import asyncio
        response = asyncio.run(app.routes['/ut/layers/{kind}/{z}/{x}/{y}.pbf'](
            'claims', self.registry['states']['ut']['datasets']['claims']['minzoom'], 0, 0
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-AEM-Claims-After'], '1')
        self.assertEqual(response.headers['X-AEM-Claims-Closed'], '1')
        self.assertEqual(response.headers['X-AEM-Claims-Unknown'], '2')
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE tiles SET tile_data=?', (original,))
            db.commit()
        with path.open('ab') as stream:
            stream.truncate(self.registry['states']['ut']['datasets']['claims']['auditBytes'])
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None

    def test_discovery_and_every_registered_tile(self):
        response = self.app.routes['/api/states/discover-v2']()
        discovered = json.loads(response.body)
        self.assertEqual(discovered['schemaVersion'], 2)
        self.assertEqual(len(discovered['states']), 11)
        reader = self.app.routes['/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf']
        checked = 0
        for code, state in self.registry['states'].items():
            actual = discovered['states'][code]['datasets']
            for group, entry in state['datasets'].items():
                if group.startswith('withdrawals'):
                    kind = group.removeprefix('withdrawals').lower()
                    dataset = actual['withdrawals'][kind]
                else:
                    dataset = actual[group]
                self.assertEqual(dataset['sourceLayer'], entry['sourceLayer'])
                self.assertEqual(dataset['bounds'], entry['bounds'])
                self.assertEqual(dataset['minzoom'], entry['minzoom'])
                self.assertEqual(dataset['maxzoom'], entry['maxzoom'])
                self.assertEqual(
                    dataset['tiles'],
                    [f'https://tiles.americanexplorationmaps.com/api/vm-data/{code}/{group}/{{z}}/{{x}}/{{y}}.pbf']
                )
                response = reader(code, group, entry['minzoom'], 0, 0)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get('Content-Encoding'), 'gzip')
                self.assertIn(entry['sourceLayer'].encode(), gzip.decompress(response.body))
                checked += 1
        self.assertEqual(checked, 117)

    def test_missing_and_invalid_coordinates(self):
        reader = self.app.routes['/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf']
        for args in [('az', 'claims', -1, 0, 0), ('az', 'claims', 6, 64, 0), ('id', 'claims', 8, 0, 0)]:
            with self.assertRaises(service.HTTPException) as raised:
                reader(*args)
            self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(reader('az', 'claims', 6, 1, 1).status_code, 204)

    def test_montana_uses_canonical_archive_without_requiring_duplicate(self):
        from audit_claim_classifications import audit_counts
        state = self.registry['states']['mt']
        entry = state['datasets']['claims']
        canonical = self.data / 'mt/claims/mt-claims.mbtiles'
        duplicate = self.data / 'mt/claims/montana-claims-active.mbtiles'
        self.assertEqual(entry['path'], 'mt/claims/mt-claims.mbtiles')
        self.assertFalse(duplicate.exists())  # Fixture never creates the duplicate.
        service.CACHE_DATA = None
        states, paths = service.discover_vm_data()
        self.assertEqual(paths[('mt', 'claims')]['path'], canonical)
        self.assertEqual(states['mt']['datasets']['claims']['sourceLayer'], 'claims')
        response = self.app.routes['/api/vm-data/{state}/{group}/{z}/{x}/{y}.pbf'](
            'mt', 'claims', entry['minzoom'], 0, 0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-AEM-Claims-After'], '1')
        audit = {'canonical_data_root': str(self.data), 'archives': [
            {'real_path': str(duplicate), 'file_identity': 'duplicate', 'source_layers': ['claims']},
            {'real_path': str(canonical), 'file_identity': 'canonical', 'source_layers': ['claims']}
        ]}
        counts = audit_counts(audit, self.registry)
        self.assertEqual(counts['states']['mt']['status'], 'PASS')
        self.assertEqual(len(counts['states']['mt']['archives']), 1)
        self.assertEqual(counts['excludedHistoricalDuplicates'], [str(duplicate)])

    def test_scope_and_all_plss_names(self):
        states, _ = service.discover_vm_data()
        self.assertEqual(self.registry['states']['mt']['datasets']['claims']['path'], 'mt/claims/mt-claims.mbtiles')
        self.assertEqual(states['mt']['datasets']['claims']['sourceLayer'], 'claims')
        self.assertNotIn('claims', states['id']['datasets'])
        self.assertEqual(states['id']['datasets']['claimsBlmLands']['semantics'], 'notClosed')
        self.assertEqual(states['nm']['datasets']['plssSections']['sourceLayer'], 'nm_plss_sections')
        self.assertEqual(states['wy']['datasets']['plssSecondDivision']['sourceLayer'], 'plss_second_division')
        self.assertEqual(states['az']['datasets']['plssGovernmentLots']['minzoom'], 11)

    def test_symlink_root_and_metadata_drift(self):
        self.assertEqual(service.DATA, self.data.resolve())
        path = self.data / self.registry['states']['az']['datasets']['claims']['path']
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE metadata SET value='0,0,1,1' WHERE name='bounds'")
            db.commit()
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None
        states, _ = service.discover_vm_data()
        self.assertNotIn('claims', states['az']['datasets'])
        # Restore fixture for other methods; no source archives are involved.
        bounds = ','.join(str(v) for v in self.registry['states']['az']['datasets']['claims']['bounds'])
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE metadata SET value=? WHERE name='bounds'", (bounds,))
            db.commit()
        os.utime(path, (1000000000, 1000000000))
        service.CACHE_DATA = None

    def test_vm_handoff_verifier_exercises_every_registration(self):
        verifier_spec = importlib.util.spec_from_file_location(
            'backend_verifier', BASE / 'vm-review/verify_backend_integration.py'
        )
        verifier = importlib.util.module_from_spec(verifier_spec)
        verifier_spec.loader.exec_module(verifier)
        result = verifier.verify(self.data, BASE / 'vm-review/western-datasets.json')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['states'], 11)
        self.assertEqual(result['registrations'], 117)
        self.assertEqual(result['representativeRequests'], 117)
        self.assertFalse(result['writesPerformed'])


if __name__ == '__main__':
    unittest.main()
