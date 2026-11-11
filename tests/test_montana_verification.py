from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verification', BASE / 'vm-review/verify_montana_archives.py')
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class MontanaVerificationTests(unittest.TestCase):
    def fixtures(self, different=False):
        root = Path(tempfile.mkdtemp(prefix='montana-verification-'))
        directory = root / 'mt/claims'
        directory.mkdir(parents=True)
        for i, name in enumerate(verification.NAMES):
            with closing(sqlite3.connect(directory / name)) as db:
                db.execute('CREATE TABLE metadata(name TEXT,value TEXT)')
                db.execute('INSERT INTO metadata VALUES(?,?)', ('json', json.dumps({'vector_layers': [{'id': 'claims'}]})))
                db.execute('CREATE TABLE tiles(zoom_level INT,tile_column INT,tile_row INT,tile_data BLOB)')
                db.execute('INSERT INTO tiles VALUES(6,13,40,?)', (b'different' if different and i else b'fixture-tile',))
                db.commit()
        return root

    def test_equivalence_requires_integrity_metadata_and_tile_hashes(self):
        root = self.fixtures()
        result = verification.compare(root)
        self.assertEqual(result['status'], 'IDENTICAL')
        self.assertTrue(result['sameSha256'])
        self.assertFalse(result['canonicalArchiveSelected'])
        for record in result['archives']:
            self.assertEqual(record['integrity'], ['ok'])
            self.assertEqual(record['tileCounts'], [[6, 1, 1]])
            self.assertEqual(len(record['sha256']), 64)

    def test_competing_payloads_are_not_selected(self):
        result = verification.compare(self.fixtures(different=True))
        self.assertEqual(result['status'], 'DIFFERENT')
        self.assertFalse(result['sameSha256'])
        self.assertFalse(result['canonicalArchiveSelected'])

    def test_missing_data_has_explicit_blockers(self):
        result = verification.compare('/tmp/nonexistent-western-dataset-root')
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIsNone(result['resolvedDataRoot'])
        self.assertIsNotNone(result['rootResolutionError'])
        self.assertTrue(all(record['errors'] for record in result['archives']))
        self.assertFalse(result['canonicalArchiveSelected'])


if __name__ == '__main__':
    unittest.main()
