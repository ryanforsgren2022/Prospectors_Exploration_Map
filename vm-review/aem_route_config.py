"""Shared state and data paths for Route Finder and route discovery."""
from pathlib import Path

STATE_NAMES = {
    'az': 'arizona', 'ca': 'california', 'co': 'colorado', 'id': 'idaho',
    'mt': 'montana', 'nm': 'new-mexico', 'nv': 'nevada', 'or': 'oregon',
    'ut': 'utah', 'wa': 'washington', 'wy': 'wyoming',
}
STATES = tuple(STATE_NAMES)
DATA_ROOT = Path('/root/LIVE_SITE_CASHE/live-mvt/data')
INDEX_ROOT = Path('/mnt/volume_sfo3_1794422503599/updater/data/search-v2')


def parcel_archive(state):
    if state not in STATE_NAMES:
        raise ValueError('Unsupported AEM state')
    extension = 'pmtiles' if state == 'nv' else 'mbtiles'
    return DATA_ROOT / state / 'parcels' / 'tiles' / f'{state}-parcels.{extension}'
