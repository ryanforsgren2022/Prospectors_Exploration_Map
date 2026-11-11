import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

const app = readFileSync(new URL('../source-dist/app.js', import.meta.url), 'utf8');
function loader(layers = [{ id: 'actual_mines' }], fail = false) {
  const sources = new Map();
  const requested = [];
  const context = vm.createContext({ URL, console: { warn() {} }, pmtiles: { PMTiles: class {
    constructor(url) { requested.push(url); }
    async getHeader() {
      if (fail) throw new Error('unreachable');
      return { minLon: -115, minLat: 31, maxLon: -109, maxLat: 37, minZoom: 3, maxZoom: 14 };
    }
    async getMetadata() { return { vector_layers: layers }; }
  } }, map: {
    getSource: id => sources.get(id),
    addSource: (id, source) => sources.set(id, source)
  } });
  vm.runInContext(app.slice(app.indexOf('const PROSPECTOR_R2_BASE_URL'),
    app.indexOf('function initializeProspectorState(')), context);
  vm.runInContext(app.slice(app.indexOf('function resolveProspectorPlss('),
    app.indexOf('const PROSPECTOR_STANDARD_GROUPS')), context);
  return { context, sources, requested };
}

test('all non-mine VM definitions retain paths, PLSS sublayers and claims semantics', async () => {
  const { context } = loader();
  const datasets = {
    claims: { tiles: ['https://tiles.americanexplorationmaps.com/az/not-closed/{z}/{x}/{y}.pbf'], sourceLayer: 'not_closed', semantics: 'notClosed', classificationFilter: { rule: 'notClosed', unknownPolicy: 'report-separately' } },
    activeClaims: { sourceLayer: 'active_only' },
    plss: { townshipsLayer: 'townships_actual', sectionsLayer: 'sections_actual', aliquotsLayer: 'aliquots_actual' },
    withdrawals: { url: 'pmtiles://https://tiles.americanexplorationmaps.com/api/vm-data/az/withdrawals.pmtiles' },
    parcels: { tiles: ['existing-parcels-route'] }
  };
  const result = await context.prepareProspectorDatasets('az', { datasets });
  for (const [key, dataset] of Object.entries(datasets)) assert.equal(result[key], dataset);
  assert.equal(context.resolveProspectorPlss('az', result, 'sections'), datasets.plss);
  assert.equal(context.resolveProspectorPlss('nv', result, 'townships'), datasets.plss);
});

test('mine R2 path uses actual archive metadata and passes extent into map source', async () => {
  const { context, sources, requested } = loader();
  const result = await context.prepareProspectorDatasets('az', {});
  assert.equal(requested[0], 'https://data.americanexplorationmaps.com/prospectors/az/historic-mines.pmtiles');
  assert.equal(result.historicMines.sourceLayer, 'actual_mines');
  context.addProspectorSource('mines', {}, result.historicMines);
  const source = sources.get('mines');
  assert.equal(source.url, 'pmtiles://' + requested[0]);
  assert.equal(source.minzoom, 3);
  assert.equal(source.maxzoom, 14);
  assert.deepEqual(Array.from(source.bounds), [-115, 31, -109, 37]);
});

test('ambiguous or inaccessible mines do not silently fall back to a VM substitute', async () => {
  for (const { context } of [loader([{ id: 'one' }, { id: 'two' }]), loader([], true)]) {
    const result = await context.prepareProspectorDatasets('nv', { datasets: {
      historicMines: { url: 'old-vm-source' }, claims: { sourceLayer: 'not_closed', semantics: 'notClosed', classificationFilter: { rule: 'notClosed', unknownPolicy: 'report-separately' } }
    } });
    assert.equal(result.historicMines, undefined);
    assert.equal(result.claims.sourceLayer, 'not_closed');
  }
});

test('multiple mine source layers require an exact discovered metadata match', async () => {
  const { context } = loader([{ id: 'one' }, { id: 'two' }]);
  const result = await context.prepareProspectorDatasets('nv', { datasets: { historicMines: { sourceLayer: 'two' } } });
  assert.equal(result.historicMines.sourceLayer, 'two');
});

