import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vm-review'))
from aem_route_config import STATES, STATE_NAMES, parcel_archive


class RouteStateCoverageTests(unittest.TestCase):
    def test_every_supported_state_has_a_parcel_archive_path(self):
        self.assertEqual(set(STATES), {'az', 'ca', 'co', 'id', 'mt', 'nm',
                                       'nv', 'or', 'ut', 'wa', 'wy'})
        self.assertEqual(len(STATE_NAMES.values()), len(set(STATE_NAMES.values())))
        for state in STATES:
            path = parcel_archive(state)
            self.assertEqual(path.parent.name, 'tiles')
            self.assertEqual(path.name, f'{state}-parcels.' +
                             ('pmtiles' if state == 'nv' else 'mbtiles'))


if __name__ == '__main__':
    unittest.main()
