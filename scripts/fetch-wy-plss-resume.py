#!/usr/bin/env python3
"""Resume Wyoming source download with three concurrent requests and a disk reserve."""
import concurrent.futures, json, os, resource, shutil, time, urllib.parse, urllib.request
from pathlib import Path
resource.setrlimit(resource.RLIMIT_AS, (7 * 1024**3, 7 * 1024**3))
base='https://services.wygisc.org/hostgis/rest/services/GeoHub/BLMPLSSQuarterQuarterSections/MapServer/0/query'
work=Path('/root/arizona-naip-build/prospectors-west/plss-state-full-v1/wy/source-20261028')
out=work/'second-division.geojsonl.partial'
def query(params):
    encoded=urllib.parse.urlencode(params).encode()
    request=urllib.request.Request(base, data=encoded) if len(encoded)>1800 else urllib.request.Request(base+'?'+encoded.decode())
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request,timeout=90) as response: data=json.load(response)
            if 'error' in data: raise ValueError(str(data['error']))
            return data
        except Exception:
            if attempt==4: raise
            time.sleep(2**attempt)
ids=query({'where':'1=1','returnIdsOnly':'true','f':'json'}).get('objectIds')
if not ids: raise RuntimeError('No source object IDs returned')
ids.sort()
if len(ids)!=len(set(ids)): raise RuntimeError('Duplicate object IDs in source')
written=0
with out.open('rb+') as f:
    while True:
        start=f.tell(); line=f.readline()
        if not line: break
        if not line.endswith(b'\n'):
            f.truncate(start); print('Removed incomplete final line',flush=True); break
        obj=json.loads(line); oid=obj.get('properties',{}).get('OBJECTID')
        if written>=len(ids) or oid!=ids[written] or not obj.get('geometry'): raise RuntimeError(f'Existing source mismatch at record {written}: {oid}')
        written+=1
print('Resuming at',written,'of',len(ids),'records; workers=3; memory limit=7 GiB',flush=True)
def fetch(chunk):
    data=query({'objectIds':','.join(map(str,chunk)),'outFields':'*','returnGeometry':'true','outSR':4326,'f':'geojson'})
    features=data.get('features',[])
    features.sort(key=lambda x:x.get('properties',{}).get('OBJECTID',-1))
    actual=[x.get('properties',{}).get('OBJECTID') for x in features]
    if actual!=chunk or any(not x.get('geometry') for x in features): raise RuntimeError('Missing, duplicate, or nonspatial features in batch')
    return features
with out.open('a') as f, concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    while written < len(ids):
        if shutil.disk_usage(work).free < 15*1024**3: raise SystemExit('Stopped: less than 15 GiB free; partial source preserved')
        batches=[ids[i:i+1000] for i in range(written,min(written+3000,len(ids)),1000)]
        for features in pool.map(fetch,batches):
            for feature in features: f.write(json.dumps(feature,separators=(',',':'))+'\n')
            written+=len(features)
        f.flush()
        if written//50000 != (written-sum(map(len,batches)))//50000 or written==len(ids): print('downloaded',written,'of',len(ids),flush=True)
new_ids=query({'where':'1=1','returnIdsOnly':'true','f':'json'}).get('objectIds')
if not new_ids or sorted(new_ids)!=ids: raise RuntimeError('Source IDs changed during download; partial source preserved')
os.rename(out,work/'second-division.geojsonl')
(work/'source-manifest.json').write_text(json.dumps({'source':base,'features':written,'workers':3,'memory_limit_gib':7},indent=2)+'\n')
print('Source download complete; no tiles built.',flush=True)