test('mine archives select their point layer when polygon layers are also present', async () => {
  for (const code of ['az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy']) {
    const { context } = loader([{ id: 'historic_mines_points' }, { id: 'historic_mines_polygons' }]);
    const result = await context.prepareProspectorDatasets(code, {});
    assert.equal(result.historicMines.sourceLayer, 'historic_mines_points', code);
  }
});

test('historic metadata starts only for eligible states and only once per state', async () => {
  const requests = [];
  const scheduled = [];
  let zoom = 4.5;
  let enabled = false;
  let visibleCode = 'az';
  const context = vm.createContext({
    URL, console: { warn() {}, log() {}, info() {} },
    pmtiles: { PMTiles: class {
      constructor(url) { requests.push(url); }
      async getHeader() { return { minLon: -115, minLat: 31, maxLon: -109, maxLat: 37, minZoom: 3, maxZoom: 14 }; }
      async getMetadata() { return { vector_layers: [{ id: 'mines' }] }; }
    } },
    window: { requestAnimationFrame: callback => scheduled.push(callback), setTimeout: () => 1, clearTimeout() {} },
    document: { querySelector: selector => ({ checked: selector === '#historicMines' && enabled }) },
    map: { getZoom: () => zoom, getStyle: () => ({ layers: [] }),
      getBounds: () => ({ getWest: () => visibleCode === 'az' ? 0 : 10, getEast: () => visibleCode === 'az' ? 1 : 11, getSouth: () => 0, getNorth: () => 1 }),
      getSource: () => null, addSource() {}, getLayer: () => null, addLayer() {}, on() {} },
    setLayerVisibility() {}, applyHistoricMineVisitedStates() {}
  });
  for (const name of ['SURFACE_MANAGEMENT_LAYER_IDS', 'NOT_CLOSED_CLAIMS_LAYER_IDS', 'PROPERTY_PARCELS_LAYER_IDS', 'PLSS_TOWNSHIPS_LAYER_IDS', 'PLSS_SECTIONS_LAYER_IDS', 'HISTORIC_MINES_ARCHIVE_LAYER_ID']) {
    vm.runInContext(app.match(new RegExp(`const ${name} = [^;]+;`))[0], context);
  }
  vm.runInContext("const PROSPECTOR_STYLE_TEMPLATES = []; const WITHDRAWAL_TEMPLATES = [];", context);
  vm.runInContext(app.slice(app.indexOf('const prospectorStateRegistry'), app.indexOf('async function initializeProspectorStateLoader')), context);
  vm.runInContext(`for (const code of ['az','ca','co','id','mt','nm','nv','or','ut','wa','wy']) {
    prospectorStateRegistry.set(code, { bounds: code === 'az' ? [0,0,1,1] : [10,0,11,1], datasets: {} });
  }`, context);
  context.syncProspectorStates();
  enabled = true;
  context.syncProspectorStates();
  assert.equal(requests.length, 0, 'disabled or below zoom threshold must not open archives');
  zoom = 7;
  context.syncProspectorStates();
  context.syncProspectorStates();
  assert.equal(requests.length, 1, 'repeated sync shares the in-flight metadata request');
  assert.match(requests[0], /\/az\/historic-mines\.pmtiles$/);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(vm.runInContext("prospectorStateRegistry.get('az').datasets.historicMines.sourceLayer", context), 'mines');
  visibleCode = 'other';
  context.syncProspectorStates();
  assert.equal(requests.length, 11, 'all eligible states use the same lazy path');
});

test('discovery consumers share one request and refresh failures can retry', async () => {
  let calls = 0;
  let fail = false;
  const context = vm.createContext({ fetch: async () => {
    calls++;
    return { ok: !fail, status: 503, json: async () => ({ schemaVersion: 2, states: {} }) };
  } });
  vm.runInContext(app.slice(app.indexOf('let stateDiscoveryPromise'), app.indexOf('/*\n * A state can be initialized')), context);
  await Promise.all([context.loadStateDiscovery(), context.loadStateDiscovery()]);
  assert.equal(calls, 1);
  fail = true;
  await assert.rejects(context.loadStateDiscovery(true));
  fail = false;
  await context.loadStateDiscovery();
  assert.equal(calls, 3);
  assert.match(app, /map\.once\('style\.load',\s*\(\) => refreshDynamicVMMapLayers\(\)\)/);
});

