"""State historic-mine MBTiles and source detail records; Arizona deltas stay live."""
from contextlib import closing
from pathlib import Path
import gzip,hashlib,json,math,sqlite3
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response,JSONResponse
from mapbox_vector_tile.Mapbox import vector_tile_pb2

ROOT=Path(__file__).resolve().parent/'data'
COVERAGE={'az':(9,14),'nv':(4,18),'ut':(4,14)}
router=APIRouter()

def connection(path):
    return closing(sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=5))

def state_root(state):
    if state not in COVERAGE:raise HTTPException(404,'Historic mines are not installed for this state')
    return ROOT/state/'historic-mines'

def properties(layer,feature):
    return {layer.keys[k]:layer.values[v].ListFields()[0][1] for k,v in zip(feature.tags[::2],feature.tags[1::2])}

def assign_properties(layer,feature,props):
    keys={k:i for i,k in enumerate(layer.keys)}
    for k,v in props.items():
        if v is None or v=='':continue
        if k not in keys:keys[k]=len(layer.keys);layer.keys.append(k)
        a=layer.values.add()
        if isinstance(v,bool):a.bool_value=v
        elif isinstance(v,int):a.sint_value=v
        elif isinstance(v,float):a.double_value=v
        else:a.string_value=str(v)
        feature.tags.extend([keys[k],len(layer.values)-1])

def arizona_updates():
    with connection(ROOT/'az-historic-mines-delta.sqlite3') as c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN')
        delta=[dict(r) for r in c.execute('select * from delta')]
        removed={r[0] for r in c.execute('select dep_id from removed')}
        return delta,removed

def delta_properties(row):
    # Commodity names use the same pinned mapping as the normalized archives.
    codes=json.loads((ROOT/'az/historic-mines/commodity-code-map.json').read_text())
    names=', '.join(dict.fromkeys(codes.get(w,w) for w in (row.get('code_list') or '').split()))
    return {'feature_id':'az:mrds:'+row['dep_id'],'dep_id':row['dep_id'],'source_id':row['dep_id'],'state_code':'az','source_dataset':'mrds','site_name':row['site_name'],'dev_stat':row['dev_stat'],'code_list':row['code_list'],'commodity':names,'commod1':names,'grade':row['grade'],'source_label':'Current USGS MRDS record','source_updated_at':row['synced_at']}

def merge_arizona(blob,z,x,y,delta,removed):
    t=vector_tile_pb2.tile()
    if blob:t.ParseFromString(gzip.decompress(blob) if blob[:2]==b'\x1f\x8b' else blob)
    if not t.layers:
        layer=t.layers.add();layer.name='historic_mines';layer.version=2;layer.extent=4096
    layer=t.layers[0]
    superseded=removed|{r['dep_id'] for r in delta}
    for i in range(len(layer.features)-1,-1,-1):
        if str(properties(layer,layer.features[i]).get('dep_id')) in superseded:del layer.features[i]
    for row in delta:
        if row['dep_id'] in removed:continue
        n=2**z;tx=(row['lon']+180)/360*n;ty=(1-math.asinh(math.tan(math.radians(max(-85.05112878,min(85.05112878,row['lat'])))))/math.pi)/2*n
        if not (x<=tx<x+1 and y<=ty<y+1):continue
        px=round((tx-x)*layer.extent);py=round((ty-y)*layer.extent)
        f=layer.features.add();f.type=1;f.geometry.extend([9,(px<<1)^(px>>31),(py<<1)^(py>>31)]);assign_properties(layer,f,delta_properties(row))
    return gzip.compress(t.SerializeToString(),compresslevel=6,mtime=0) if layer.features else None

def tile_response(state,z,x,y):
    folder=state_root(state);lo,hi=COVERAGE[state]
    if not lo<=z<=hi or not (0<=x<2**z and 0<=y<2**z):raise HTTPException(404,'Outside native historic-mine tile coverage')
    try:
        with connection(folder/'tiles'/(state+'-historic-mines.mbtiles')) as c:
            row=c.execute('select tile_data from tiles where zoom_level=? and tile_column=? and tile_row=?',(z,x,2**z-1-y)).fetchone()
        blob=row[0] if row else None
        if state=='az':blob=merge_arizona(blob,z,x,y,*arizona_updates())
    except (sqlite3.Error,OSError,ValueError) as error:raise HTTPException(503,'Historic-mine dataset unavailable') from error
    headers={'Cache-Control':'public, max-age='+('120' if state=='az' else '600')}
    if not blob:return Response(status_code=204,headers=headers)
    headers['ETag']='"'+hashlib.sha256(blob).hexdigest()+'"'
    if blob[:2]==b'\x1f\x8b':headers['Content-Encoding']='gzip'
    return Response(blob,media_type='application/vnd.mapbox-vector-tile',headers=headers)

@router.get('/{state}/historic-mines/tilejson.json')
def tilejson(state:str):
    folder=state_root(state);lo,hi=COVERAGE[state]
    manifest=json.loads((folder/(state+'-historic-mines.manifest.json')).read_text())
    return {'tilejson':'3.0.0','name':state+' historic mines','scheme':'xyz','tiles':[f'https://tiles.americanexplorationmaps.com/{state}/historic-mines/{{z}}/{{x}}/{{y}}.pbf'],'minzoom':lo,'maxzoom':hi,'bounds':manifest['bounds'],'vector_layers':[{'id':'historic_mines','fields':manifest['fields']}],'promoteId':'dep_id','featureIdField':'feature_id','records':f'https://tiles.americanexplorationmaps.com/{state}/historic-mines/records/{{feature_id}}','dynamicUpdates':state=='az'}

@router.get('/{state}/historic-mines/records/{feature_id}')
def record(state:str,feature_id:str):
    folder=state_root(state)
    if not feature_id.startswith(state+':') or len(feature_id)>128:raise HTTPException(404,'Unknown mine record')
    try:
        with connection(folder/(state+'-historic-mines.records.sqlite')) as c:
            row=c.execute('select source_id,longitude,latitude,properties_json,source_json from records where feature_id=?',(feature_id,)).fetchone()
        if state=='az':
            delta,removed=arizona_updates();sid=feature_id.removeprefix('az:mrds:')
            if sid in removed:raise HTTPException(404,'Record removed by current source update')
            changed=next((r for r in delta if r['dep_id']==sid),None)
            if changed:
                return JSONResponse({'feature_id':feature_id,'coordinates':[changed['lon'],changed['lat']],'properties':delta_properties(changed),'source_record':changed,'baseline_source_record':json.loads(row[4]) if row else None,'coordinate_provenance':'current MRDS update coordinates'},headers={'Cache-Control':'public, max-age=120'})
        if not row:raise HTTPException(404,'Unknown mine record')
        return JSONResponse({'feature_id':feature_id,'coordinates':[row[1],row[2]] if row[1] is not None else None,'properties':json.loads(row[3]),'source_record':json.loads(row[4]),'coordinate_provenance':'original source geometry' if state!='az' else 'existing tile coordinates, quantized'},headers={'Cache-Control':'public, max-age=600'})
    except (sqlite3.Error,OSError,ValueError) as error:raise HTTPException(503,'Historic-mine record unavailable') from error

@router.get('/{state}/historic-mines/{z}/{x}/{y}.pbf')
def historic_mines_tile(state:str,z:int,x:int,y:int):
    return tile_response(state,z,x,y)
