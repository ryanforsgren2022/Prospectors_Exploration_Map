#!/usr/bin/env python3
"""Download Wyoming second-division features in pages with a disk reserve."""
import json, os, shutil, time, urllib.parse, urllib.request
from pathlib import Path

base = 'https://services.wygisc.org/hostgis/rest/services/GeoHub/BLMPLSSQuarterQuarterSections/MapServer/0/query'
work = Path('/root/arizona-naip-build/prospectors-west/plss-state-full-v1/wy/source-20261028')
work.mkdir(parents=True, exist_ok=True)
out = work / 'second-division.geojsonl.partial'
if out.exists() or (work / 'second-division.geojsonl').exists():
    raise SystemExit('Existing source preserved; refusing to overwrite')

def query(params):
    url = base + '?' + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = json.load(response)
            if 'error' in data:
                raise ValueError(str(data['error']))
            return data
        except Exception:
            if attempt == 4: raise
            time.sleep(2 ** attempt)

count = query({'where':'1=1', 'returnCountOnly':'true', 'f':'json'})['count']
print('expected features:', count, flush=True)
last_id = -1
written = 0
with out.open('x') as f:
    while written < count:
        if shutil.disk_usage(work).free < 15 * 1024 ** 3:
            raise SystemExit('Stopped: less than 15 GiB free; partial source preserved')
        data = query({'where':f'OBJECTID > {last_id}', 'outFields':'*', 'returnGeometry':'true', 'outSR':4326, 'resultRecordCount':1000, 'orderByFields':'OBJECTID ASC', 'f':'geojson'})
        features = data.get('features', [])
        if not features: raise RuntimeError('Empty page before expected count')
        for feature in features:
            oid = feature.get('properties', {}).get('OBJECTID')
            if not isinstance(oid, int) or oid <= last_id or not feature.get('geometry'):
                raise RuntimeError(f'Invalid ordering or geometry at OBJECTID {oid}')
            last_id = oid
            f.write(json.dumps(feature, separators=(',', ':')) + '\n')
        written += len(features)
        if written % 50000 < 1000 or written == count:
            f.flush()
            print('downloaded', written, 'of', count, 'last object id', last_id, flush=True)
if written != count: raise RuntimeError(f'Count mismatch: {written} versus {count}')
if query({'where':'1=1','returnCountOnly':'true','f':'json'})['count'] != count:
    raise RuntimeError('Source count changed during download; partial source preserved for review')
os.rename(out, work / 'second-division.geojsonl')
(work / 'source-manifest.json').write_text(json.dumps({'source':base,'features':written,'last_objectid':last_id}, indent=2)+'\n')
print('Source download complete; no tiles have been built.', flush=True)