test('move and zoom completion coalesce into one settled update', () => {
  const frames = [];
  const events = {};
  const calls = [];
  const context = vm.createContext({ window: { requestAnimationFrame: callback => frames.push(callback) },
    map: { on: (name, callback) => { events[name] = callback; } },
    syncDynamicVMMapLayers: () => calls.push('vm'), syncAccessPresentation: () => calls.push('access'),
    scheduleProspectorStateSync: () => calls.push('state') });
  vm.runInContext(app.slice(app.indexOf('let unifiedProspectorEventsEnabled'), app.indexOf("map.on('click', (event)")), context);
  vm.runInContext('unifiedProspectorEventsEnabled = true', context);
  events.moveend();
  events.zoomend();
  assert.equal(frames.length, 1);
  frames.shift()();
  assert.deepEqual(calls, ['vm', 'access', 'state']);
});

test('relative archive resolution uses only an explicit VM base', () => {
  const { context } = loader();
  assert.equal(context.prospectorsDatasetUrl({ baseUrl: 'https://tiles.americanexplorationmaps.com/api/vm-data/az/' },
    { file: 'existing.pmtiles' }), 'pmtiles://https://tiles.americanexplorationmaps.com/api/vm-data/az/existing.pmtiles');
  assert.equal(context.prospectorsDatasetUrl({}, { file: 'unknown.pmtiles' }), null);
});

