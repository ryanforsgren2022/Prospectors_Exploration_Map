"""Synthetic filesystem migration tests only. Never opens production archives."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'scripts'))
from mbtiles_migration import Blocked, apply, preflight, rollback, sha


class StoragePlanTests(unittest.TestCase):
    def fixture(self):
        workspace = Path(tempfile.mkdtemp(prefix='mbtiles-migration-test-'))
        root = workspace / 'data'
        source = root / 'id/claims/id-claims-active-blm-lands.mbtiles'
        source.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE metadata(name TEXT,value TEXT)')
            db.execute('INSERT INTO metadata VALUES(?,?)', ('json', json.dumps({'vector_layers': [{'id': 'claims', 'fields': {'CSE_DISP': 'String', 'ORIGINAL': 'String'}}]})))
            db.execute('CREATE TABLE tiles(zoom_level INT,tile_column INT,tile_row INT,tile_data BLOB)')
            db.execute('INSERT INTO tiles VALUES(8,0,0,?)', (b'original-geometry-and-attributes',))
            db.commit()
        operation = {'id': 'one', 'kind': 'link', 'source': str(source.relative_to(root)),
                     'destination': 'id/claims-blm-lands/tiles/id-claims-blm-lands.mbtiles',
                     'expectedBytes': source.stat().st_size, 'expectedSourceLayers': ['claims']}
        return workspace, root, source, {'operations': [operation]}

    def test_check_is_read_only_and_apply_requires_approval(self):
        workspace, root, source, manifest = self.fixture()
        digest = sha(source)
        preflight(manifest, root)
        self.assertFalse((root / manifest['operations'][0]['destination']).exists())
        with self.assertRaises(Blocked):
            apply(manifest, root, workspace / 'receipt.json')
        self.assertFalse((workspace / 'receipt.json').exists())
        self.assertEqual(sha(source), digest)

    def test_migration_and_rollback_preserve_every_byte_and_file(self):
        workspace, root, source, manifest = self.fixture()
        digest = sha(source)
        receipt = workspace / 'receipt.json'
        result = apply(manifest, root, receipt, True, True)
        destination = root / manifest['operations'][0]['destination']
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(sha(destination), digest)
        self.assertTrue(source.samefile(destination))
        self.assertEqual(rollback(receipt)['status'], 'rollback-check-passed')
        self.assertTrue(destination.exists())  # Check-only rollback does not mutate.
        result = rollback(receipt, True, True, True)
        self.assertEqual(result['filesDeleted'], 0)
        self.assertTrue(source.exists())
        retained = list(root.glob('id/migration-rollback/tiles/*.mbtiles'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(sha(retained[0]), digest)
        self.assertEqual(sha(source), digest)
        with self.assertRaises(Blocked):
            rollback(receipt, True, True, True)

    def test_existing_target_is_never_overwritten(self):
        workspace, root, source, manifest = self.fixture()
        destination = root / manifest['operations'][0]['destination']
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b'unique conflicting data')
        with self.assertRaises(Blocked):
            preflight(manifest, root)
        self.assertEqual(destination.read_bytes(), b'unique conflicting data')
        self.assertTrue(source.exists())

    def test_symlink_escape_and_metadata_drift_are_blocked(self):
        workspace, root, source, manifest = self.fixture()
        manifest['operations'][0]['destination'] = '../outside.mbtiles'
        with self.assertRaises(Blocked):
            preflight(manifest, root)
        manifest['operations'][0]['destination'] = 'id/alias/tiles/file.mbtiles'
        (root / 'id/alias').symlink_to(workspace, target_is_directory=True)
        with self.assertRaises(Blocked):
            preflight(manifest, root)
        manifest['operations'][0]['destination'] = 'id/claims-blm-lands/tiles/id-claims-blm-lands.mbtiles'
        manifest['operations'][0]['expectedSourceLayers'] = ['wrong_layer']
        with self.assertRaises(Blocked):
            preflight(manifest, root)

    def test_failed_integrity_stops_before_any_destination_is_created(self):
        workspace, root, source, manifest = self.fixture()
        source.write_bytes(b'invalid sqlite file')
        manifest['operations'][0]['expectedBytes'] = source.stat().st_size
        with self.assertRaises(sqlite3.Error):
            preflight(manifest, root)
        self.assertFalse((root / manifest['operations'][0]['destination']).exists())

    def test_final_manifest_excludes_partial_archives_and_preserves_master_layers(self):
        manifest = json.loads((BASE / 'docs/mbtiles-path-manifest.json').read_text())
        excluded = json.loads((BASE / 'docs/washington-excluded-archives.json').read_text())
        self.assertEqual(len(excluded), 2)
        self.assertEqual(manifest['selectedArchiveCount'], 98)
        self.assertEqual(manifest['counts']['filenameChanges'], 26)
        self.assertEqual(manifest['counts']['directoryOnlyChanges'], 6)
        excluded_paths = {row['oldPath'] for row in excluded}
        self.assertTrue(excluded_paths.isdisjoint(row['oldPath'] for row in manifest['allArchives']))
        operations = manifest['operations']
        self.assertTrue(all(op['kind'] == 'link' for op in operations))
        self.assertTrue(all(not any(path.endswith(op['source']) for path in excluded_paths) for op in operations))
        self.assertEqual(sum(op['executionBlocked'] for op in operations), 2)
        wa_layers = {layer for row in manifest['selectedArchiveMigrations'] if row['state'] == 'wa' for layer in row['sourceLayers']}
        self.assertTrue({'plss_government_lots', 'plss_quarter_quarter_sections', 'plss_special_surveys'} <= wa_layers)
        id_changes = [(row['currentFilename'], row['proposedFilename']) for row in manifest['selectedArchiveMigrations']
                      if row['state'] == 'id' and row['currentFilename'] != row['proposedFilename']]
        self.assertEqual(set(id_changes), {('id-claims-active-blm-lands.mbtiles', 'id-claims-blm-lands.mbtiles'),
                                          ('id-plss-intersected.mbtiles', 'id-plss-intersected-surveys.mbtiles')})
        registry = json.loads((BASE / 'vm-review/western-datasets.json').read_text())
        destinations = {
            (row['oldPath'].split('/data/', 1)[-1],
             row['proposedCanonicalPath'].split('/data/', 1)[-1])
            for row in manifest['selectedArchiveMigrations']
        }
        registered = {
            (entry['path'], entry.get('canonicalPath', entry.get('canonicalPathBlocked')))
            for state in registry['states'].values()
            for entry in state['datasets'].values()
        }
        self.assertEqual(registered, destinations)
        for group in ('plssGovernmentLots', 'plssQuarterQuarterSections'):
            entry = registry['states']['wa']['datasets'][group]
            self.assertNotIn('canonicalPath', entry)
            self.assertIn('canonicalPathBlocked', entry)


if __name__ == '__main__':
    unittest.main()
