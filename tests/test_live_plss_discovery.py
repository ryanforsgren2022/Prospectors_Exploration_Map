"""Regression coverage for shared discovery of the additional PLSS groups."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
import sys
import types

# Discovery metadata tests do not need the web server dependencies.
fastapi = types.ModuleType("fastapi")
fastapi.HTTPException = fastapi.Response = fastapi.Request = object
starlette = types.ModuleType("starlette")
responses = types.ModuleType("starlette.responses")
responses.StreamingResponse = object
sys.modules.setdefault("fastapi", fastapi)
sys.modules.setdefault("starlette", starlette)
sys.modules.setdefault("starlette.responses", responses)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vm-review'))
MODULE = Path(__file__).resolve().parents[1] / 'vm-review/aem_vm_discovery_live_candidate.py'
spec = importlib.util.spec_from_file_location('live_discovery', MODULE)
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)

class SharedPlssDiscoveryTest(unittest.TestCase):
    def test_all_states_use_same_groups_and_layer_aliases(self):
        groups = {
            'plssQuarterSections': 'plss_quarter_sections',
            'plssQuarterQuarterSections': 'plss_quarter_quarter',
            'plssSurveyPoints': 'plss_survey_points',
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            discovery.DATA = root
            discovery.CACHE_DATA = None
            for state in ('az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy'):
                folder = root / state
                folder.mkdir()
                (folder / 'state.json').write_text(json.dumps({'bounds': [-120, 30, -100, 50]}))
                for group, layer in groups.items():
                    dbfile = folder / (group + '.mbtiles')
                    with closing(sqlite3.connect(dbfile)) as db:
                        db.execute('create table metadata (name text, value text)')
                        db.executemany('insert into metadata values (?, ?)', [('format', 'pbf'), ('minzoom', '4'), ('maxzoom', '16'), ('json', json.dumps({'vector_layers': [{'id': layer}]}))])
                        db.commit()
                    os.utime(dbfile, (time.time() - 30, time.time() - 30))
            states, paths = discovery.discover_vm_data()
            self.assertEqual(len(states), 11)
            for state, info in states.items():
                for group, layer in groups.items():
                    self.assertEqual(info['datasets'][group]['sourceLayer'], layer, state)
                    self.assertEqual(info['datasets'][group]['minzoom'], {'plssQuarterSections': 11, 'plssQuarterQuarterSections': 12, 'plssSurveyPoints': 12}[group], state)
                    self.assertIn((state, group), paths)
            self.assertIn('plss_quarter_quarter_sections', discovery.GROUPS['plssQuarterQuarterSections'])
            self.assertIn('nm_plss_survey-points', discovery.GROUPS['plssSurveyPoints'])
            self.assertIn('plss_first_division', discovery.GROUPS['plssSections'])
            self.assertIn('nm_plss_sections', discovery.GROUPS['plssSections'])
            self.assertIn('nm_plss_townships', discovery.GROUPS['plssTownships'])
            self.assertIn('nm_plss_special-surveys', discovery.GROUPS['plssSpecialSurveys'])

if __name__ == '__main__':
    unittest.main()