test('roads use one continuous V3 R2 source with no state switching or clipping', () => {
  assert.ok(app.includes("url: 'pmtiles://' + CONTINUOUS_ROADS_URL"));
  assert.ok(app.includes("const CONTINUOUS_ROADS_URL = 'https://data.americanexplorationmaps.com/prospectors/western-roads-z6-filtered-20261030.pmtiles'"));
  assert.match(app, /roads:\s*\{[\s\S]*?type:\s*'vector',[\s\S]*?url:\s*'pmtiles:\/\/' \+ CONTINUOUS_ROADS_URL,[\s\S]*?minzoom:\s*4,[\s\S]*?maxzoom:\s*15,/);
  assert.ok(app.includes("source: 'roads', 'source-layer': 'roads'"));
  assert.doesNotMatch(app, /activeStateRoad|stateRoad/);
  assert.doesNotMatch(app, /removeSource\(['\"]roads['\"]\)/);
  assert.doesNotMatch(app, /source:\s*'roads'[\s\S]{0,200}filter:\s*\[[^\]]*within/);
});

test('initial zoom and shared road classes restore progressive visibility', () => {
  assert.match(app, /center:\s*\[-111\.40, 33\.40\],\s*zoom:\s*4\.5/);
  const context = vm.createContext({});
  vm.runInContext(app.slice(app.indexOf('const WESTERN_ROAD_GROUPS'),
    app.indexOf('// Scale thresholds translated')), context);
  const layers = vm.runInContext('westernRoadStyles()', context);
  const thresholds = {
    'western-trails': 8.5, 'access-roads-casing': 8.5, 'access-roads': 8.5,
    'local-road-casing': 10.5, 'local-roads': 10.5,
    'secondary-road-casing': 7, 'secondary-roads': 7,
    'managed-road-casing': 7, 'managed-roads': 7,
    'state-road-casing': 6.1, 'state-roads': 6.1,
    'primary-road-casing': 2, 'primary-roads': 2
  };
  const lines = layers.filter(layer => layer.type === 'line');
  assert.equal(lines.length, Object.keys(thresholds).length);
  for (const layer of lines) {
    assert.equal(layer.source, 'roads');
    assert.equal(layer.minzoom, thresholds[layer.id], layer.id);
  }

});

test('road filters retain the two-level offset without being reset while zooming', () => {
  const context = vm.createContext({});
  vm.runInContext(app.slice(app.indexOf('const WESTERN_ROAD_GROUPS'),
    app.indexOf('// Scale thresholds translated')), context);
  const layers = vm.runInContext('westernRoadStyles()', context);
  for (const layer of layers) {
    const filter = layer.filter.at(-1);
    assert.equal(JSON.stringify(filter), JSON.stringify(['<=',
      ['to-number', ['get', 'tippecanoe:minimumzoom'], 0],
      ['+', ['floor', ['zoom']], 2]]));
  }
  assert.doesNotMatch(app, /syncRoadFeatureZoom|map\.setFilter\(/);
});

test('discovered VM datasets use one generic path across states without duplicating known layers', () => {
  const context = vm.createContext({ PROSPECTOR_GROUP_NAMES: ['boundary', 'claims', 'historicMines'],
    prospectorVmDatasets: state => ({ boundary: state.datasets.boundary }),
    aemVMSourceDefinition: item => item.url ? { url: item.url } : null });
  vm.runInContext(app.slice(app.indexOf('function discoverGenericVmLayers'),
    app.indexOf('function syncDynamicVMMapLayers')), context);
  for (const state of ['az', 'nv', 'wy']) {
    const url = `pmtiles://https://tiles.americanexplorationmaps.com/api/vm-data/${state}/`;
    const layers = context.discoverGenericVmLayers({ datasets: {
      boundary: { sourceLayer: 'boundary', url: url + 'boundary.pmtiles' },
      claims: { sourceLayer: 'mining_claims', url: url + 'claims.pmtiles' },
      historicMines: { sourceLayer: 'historic_mines', url: url + 'historicMines.pmtiles' },
      newLayer: { sourceLayer: 'new_layer', url: url + 'newLayer.pmtiles' }
    }});
    assert.deepEqual(Array.from(layers, layer => layer.id), ['dataset_claims', 'dataset_newLayer']);
    assert.ok(layers.every(layer => context.isGenericVmLayerId(layer.id)));
  }
});

test('all state boundaries use one VM-discovered lifecycle and shared viewability style', () => {
  assert.doesNotMatch(app, /PERMANENT_STATE_BOUNDARY|permanent-western-state-borders|western-state-boundaries\.geojson|arizona-state-border/);
  assert.match(app, /id:\s*'state-boundary-line',[\s\S]*?source-layer':\s*'boundary',[\s\S]*?minzoom:\s*4/);
  assert.match(app, /group === 'boundary'[\s\S]*?templateId:\s*'state-boundary-line'/);
});

test('withdrawals use shared state templates without a Nevada-only overview layer', () => {
  assert.doesNotMatch(app, /nv-withdrawals-overview|syncNevadaWithdrawalOverview/);
  assert.match(app, /group === 'withdrawals'[\s\S]*?const dataset = datasets\.withdrawals/);
  assert.match(app, /if \(group === 'withdrawals'\) \{[\s\S]*?prospectorToggleChecked\(\s*'miningWithdrawals'/);
});

test('off-screen overlays are evicted and reattach uniformly without removing roads or boundaries', () => {
  const sources = new Map([['roads', {}]]);
  const layers = new Map();
  const listeners = new Map();
  const timers = new Map();
  let timerId = 0;
  let inView = false;
  const context = vm.createContext({ URL, console: { info() {}, warn() {}, log() {} },
    window: { setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id) },
    map: {
      getSource: id => sources.get(id), addSource: (id, source) => sources.set(id, source),
      removeSource: id => { assert.notEqual(id, 'roads'); sources.delete(id); },
      getLayer: id => layers.get(id), addLayer: layer => layers.set(layer.id, layer),
      removeLayer: id => layers.delete(id), getStyle: () => ({ layers: [...layers.values()] }),
      getBounds: () => ({ getWest: () => inView ? 0 : 5, getEast: () => inView ? 1 : 6, getSouth: () => 0, getNorth: () => 1 }),
      on: (event, id, fn) => listeners.set(`${event}:${id}`, fn),
      off: (event, id, fn) => { assert.equal(listeners.get(`${event}:${id}`), fn); listeners.delete(`${event}:${id}`); }
    }, document: { querySelector: () => ({ checked: true }) }, applyHistoricMineVisitedStates() {} });
  for (const name of ['SURFACE_MANAGEMENT_LAYER_IDS', 'NOT_CLOSED_CLAIMS_LAYER_IDS', 'PROPERTY_PARCELS_LAYER_IDS', 'PLSS_TOWNSHIPS_LAYER_IDS', 'PLSS_SECTIONS_LAYER_IDS', 'HISTORIC_MINES_ARCHIVE_LAYER_ID']) {
    vm.runInContext(app.match(new RegExp(`const ${name} = [^;]+;`))[0], context);
  }
  vm.runInContext("const PROSPECTOR_STYLE_TEMPLATES = [{id:'state-boundary-line',type:'line'},{id:HISTORIC_MINES_ARCHIVE_LAYER_ID,type:'circle'}]; const WITHDRAWAL_TEMPLATES = [];", context);
  vm.runInContext(app.slice(app.indexOf('const prospectorStateRegistry'), app.indexOf('async function initializeProspectorStateLoader')), context);
  const codes = ['az','ca','co','id','mt','nm','nv','or','ut','wa','wy'];
  for (const code of codes) {
    const state = { datasets: { boundary: { tiles: ['boundary'], sourceLayer: 'boundary' }, historicMines: { tiles: ['mines'], sourceLayer: 'mines' } } };
    context.ensureProspectorGroup(code, state, 'boundary');
    context.ensureProspectorGroup(code, state, 'historicMines');
    context.scheduleOffscreenEviction(`prospector:${code}`, [0, 0, 1, 1], false, () => context.evictProspectorOverlays(code));
  }
  assert.equal(listeners.size, 33);
  inView = true;
  context.scheduleOffscreenEviction('prospector:az', [0, 0, 1, 1], true, () => assert.fail('re-entry must cancel eviction'));
  assert.equal(timers.size, 10);
  inView = false;
  for (const callback of timers.values()) callback();
  assert.equal(listeners.size, 3);
  for (const code of codes.slice(1)) {
    assert.ok(sources.has(`prospector-${code}-boundary`));
    assert.ok(!sources.has(`prospector-${code}-historic-mines`));
    context.ensureProspectorGroup(code, { datasets: { historicMines: { tiles: ['mines'], sourceLayer: 'mines' } } }, 'historicMines');
  }
  assert.equal(listeners.size, 33);
  assert.ok(sources.has('roads'));
});

test('automatic VM overlays use the same delayed off-screen cleanup and restore', () => {
  const sources = new Map();
  const layers = new Map();
  const timers = new Map();
  let inView = true;
  let timerId = 0;
  const context = vm.createContext({ console: { warn() {} },
    window: { setTimeout: callback => { timers.set(++timerId, callback); return timerId; }, clearTimeout: id => timers.delete(id) },
    map: { getStyle: () => ({ layers: [{}] }), getSource: id => sources.get(id), addSource: (id, source) => sources.set(id, source),
      removeSource: id => sources.delete(id), getLayer: id => layers.get(id), addLayer: layer => layers.set(layer.id, layer),
      removeLayer: id => layers.delete(id), setLayoutProperty() {} },
    prospectorsStateIntersectsView: () => inView });
  vm.runInContext(app.slice(app.indexOf('const offscreenEvictionTimers'), app.indexOf('function evictProspectorOverlays')), context);
  vm.runInContext(app.slice(app.indexOf('const aemVMRegistry'), app.indexOf('function aemVMRenderControls')), context);
  vm.runInContext(`aemVMRegistry.set('az', {bounds:[0,0,1,1], autoLayers:[{id:'auto_0123456789abcdef', sourceLayer:'layer', tiles:['https://tiles.americanexplorationmaps.com/api/vm-data/az/{z}/{x}/{y}.pbf']}]})`, context);
  context.syncDynamicVMMapLayers();
  assert.equal(sources.size, 1);
  assert.equal(layers.size, 3);
  inView = false;
  context.syncDynamicVMMapLayers();
  assert.equal(timers.size, 1);
  [...timers.values()][0]();
  assert.equal(sources.size, 0);
  assert.equal(layers.size, 0);
  inView = true;
  context.syncDynamicVMMapLayers();
  assert.equal(sources.size, 1);
  assert.equal(layers.size, 3);
});

test('roads start after the first map load or a bounded fallback', () => {
  assert.match(app, /let startupRoadsReady = false/);
  assert.match(app, /map\.once\('load', startRoads\)/);
  assert.match(app, /window\.setTimeout\(startRoads, 4000\)/);
  assert.match(app, /pixelRatio:\s*isMobile \? Math\.min\(window\.devicePixelRatio \|\| 1, 1\.5\)/);
  assert.match(app, /maxTileCacheZoomLevels:\s*4/);
  assert.doesNotMatch(app, /prefetchZoomDelta/);
});

test('road startup runs once and honors a toggle made before the fallback', () => {
  for (const initiallyEnabled of [true, false]) {
    const events = new Map();
    const timers = new Map();
    const frames = [];
    const calls = [];
    let timerId = 0;
    const context = vm.createContext({
      window: { setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; }, clearTimeout: id => timers.delete(id) },
      requestAnimationFrame: fn => frames.push(fn),
      map: { once: (name, fn) => events.set(name, fn), off: name => events.delete(name), resize() {}, setTerrain: () => calls.push('terrain'), easeTo() {} },
      DEVICE: { targetPitch: 45, targetBearing: -14, initialTerrainTransition: 0 },
      syncTwoDHillshade() {}, syncRoadView: () => calls.push('roads'), syncZoomPresentation() {},
      addSurfaceManagementMilitaryPattern() {},
      setMiningWithdrawalsVisible() {}, setHistoricMinesVisible() {},
      afterSourceSettles: (id, fn) => { calls.push(`settled:${id}`); fn(); },
      terrainEnabled: true, miningWithdrawalsEnabled: false, historicMinesEnabled: false,
      roadRenderingEnabled: initiallyEnabled, startupRoadsReady: false
    });
    vm.runInContext(app.slice(app.indexOf("map.once('style.load', () => {"), app.indexOf('map.addControl(')), context);
    events.get('style.load')();
    const timer = [...timers.values()].find(t => t.delay === 4000);
    timer.fn();
    assert.equal(context.startupRoadsReady, true);
    assert.equal(events.has('load'), false);
    timer.fn();
    for (const frame of frames) frame();
    assert.equal(calls.filter(call => call === 'terrain').length, 1);
    assert.equal(calls.filter(call => call === 'roads').length, 2);
    assert.equal(calls.includes('settled:roads'), initiallyEnabled);
  }
});

test('the legacy Idaho BLM-only control is absent from the shared claims loader', async () => {
  const { context } = loader();
  const result = await context.prepareProspectorDatasets('id', { datasets: {
    claims: { sourceLayer: 'claims' },
    claimsBlmLands: { sourceLayer: 'claims', semantics: 'notClosed', classificationFilter: { rule: 'notClosed', unknownPolicy: 'report-separately' }, coverage: 'BLM lands only' }
  } });
  assert.equal(result.claims, undefined);
  assert.equal(result.claimsBlmLands, undefined);
});

test('every supported state uses the same z5 claims control', () => {
  const html = readFileSync(new URL('../source-dist/index.html', import.meta.url), 'utf8');
  const codes = ['az', 'ca', 'co', 'id', 'mt', 'nm', 'nv', 'or', 'ut', 'wa', 'wy'];
  assert.equal((html.match(/id="notClosedClaims"/g) || []).length, 1);
  assert.ok(!html.includes('blmLandsClaims'));
  assert.match(app, /const NOT_CLOSED_CLAIMS_MIN_ZOOM = 5;/);
  const { context } = loader();
  context.document = { querySelector: selector => ({ checked: selector === '#notClosedClaims' }) };
  vm.runInContext('const PROSPECTOR_EXTRA_PLSS = {};', context);
  vm.runInContext(app.slice(app.indexOf('function prospectorToggleChecked('),
    app.indexOf('/* AEM UNIVERSAL PLSS ROUTE RESOLUTION V1 */')), context);
  vm.runInContext(app.slice(app.indexOf('function prospectorGroupToggleEnabled('),
    app.indexOf('function prospectorGroupShouldRender(')), context);
  for (const code of codes) {
    const state = { datasets: { claims: { sourceLayer: 'claims', minzoom: 5,
      semantics: 'notClosed', classificationFilter: { rule: 'notClosed', unknownPolicy: 'report-separately' } } } };
    assert.equal(context.prospectorVmDatasets(state).claims.minzoom, 5, code);
    assert.equal(context.prospectorGroupToggleEnabled('claims'), true, code);
  }
});

test('every audit registration attaches its actual source layer, including all PLSS and split withdrawals', () => {
  const registry = JSON.parse(readFileSync(new URL('../vm-review/western-datasets.json', import.meta.url)));
  const sources = new Map();
  const layers = new Map();
  const context = vm.createContext({ URL, console: { info() {}, warn() {}, log() {} }, map: {
    getSource: id => sources.get(id), addSource: (id, source) => sources.set(id, source),
    getLayer: id => layers.get(id), addLayer: layer => layers.set(layer.id, layer),
    getStyle: () => ({ layers: [...layers.values()] }), on() {},
  }, document: { querySelector: () => ({ checked: true }) } });
  const constants = ['SURFACE_MANAGEMENT_LAYER_IDS', 'NOT_CLOSED_CLAIMS_LAYER_IDS', 'PROPERTY_PARCELS_LAYER_IDS',
    'PLSS_TOWNSHIPS_LAYER_IDS', 'PLSS_SECTIONS_LAYER_IDS', 'HISTORIC_MINES_ARCHIVE_LAYER_ID'];
  for (const constant of constants) {
    const declaration = app.match(new RegExp(`const ${constant} = [^;]+;`))[0];
    vm.runInContext(declaration, context);
  }
  vm.runInContext(app.slice(app.indexOf('const WITHDRAWAL_TEMPLATES'), app.indexOf('const NOT_CLOSED_CLAIMS_QUERY')), context);
  vm.runInContext(`const PROSPECTOR_STYLE_TEMPLATES = [
    ...SURFACE_MANAGEMENT_LAYER_IDS, ...NOT_CLOSED_CLAIMS_LAYER_IDS, ...PROPERTY_PARCELS_LAYER_IDS,
    ...PLSS_TOWNSHIPS_LAYER_IDS, ...PLSS_SECTIONS_LAYER_IDS, 'state-boundary-line'
  ].map(id => ({ id, type: 'line', layout: {} }));`, context);
  vm.runInContext(app.slice(app.indexOf('const prospectorStateRegistry'), app.indexOf('async function initializeProspectorStateLoader')), context);
  let checked = 0;
  for (const [code, state] of Object.entries(registry.states)) {
    const datasets = {};
    for (const [group, spec] of Object.entries(state.datasets).filter(([group]) => group !== 'claimsBlmLands')) {
      const dataset = { ...spec, tiles: [`https://tiles.americanexplorationmaps.com/api/vm-data/${code}/${group}/{z}/{x}/{y}.pbf`] };
      if (group.startsWith('withdrawals')) {
        (datasets.withdrawals ||= {})[group.slice('withdrawals'.length).toLowerCase()] = dataset;
      } else datasets[group] = dataset;
    }
    for (const group of Object.keys(datasets)) {
      assert.equal(context.ensureProspectorGroup(code, { ...state, datasets }, group), true, `${code}/${group}`);
    }
    for (const [group, spec] of Object.entries(state.datasets).filter(([group]) => group !== 'claimsBlmLands')) {
      const source = [...sources.entries()].find(([, definition]) => definition.tiles?.[0].includes(`/api/vm-data/${code}/${group}/`));
      assert.ok(source, `${code}/${group} source`);
      assert.equal(source[1].minzoom, spec.minzoom);
      assert.equal(source[1].maxzoom, spec.maxzoom);
      assert.deepEqual(Array.from(source[1].bounds), spec.bounds);
      assert.equal(source[1].tiles[0], `https://tiles.americanexplorationmaps.com/api/vm-data/${code}/${group}/{z}/{x}/{y}.pbf`);
      assert.ok([...layers.values()].some(layer => layer.source === source[0] && layer['source-layer'] === spec.sourceLayer), `${code}/${group} layer`);
      checked++;
    }
  }
  const layerCount = layers.size;
  for (const [code, state] of Object.entries(registry.states)) {
    // Repeated viewport/toggle sync must not create duplicate sources or layers.
    const groups = [...Object.keys(state.datasets).filter(g => !g.startsWith('withdrawals') && g !== 'claimsBlmLands'), 'withdrawals'];
    for (const group of groups) context.ensureProspectorGroup(code, state, group);
  }
  assert.equal(layers.size, layerCount);
  const azTownships = [...layers.values()].filter(l => l.id.startsWith('prospector-az-') && l['source-layer'] === 'plss_townships');
  assert.equal(azTownships.length, 3); // One fill, outline and label set; no combined-archive duplicate.
  assert.equal(new Set(azTownships.map(l => l.source)).size, 1);
  assert.equal(checked, 116);
  assert.equal(vm.runInContext('PROSPECTOR_GROUP_NAMES.at(-1)', context), 'parcels');
});
