#!/usr/bin/env python3
"""Convert the existing producer's zoom property to Tippecanoe's feature hint.

Only zooms 4–6 are generated here. Detailed zooms remain in the old archive.
"""
import json
import sys

for line in sys.stdin:
    feature = json.loads(line)
    zoom = feature.get('properties', {}).get('tippecanoe:minimumzoom')
    if not isinstance(zoom, int) or not 4 <= zoom <= 15:
        raise ValueError('Missing or invalid road minimum zoom')
    if zoom > 6:
        continue
    feature['tippecanoe'] = {'minzoom': zoom}
    sys.stdout.write(json.dumps(feature, separators=(',', ':')) + '\n')
